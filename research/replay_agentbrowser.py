"""Parametric routine replay executor.

PARAMETRIC ROUTINE REPLAY: re-run the STRUCTURE of a routine the user has done before
(open composer -> click recipient -> type message -> send), filling its variable SLOTS
with new values from the current request (recipient Alice->Bob, message text -> new text).
We never replay the identical past action; we reuse the "way" and drop in new parameters.
"Deterministic" here refers to how each step is GROUNDED - by accessibility role+name at
~0 LLM tokens, reproducibly - not to the content, which is always new.

A STANDALONE agent-browser executor (daemon reuse, real Chrome profile, human
pacing, safety guards) with the one novel piece on top: deterministic role+name
grounding of a compiled plan, so replay costs ~0 LLM tokens.

The split: this file is the compiled fast-path (grounding ladder tier 1 role+name / tier 2
OCR fingerprint, 0 tokens); on a miss with --deopt it hands off to a local LLM step that
reasons about the live page. Daemon management + pacing follow the rules that keep a
real-profile browser stable: launch bound --profile ... --headed ONCE and REUSE the
daemon; never cycle close/open into the headless fallback.

STATUS: parser verified on a real live snapshot (100%). A first owner-authorized live
run has completed: a compiled two-step routine, retrieved from a natural-language
request, executed in a real authenticated browser at zero model tokens.

  python3 replay_agentbrowser.py plan.json                 # SAFE default: dry-run, never clicks
  python3 replay_agentbrowser.py plan.json --execute       # opt in to real browser actions
      [--profile "Profile 3"] [--allow-destructive] [--deopt]
  python3 replay_agentbrowser.py --selftest      # offline: validate parse+locate+guard, no browser

plan.json = [{"op":"click|type","target":"Compose message","role":"button",
              "ocr_text":"Compose","value":"hi","guard":{"expect_element":"Compose message"}}, ...]
"""
from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlparse

LLAMA_URL = os.environ.get("LLAMA_URL", "http://localhost:8081") + "/v1/chat/completions"

# Fire only when a destructive verb is the IMPERATIVE HEAD of a control's accessible name
# (a short action button: "Post", "Send", "Send invitation", "Connect") - NOT when the verb
# merely appears inside a safe phrase ("Start a post", "Text editor for creating content").
# Anchored-at-start avoids the false positive that would otherwise block the composer opener.
# KNOWN EDGE (ISSUES): a confirm control phrased "Yes, delete" (verb not at head) slips past;
# acceptable because plans come from recorded non-destructive routines + discard is done out-of-band.
_DESTRUCTIVE_VERBS = ("send", "post", "publish", "share", "connect", "delete", "remove",
                      "pay", "buy", "submit", "confirm", "transfer", "archive", "discard",
                      "checkout", "purchase", "withdraw", "tweet", "invite", "follow", "apply")
DESTRUCTIVE = re.compile(r"^(?:" + "|".join(_DESTRUCTIVE_VERBS) + r")\b", re.I)


def is_destructive(*names):
    """True if any name's imperative head is a destructive verb (see DESTRUCTIVE)."""
    return any(DESTRUCTIVE.match(norm(n)) for n in names if n)

_ROLE_ALIASES = {"axbutton": "button", "axtextfield": "textbox", "axstatictext": "text",
                 "axlink": "link", "textbox": "textbox", "button": "button", "link": "link"}


def norm(s):
    return re.sub(r"\s+", " ", (s or "").replace("‎", "")).strip().lower()


def role_match(a, b):
    if not b:
        return True
    a, b = norm(a), norm(b)
    return a == b or _ROLE_ALIASES.get(a, a) == _ROLE_ALIASES.get(b, b)


def parse_snapshot(text):
    """agent-browser snapshot lines look like: `- button "Compose message" [ref=e36]`
    or `- textbox [ref=e40]`. Extract (role, name, ref) for every element with a ref."""
    items = []
    for line in text.splitlines():
        rm = re.search(r'\bref=(e\d+)\b', line)     # ref can sit anywhere in the bracket
        if not rm:
            continue
        role_m = re.search(r'-\s+([A-Za-z][\w-]*)', line)
        name_m = re.search(r'"([^"]*)"', line)      # first quoted string = accessible name
        items.append({"role": role_m.group(1) if role_m else "",
                      "name": name_m.group(1) if name_m else "",
                      "ref": rm.group(1)})
    return items


