"""Built-in capture management: give the system its eyes.

`aframes record` provisions and runs a local, open-source capture engine
(event-driven screen + accessibility-tree + input recording into SQLite).
The engine binary is fetched once, pinned to a known MIT-licensed
version for reproducibility, and runs entirely on-device. Audio capture
is OFF by default.

The compilation layer (the rest of this package) is recorder-agnostic;
this module just makes the default pipeline self-contained:

    pip install activity-frames
    aframes record          # start capturing
    aframes context         # your last 2 hours, agent-ready
"""
from __future__ import annotations

import os
import platform
import signal
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

HOME_DIR = Path("~/.activity-frames").expanduser()
BIN_DIR = HOME_DIR / "bin"
PID_FILE = HOME_DIR / "recorder.pid"
LOG_FILE = HOME_DIR / "recorder.log"

# Pinned engine: nocta-recorder v0.1.0, the last MIT-licensed npm release.
# Each platform tarball is verified against its npm dist integrity hash
# (sha512) before extraction; a mismatch aborts the install.
_ENGINE_VERSION = "0.3.324"
_ENGINE_PACKAGES = {
    ("darwin", "arm64"): (
        "cli-darwin-arm64",
        "uWdkCmGxO8jPHT8A91PzPQe7paFHQZmZHIqIRtW3Ikeb5G2H/XLUHmq6CYMpgUio"
        "GAr8dSvIEbc00Tx9/qYYQg==",
    ),
    ("darwin", "x86_64"): (
        "cli-darwin-x64",
        "OpbKGyL5i7ep1IXG2wFrVlB5075hHeSjyrQh3ytfdMOz5DaqAsMAC6eLbQ2TnrGh"
        "K3EGPDqgn1pgLvA2RcmL3A==",
    ),
    ("linux", "x86_64"): (
        "cli-linux-x64",
        "gdEu4RWpTtn92LK6ySNRurmH27lYsbR0bfvWRWb0DDOC3HLn4yumII49PxhZ1dSU"
        "bNTKM1tBkCoHieY8iPLf2g==",
    ),
}
_REGISTRY = "https://registry.npmjs.org/@nocta-recorder/{pkg}/-/{pkg}-{ver}.tgz"


class CaptureError(RuntimeError):
    pass


def _platform_key() -> tuple[str, str]:
    sysname = platform.system().lower()
    machine = platform.machine().lower()
    if machine in ("aarch64",):
        machine = "arm64"
    if machine in ("amd64",):
        machine = "x86_64"
    return sysname, machine


def engine_path() -> Path:
    # The engine keeps its real name: it is a pinned nocta-recorder build.
    return BIN_DIR / "nocta-recorder"


def _find_system_engine() -> str | None:
    """An already-installed engine on PATH also works."""
    from shutil import which

    return which("nocta-recorder")


def _verify_sha512(path: Path, expected_b64: str) -> None:
    import base64
    import hashlib

    h = hashlib.sha512()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    actual = base64.b64encode(h.digest()).decode()
    if actual != expected_b64:
        raise CaptureError(
            "Engine download failed integrity verification "
            f"(expected sha512-{expected_b64[:16]}..., got sha512-{actual[:16]}...). "
            "Refusing to install. Retry, or install nocta-recorder yourself and "
            "re-run; anything named 'nocta-recorder' on PATH is used as-is."
        )


