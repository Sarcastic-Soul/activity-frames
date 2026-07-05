"""Synthetic nocta-recorder-shaped fixture database for tests."""
from __future__ import annotations

import sqlite3

import pytest

from activity_frames.db import Database

BASE = "2026-07-04T"


def ts(hhmmss: str, frac: str = "000000") -> str:
    return f"{BASE}{hhmmss}.{frac}+00:00"


@pytest.fixture()
def fixture_db(tmp_path):
    """A small but realistic day of capture data (UTC timestamps).

    Timeline (UTC):
      17:00:00-17:10    Chrome / linkedin.com  (search + 2 profiles + company)
      17:10-17:11       Slack flicker (8s)     -> should merge as interruption
      17:11-17:20       Chrome / linkedin.com  (continued)
      17:20-17:45       Cursor (editor work, typing)
      18:45-19:00       Chrome / github.com    (after a 60min away gap)
    """
    path = tmp_path / "db.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE frames (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP NOT NULL,
            app_name TEXT, window_name TEXT, focused BOOLEAN,
            browser_url TEXT, document_path TEXT,
            device_name TEXT NOT NULL DEFAULT 'monitor_1'
        );
        CREATE TABLE ui_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL,
            event_type TEXT NOT NULL,
            x INTEGER, y INTEGER,
            text_content TEXT,
            app_name TEXT, window_title TEXT, browser_url TEXT,
            element_name TEXT, element_role TEXT
        );
        CREATE TABLE elements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            frame_id INTEGER NOT NULL,
            source TEXT NOT NULL DEFAULT 'accessibility',
            role TEXT NOT NULL DEFAULT 'AXButton',
            text TEXT,
            left_bound REAL, top_bound REAL, width_bound REAL, height_bound REAL
        );
        """
    )

    frames = []
    # LinkedIn session: a frame every ~20s, 17:00 to 17:10.
    urls = (
        [("https://www.linkedin.com/search/results/people/?keywords=cto%20berlin", "Search | LinkedIn")] * 6
        + [("https://www.linkedin.com/in/jane-doe/", "Jane Doe | LinkedIn")] * 12
        + [("https://www.linkedin.com/in/john-smith/", "John Smith | LinkedIn")] * 6
        + [("https://www.linkedin.com/company/acme/", "Acme | LinkedIn")] * 6
    )
    t = 0
    for url, win in urls:
        frames.append((f"17:{t//60:02d}:{t%60:02d}", "Google Chrome", win, url))
        t += 20
    # Slack flicker at 17:10:00 for 8 seconds (2 frames).
    frames.append(("17:10:00", "Slack", "general - Slack", None))
    frames.append(("17:10:08", "Slack", "general - Slack", None))
    # Back to LinkedIn 17:10:20 to 17:20, every 30s.
    t = 620
    while t < 1200:
        frames.append(
            (f"17:{t//60:02d}:{t%60:02d}", "Google Chrome",
             "Feed | LinkedIn", "https://www.linkedin.com/feed/")
        )
        t += 30
    # Cursor 17:20 to 17:45, every 60s.
    t = 1200
    while t < 2700:
        frames.append((f"17:{t//60:02d}:{t%60:02d}", "Cursor", "main.py - project", None))
        t += 60
    # Away gap 17:45 -> 18:45, then GitHub 18:45-19:00 every 60s.
    for m in range(45, 60):
        frames.append(
            (f"18:{m:02d}:00", "Google Chrome", "acme/api: PR #7",
             "https://github.com/acme/api/pull/7")
        )

    for hms, app, win, url in frames:
        conn.execute(
            "INSERT INTO frames (timestamp, app_name, window_name, focused, browser_url)"
            " VALUES (?,?,?,1,?)",
            (ts(hms), app, win, url),
        )

    # Input events: typing in Cursor (recorded on a mismatched layout),
    # clicks on LinkedIn, one anonymous click for resolution.
    events = [
        (ts("17:00:30"), "click", 100, 200, None, "Google Chrome", "Connect", "AXButton"),
        (ts("17:02:00"), "click", 100, 200, None, "Google Chrome", "Connect", "AXButton"),
        (ts("17:04:00"), "click", 100, 200, None, "Google Chrome", "Connect", "AXButton"),
        (ts("17:25:00"), "text", None, None, "hello zorld", "Cursor", None, None),
        (ts("17:26:00"), "key", None, None, None, "Cursor", None, None),
        (ts("17:27:00"), "key", None, None, None, "Cursor", None, None),
        (ts("17:28:00"), "clipboard", None, None, "copied", "Cursor", None, None),
        # anonymous click at normalized (0.5, 0.5) of a 1728x1117 screen
        (ts("17:05:00"), "click", 864, 558, None, "Google Chrome", None, None),
    ]
    for tstamp, etype, x, y, text, app, elem, role in events:
        conn.execute(
            "INSERT INTO ui_events (timestamp, event_type, x, y, text_content,"
            " app_name, element_name, element_role) VALUES (?,?,?,?,?,?,?,?)",
            (tstamp, etype, x, y, text, app, elem, role),
        )

    # An element covering the center of the screen on the frame nearest 17:05.
    row = conn.execute(
        "SELECT id FROM frames WHERE timestamp <= ? ORDER BY timestamp DESC LIMIT 1",
        (ts("17:05:00"),),
    ).fetchone()
    conn.execute(
        "INSERT INTO elements (frame_id, text, left_bound, top_bound, width_bound,"
        " height_bound) VALUES (?, 'Message', 0.45, 0.45, 0.1, 0.1)",
        (row[0],),
    )

    # Rescue scenario: click at 17:15:01 whose NEAREST frame (17:15:00) has no
    # elements, while a frame 2s later (17:15:03) does. The resolver should
    # rescue via the element-bearing neighbor.
    conn.execute(
        "INSERT INTO frames (timestamp, app_name, window_name, focused, browser_url)"
        " VALUES (?, 'Google Chrome', 'Feed | LinkedIn', 1,"
        " 'https://www.linkedin.com/feed/')",
        (ts("17:15:00"),),
    )
    cur = conn.execute(
        "INSERT INTO frames (timestamp, app_name, window_name, focused, browser_url)"
        " VALUES (?, 'Google Chrome', 'Feed | LinkedIn', 1,"
        " 'https://www.linkedin.com/feed/')",
        (ts("17:15:03"),),
    )
    conn.execute(
        "INSERT INTO elements (frame_id, text, left_bound, top_bound, width_bound,"
        " height_bound) VALUES (?, 'Follow', 0.45, 0.45, 0.1, 0.1)",
        (cur.lastrowid,),
    )
    conn.execute(
        "INSERT INTO ui_events (timestamp, event_type, x, y, app_name)"
        " VALUES (?, 'click', 864, 558, 'Google Chrome')",
        (ts("17:15:01"),),
    )

    conn.commit()
    conn.close()
    return Database(str(path))


@pytest.fixture()
def day_window():
    """UTC window covering all fixture data regardless of local tz."""
    return "2026-07-04T00:00:00", "2026-07-05T00:00:00"