def locate(items, target, role="", ocr_text=""):
    """Grounding ladder. Returns (item, tier) or (None, 0)."""
    t = norm(target)
    # tier 1: accessibility (role+name), then name-exact, then name-contains
    if t:
        for it in items:
            if norm(it["name"]) == t and role_match(it["role"], role):
                return it, 1
        for it in items:
            if norm(it["name"]) == t:
                return it, 1
        cand = [it for it in items if t in norm(it["name"])]
        if cand:
            return min(cand, key=lambda it: len(it["name"])), 1
    # tier 2: the recorded OCR/visible-text fingerprint
    o = norm(ocr_text)
    if o:
        for it in items:
            if norm(it["name"]) == o or (o and o in norm(it["name"])):
                return it, 2
    return None, 0


# ---- agent-browser driver (reproduces nocta-execute's operational lessons) ---
def ab(*args, timeout=30):
    return subprocess.run(["agent-browser", *args], capture_output=True, text=True, timeout=timeout)


def snapshot():
    return ab("snapshot", timeout=45).stdout


def pace(lo=1.0, hi=3.0):
    """Human pacing between actions (anti-bot). Real jittered sleep - this is a
    standalone script the operator runs, so time.sleep is fine here."""
    time.sleep(random.uniform(lo, hi))


# SPA hydration: `open` returns when navigation commits, long before content
# exists. Grounding against the skeleton is a guaranteed false miss (the
# recorded corpus even contains a "Loading" AXGroup the user clicked). So after
# a navigate we poll until the page looks real, and a missed click re-snapshots
# before declaring failure.
_SKELETON_NAMES = frozenset({"loading", "loading…", "loading..."})
HYDRATE_TIMEOUT_S = float(os.environ.get("NOCTA_HYDRATE_TIMEOUT", "12"))


def _looks_hydrated(items):
    named = sum(1 for it in items if it["name"])
    skeleton = any((it["name"] or "").strip().lower() in _SKELETON_NAMES
                   for it in items)
    return named >= 12 and not skeleton


def wait_hydrated(target="", role="", ocr="", timeout_s=None, poll_s=1.2):
    """Poll the snapshot until the lookahead target grounds or the page looks
    hydrated; return the last parsed snapshot either way (bounded, no model)."""
    deadline = time.monotonic() + (HYDRATE_TIMEOUT_S if timeout_s is None else timeout_s)
    snap = parse_snapshot(snapshot())
    while time.monotonic() < deadline:
        if target and locate(snap, target, role, ocr)[0]:
            return snap
        if not target and _looks_hydrated(snap):
            return snap
        time.sleep(poll_s)
        snap = parse_snapshot(snapshot())
    return snap


def ensure_daemon(profile="Profile 3", url="about:blank"):
    """Reproduce the daemon-reuse gotcha (docs/lessons/browser.md): a headed real-Chrome
    daemon must be launched ONCE bound with --profile ... --headed and then REUSED; if it
    died and you `open` again it silently respawns a HEADLESS throwaway. So: if a headed
    real-Chrome agent-browser is already up, reuse it; else launch bound. Verify it is NOT
    the headless fallback before trusting any snapshot. Never pkill blindly (another agent
    may be driving Chrome)."""
    pid = subprocess.run(["pgrep", "-f", "agent-browser-profile|Google Chrome.*remote-debugging"],
                         capture_output=True, text=True).stdout.split()
    if pid:
        cmd = subprocess.run(["ps", "-p", pid[0], "-o", "command="],
                             capture_output=True, text=True).stdout
        if "--headless" not in cmd and "chrome-headless-shell" not in cmd and "playwright" not in cmd:
            return "reused-headed"
        return "WARNING-headless-fallback-detected (relaunch bound manually to avoid clobbering another agent's Chrome)"
    ab("--profile", profile, "--headed", "--args", "--disable-blink-features=AutomationControlled",
       "open", url, timeout=60)
    up = subprocess.run(["pgrep", "-f", "agent-browser-profile"], capture_output=True, text=True).stdout.split()
    if up:
        cmd = subprocess.run(["ps", "-p", up[0], "-o", "command="], capture_output=True, text=True).stdout
        return "launched-headed" if "--headless" not in cmd else "FAILED-launched-headless"
    return "FAILED-no-daemon"


