"""Timestamp helpers.

The capture engine stores UTC ISO timestamps like
"2026-07-04T23:10:43.399302+00:00" in both `frames` and `ui_events`.
All window boundaries we pass to SQL are plain "YYYY-MM-DDTHH:MM:SS"
prefixes, which compare correctly against the stored strings.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def parse_epoch(ts: str) -> float:
    """Parse a recorder timestamp to epoch seconds. Returns 0.0 on garbage.

    Handles "2026-07-04T23:10:43", with optional fractional seconds and
    optional "+00:00"/"Z" suffix. Timestamps are always UTC.
    """
    if not ts or len(ts) < 19:
        return 0.0
    base = ts[:19]
    try:
        dt = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return 0.0
    epoch = dt.timestamp()
    if len(ts) > 20 and ts[19] == ".":
        frac = ""
        for ch in ts[20:]:
            if ch.isdigit():
                frac += ch
            else:
                break
        if frac:
            epoch += float("0." + frac)
    return epoch


def utc_string(dt: datetime) -> str:
    """Format a datetime as the recorder's comparable UTC prefix."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def now_utc_string() -> str:
    return utc_string(datetime.now(timezone.utc))


def local_day_string(dt: datetime | None = None) -> str:
    """Local calendar day "YYYY-MM-DD" for a datetime (default: now)."""
    d = dt if dt is not None else datetime.now()
    return d.astimezone().strftime("%Y-%m-%d")


def local_day_window_utc(day: str) -> tuple[str, str]:
    """UTC window [start, end) covering a local calendar day.

    Each boundary gets the local UTC offset in effect ON THAT DATE
    (naive .astimezone() applies the platform's timezone rules per
    date), so past days across a DST change and 23/25-hour transition
    days are handled correctly.

    Raises ValueError on a malformed day string.
    """
    start_naive = datetime.strptime(day, "%Y-%m-%d")
    start_local = start_naive.astimezone()
    end_local = (start_naive + timedelta(days=1)).astimezone()
    return utc_string(start_local), utc_string(end_local)


def hours_ago_window_utc(hours: float) -> tuple[str, str]:
    """UTC window [now - hours, now]."""
    now = datetime.now(timezone.utc)
    return utc_string(now - timedelta(hours=hours)), utc_string(now)


def fmt_local_hm(epoch: float) -> str:
    """Format an epoch as local "HH:MM"."""
    if epoch <= 0:
        return "?"
    return datetime.fromtimestamp(epoch).astimezone().strftime("%H:%M")


def fmt_local_hms(epoch: float) -> str:
    if epoch <= 0:
        return "?"
    return datetime.fromtimestamp(epoch).astimezone().strftime("%H:%M:%S")