def ensure_engine(quiet: bool = False) -> str:
    """Return a runnable capture-engine binary, fetching it if needed.

    Downloads are pinned to a specific version AND verified against its
    published sha512 before anything is extracted or executed.
    """
    local = engine_path()
    if local.exists() and os.access(local, os.X_OK):
        return str(local)
    system = _find_system_engine()
    if system:
        return system

    key = _platform_key()
    entry = _ENGINE_PACKAGES.get(key)
    if not entry:
        raise CaptureError(
            f"No prebuilt capture engine for {key[0]}/{key[1]} yet. "
            "You can point activity-frames at any existing capture database "
            "via $AFRAMES_DB instead."
        )
    pkg, sha512_b64 = entry
    url = _REGISTRY.format(pkg=pkg, ver=_ENGINE_VERSION)
    if not quiet:
        print(f"Fetching capture engine (nocta-recorder {_ENGINE_VERSION}, "
              f"{key[0]}/{key[1]}, one-time, ~50MB)...", file=sys.stderr)
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tgz = Path(td) / "engine.tgz"
        urllib.request.urlretrieve(url, tgz)
        _verify_sha512(tgz, sha512_b64)
        with tarfile.open(tgz) as tf:
            member = next(
                (m for m in tf.getmembers() if m.name.endswith("bin/nocta-recorder")),
                None,
            )
            # Regular files only: symlinks/hardlinks in an archive could
            # otherwise redirect the extract or the chmod below.
            if member is None or not member.isreg():
                raise CaptureError("Unexpected engine archive layout.")
            member.name = "nocta-recorder"
            try:
                tf.extract(member, BIN_DIR, filter="data")  # Python 3.12+
            except TypeError:
                tf.extract(member, BIN_DIR)
    local.chmod(0o755)
    if not quiet:
        print(f"Capture engine installed at {local}", file=sys.stderr)
    return str(local)


def _pid_is_engine(pid: int) -> bool:
    """Verify the PID actually belongs to the capture engine, so a stale
    pidfile after reboot/PID-reuse never points us at an innocent process."""
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        return True  # cannot verify: fail open for status, stop() re-checks
    return "nocta-recorder" in out or "capture-engine" in out


def _read_pid() -> int | None:
    try:
        pid = int(PID_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        PID_FILE.unlink(missing_ok=True)  # stale
        return None
    if not _pid_is_engine(pid):
        PID_FILE.unlink(missing_ok=True)  # PID reused by another process
        return None
    return pid


def _last_frame_age_s() -> float | None:
    """Seconds since the most recent captured frame, or None if unknown."""
    try:
        from ._time import parse_epoch
        from .db import Database

        db = Database()
        ts = db.scalar("SELECT MAX(timestamp) FROM frames", default=None)
        db.close()
        if not ts:
            return None
        import time

        return max(0.0, time.time() - parse_epoch(ts))
    except Exception:
        return None


def status() -> str:
    pid = _read_pid()
    if not pid:
        return "not recording"
    age = _last_frame_age_s()
    base = f"recording (pid {pid}, log: {LOG_FILE})"
    if age is None:
        return (base + "\nwarning: no capture database found yet. If this "
                "persists, grant Screen Recording and Accessibility permission "
                "(System Settings > Privacy & Security) and restart capture.")
    if age > 300:
        return (base + f"\nwarning: last captured frame is {int(age/60)} min old. "
                "The engine may lack Screen Recording / Accessibility permission "
                "(System Settings > Privacy & Security), or the screen is idle.")
    return base + f" - healthy, last frame {int(age)}s ago"


def start(*, audio: bool = False, foreground: bool = False) -> None:
    if _read_pid():
        print(f"Already {status()}", file=sys.stderr)
        return
    binary = ensure_engine()
    args = [binary, "record"]
    args += ["--audio-chunk-duration", "300"] if audio else ["--disable-audio"]

    HOME_DIR.mkdir(parents=True, exist_ok=True)
    if foreground:
        os.execv(binary, args)

    log = open(LOG_FILE, "ab")
    proc = subprocess.Popen(
        args, stdout=log, stderr=log,
        start_new_session=True,
    )
    PID_FILE.write_text(str(proc.pid))
    hint = ""
    if platform.system() == "Darwin":
        hint = ("\nmacOS: the engine needs Screen Recording and Accessibility "
                "permission (System Settings > Privacy & Security). Check with: "
                "aframes record --status")
    print(f"Capture started (pid {proc.pid}). Audio: {'on' if audio else 'off'}.\n"
          f"Data stays on this machine. Stop with: aframes record --stop{hint}",
          file=sys.stderr)


def stop() -> None:
    pid = _read_pid()
    if not pid:
        print("Not recording.", file=sys.stderr)
        return
    os.kill(pid, signal.SIGTERM)
    PID_FILE.unlink(missing_ok=True)
    print("Capture stopped.", file=sys.stderr)