def deopt_resolve(items, target, role):
    """DEOPT: tier 1/2 missed. Hand the current snapshot + the step goal to a LOCAL
    LLM (nocta-execute-style step) to pick the best ref, then resume the deterministic
    plan. Returns a ref or None. Local-first: refuses non-localhost."""
    if (urlparse(LLAMA_URL).hostname or "").lower() not in ("localhost", "127.0.0.1", "::1", "[::1]"):
        return None
    cat = "\n".join(f'[{it["ref"]}] {it["role"]} "{it["name"]}"' for it in items if it["name"])[:4000]
    prompt = (f'Goal: click/type the {role or "element"} for "{target}".\nElements on screen:\n{cat}\n'
              f'Reply with ONLY the single best matching ref id (like e12), or NONE.')
    body = json.dumps({"messages": [{"role": "user", "content": prompt}],
                       "temperature": 0, "max_tokens": 400}).encode()
    try:
        req = urllib.request.Request(LLAMA_URL, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=90) as r:
            content = json.load(r)["choices"][0]["message"].get("content") or ""
        m = re.findall(r"e\d+", content)
        return m[-1] if m else None      # the answer ref (after any reasoning)
    except Exception:
        return None


def run_plan(plan, dry_run=False, allow_destructive=False, deopt=False, nav_dry=False):
    """Execute (or rehearse) a plan.

    Modes:
      dry_run=True             fully static: ground every step against the
                               CURRENT page. Structurally pessimistic for
                               multi-page plans (later pages' steps cannot
                               ground yet) - use nav_dry for those.
      nav_dry=True             rehearsal: navigate ops EXECUTE (read-only page
                               loads), click/type ops are grounded per page but
                               never acted. The honest pre-flight for a
                               multi-page plan.
      both False (--execute)   live run.
    """
    steps_out = []
    acting = not dry_run and not nav_dry
    # hard wall-clock cap so a wedged browser can never hang a live demo: past
    # the deadline, remaining steps are recorded aborted and the run returns.
    deadline = time.monotonic() + float(os.environ.get("NOCTA_REPLAY_DEADLINE", "240"))
    aborted = False
    for i, step in enumerate(plan):
        op = step.get("op")
        if (acting or nav_dry) and time.monotonic() > deadline:
            steps_out.append({"i": i, "op": op, "target": step.get("target") or "",
                              "tier": 0, "ref": None, "acted": False, "deopt": False,
                              "deopt_recovered": False, "blocked": False,
                              "aborted": "deadline"})
            aborted = True
            continue
        if i and (acting or (nav_dry and op == "navigate")):
            pace(1.5, 3.0)          # let the previous action's DOM settle + human pacing
        target = step.get("target") or (step.get("guard") or {}).get("expect_element") or ""
        role = step.get("role") or (step.get("guard") or {}).get("expect_role") or ""

        # navigate: no element to ground - the URL is the instruction. Executes
        # in live AND nav-dry modes (page loads are read-only rehearsal).
        if op == "navigate":
            rec = {"i": i, "op": "navigate", "target": target, "tier": 0,
                   "ref": None, "acted": False, "deopt": False,
                   "deopt_recovered": False, "blocked": False}
            if (acting or nav_dry) and target:
                ab("open", target, timeout=45)
                pace(1.0, 2.0)
                # settle until the NEXT actionable step grounds (or the page
                # looks hydrated) - SPAs render seconds after `open` returns
                look = next((s for s in plan[i + 1:] if s.get("op") != "navigate"), None)
                snap = wait_hydrated(
                    (look or {}).get("target") or "",
                    (look or {}).get("role") or "",
                    (look or {}).get("ocr_text") or "")
                rec["acted"] = True
                rec["page_elements"] = sum(1 for it in snap if it["name"])
                if rec["page_elements"] < 5:
                    rec["warning"] = "page barely hydrated (auth wall / wrong profile / slow load?)"
            steps_out.append(rec)
            continue

        snap = parse_snapshot(snapshot())
        it, tier = locate(snap, target, role, step.get("ocr_text", ""))
        if not it and (acting or nav_dry):
            # miss on a live page: re-snapshot before giving up (late render)
            for backoff in (1.5, 3.0):
                time.sleep(backoff)
                snap = parse_snapshot(snapshot())
                it, tier = locate(snap, target, role, step.get("ocr_text", ""))
                if it:
                    break
        if not it and deopt:                 # tier 1/2 missed -> LLM deopt step
            dref = deopt_resolve(snap, target, role)
            if dref:
                it, tier = {"ref": dref, "name": target, "role": role}, -1  # -1 = deopt-recovered
        rec = {"i": i, "op": step.get("op"), "target": target, "tier": tier,
               "ref": it["ref"] if it else None, "acted": False,
               "deopt": False, "deopt_recovered": tier == -1, "blocked": False}
        if not it:
            # a click whose recorded effect is the very next navigate is
            # SUBSUMED: replaying the navigate reproduces the transition, so a
            # miss here is a skip, not a failure (converter marks these "soft")
            if step.get("soft"):
                rec["skipped_soft"] = True
                steps_out.append(rec)
                continue
            rec["deopt"] = True  # unresolved even after deopt
            if os.environ.get("NOCTA_REPLAY_DEBUG"):
                rec["page_sample"] = [f'{it2["role"]}:{it2["name"][:40]}'
                                      for it2 in snap if it2["name"]][:20]
            steps_out.append(rec)
            continue
        nm = it["name"] or target
        # is_destructive() normalizes first (strips ‎ bidi marks / whitespace, lowercases)
        # then matches the imperative head - a raw DESTRUCTIVE.search() is defeated by a leading
        # ‎ (which the corpus is full of), so it must go through the normalized helper.
        if is_destructive(nm, target) and not allow_destructive:
            rec["blocked"] = True
            rec["reason"] = f"destructive verb blocked: {nm}"
            steps_out.append(rec)
            continue
        if acting:
            if step.get("op") == "type":
                ab("click", it["ref"]); pace(1, 2)
                ab("type", it["ref"], step.get("value", ""))
            else:
                ab("click", it["ref"])
            rec["acted"] = True
        steps_out.append(rec)
    summary = {
        "total": len(steps_out),
        "tier1": sum(s["tier"] == 1 for s in steps_out),
        "tier2": sum(s["tier"] == 2 for s in steps_out),
        "deopt_recovered": sum(bool(s.get("deopt_recovered")) for s in steps_out),
        "deopt_unresolved": sum(s["deopt"] for s in steps_out),
        "skipped_soft": sum(bool(s.get("skipped_soft")) for s in steps_out),
        "blocked": sum(s["blocked"] for s in steps_out),
        "acted": sum(s["acted"] for s in steps_out),
        "aborted": sum(1 for s in steps_out if s.get("aborted")),
    }
    mode = "executed" if acting else ("nav_dry" if nav_dry else "dry_run")
    if aborted:
        mode += "+deadline-abort"
    return {"mode": mode, "summary": summary, "steps": steps_out}


# ---- offline self-test (no browser) -----------------------------------------
SAMPLE_SNAPSHOT = """
- generic [ref=e1]
  - button "Compose message" [ref=e12]
  - textbox "Write a message" [ref=e14]
  - link "Drafts" [ref=e16]
  - button "Save draft now" [ref=e18]
  - button "Send" [ref=e20]
"""
SELFTEST_PLAN = [
    {"op": "click", "target": "Compose message", "role": "button"},   # tier1 (name exact)
    {"op": "type", "target": "Write a message", "role": "textbox", "value": "hi"},  # tier1
    {"op": "click", "target": "Keep draft", "role": "button", "ocr_text": "Save draft now"},  # tier2: name absent, OCR matches
    {"op": "click", "target": "Attach file", "role": "button"},        # deopt (absent)
    {"op": "click", "target": "Send", "role": "button"},               # blocked (destructive)
]


def selftest():
    items = parse_snapshot(SAMPLE_SNAPSHOT)
    assert len(items) == 6, f"parsed {len(items)} refs, expected 6"
    outs = []
    for step in SELFTEST_PLAN:
        it, tier = locate(items, step["target"], step.get("role", ""), step.get("ocr_text", ""))
        nm = it["name"] if it else ""
        blocked = bool(it) and is_destructive(nm or step["target"])
        outs.append((step["target"], tier, it["ref"] if it else None, "BLOCKED" if blocked else ""))
    exp = [("Compose message", 1, "e12"), ("Write a message", 1, "e14"),
           ("Keep draft", 2, "e18"), ("Attach file", 0, None), ("Send", 1, "e20")]
    ok = True
    for (tg, tier, ref, note), (etg, etier, eref) in zip(outs, exp):
        good = tier == etier and ref == eref
        ok = ok and good and (note == "BLOCKED" if tg == "Send" else True)
        print(f"  {'PASS' if good else 'FAIL'}  {tg}: tier{tier} ref={ref} {note}")
    # guard must survive obfuscation the corpus actually contains (leading ‎ bidi mark, spaces)
    bypass = [is_destructive("‎Send"), is_destructive("  send"), is_destructive("POST"),
              is_destructive("Send invitation")]
    safe = [not is_destructive("Start a post"), not is_destructive("Compose message"),
            not is_destructive("Search")]
    gok = all(bypass) and all(safe)
    ok = ok and gok
    print(f"  {'PASS' if gok else 'FAIL'}  destructive-guard: blocks ‎/space/case-obfuscated verbs, allows safe names")

    # nav-dry hydration/retry/soft simulation: skeleton snapshots first, real
    # page later - the plan must still ground (no browser: everything patched)
    hok = _selftest_navdry()
    ok = ok and hok
    print(f"  {'PASS' if hok else 'FAIL'}  nav-dry: waits through skeleton, retries misses, skips soft steps")
    print("SELFTEST", "PASS" if ok else "FAIL", "- grounding ladder + normalized safety guard + nav-dry hydration")
    sys.exit(0 if ok else 1)


def _selftest_navdry():
    global snapshot, ab, pace, HYDRATE_TIMEOUT_S
    skeleton = '- generic [ref=e1]\n  - group "Loading" [ref=e2]\n'
    hydrated = "- generic [ref=e1]\n" + "".join(
        f'  - button "Filler {n}" [ref=e{n + 10}]\n' for n in range(14)
    ) + '  - link "View all transactions for this purchase" [ref=e99]\n'
    seq = [skeleton, skeleton, hydrated]
    opens = []
    orig = (snapshot, ab, pace, time.sleep, HYDRATE_TIMEOUT_S)
    snapshot = lambda: seq.pop(0) if seq else hydrated          # noqa: E731
    ab = lambda *a, **k: (opens.append(a) if a and a[0] == "open" else None,  # noqa: E731
                          subprocess.CompletedProcess(a, 0, "", ""))[1]
    pace = lambda *a, **k: None                                  # noqa: E731
    time.sleep = lambda *_: None
    HYDRATE_TIMEOUT_S = 0.2
    try:
        out = run_plan(
            [
                {"op": "navigate", "target": "https://example.com/billing"},
                {"op": "click", "target": "Row that navigated", "role": "AXCell",
                 "soft": True},                       # absent -> skipped, not failed
                {"op": "click", "target": "View all transactions for this purchase",
                 "role": "AXLink"},                   # grounds after hydration wait
            ],
            nav_dry=True,
        )
        s = out["summary"]
        return (out["mode"] == "nav_dry" and opens
                and s["acted"] == 1 and s["tier1"] == 1
                and s["skipped_soft"] == 1 and s["deopt_unresolved"] == 0)
    finally:
        snapshot, ab, pace, time.sleep, HYDRATE_TIMEOUT_S = orig


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    plan = json.load(open(sys.argv[1]))
    live = "--execute" in sys.argv
    nav = "--nav-dry" in sys.argv
    profile = "Profile 3"
    if "--profile" in sys.argv:
        profile = sys.argv[sys.argv.index("--profile") + 1]
    if live or nav:
        # bind-or-reuse BEFORE the first open: an `open` with no daemon silently
        # spawns a headless throwaway and every snapshot lies (see ensure_daemon)
        state = ensure_daemon(profile)
        print(f"# daemon: {state}", file=sys.stderr)
    # SAFE BY DEFAULT: dry-run unless --execute is passed. This tool drives a REAL browser,
    # so live clicks must be opted into explicitly (a bare run never acts).
    print(json.dumps(run_plan(plan, dry_run=not live and not nav,
                              nav_dry=nav,
                              allow_destructive="--allow-destructive" in sys.argv,
                              deopt="--deopt" in sys.argv), indent=2))
