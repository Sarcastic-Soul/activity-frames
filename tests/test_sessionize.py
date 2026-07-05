from activity_frames.sessionize import app_ledger, coverage, segments


def test_segments_basic_shape(fixture_db, day_window):
    segs = segments(fixture_db, *day_window)
    keys = [(s.app, s.domain) for s in segs]
    # Slack flicker merged away: linkedin, cursor, github (after gap).
    assert ("Google Chrome", "linkedin.com") in keys
    assert ("Cursor", None) in keys
    assert ("Google Chrome", "github.com") in keys
    assert ("Slack", None) not in keys  # merged as interruption


def test_flicker_recorded_as_interruption(fixture_db, day_window):
    segs = segments(fixture_db, *day_window)
    li = next(s for s in segs if s.domain == "linkedin.com")
    assert len(li.interruptions) == 1
    assert li.interruptions[0].app == "Slack"
    assert li.interruptions[0].seconds <= 20


def test_session_gap_creates_new_segment_not_dwell(fixture_db, day_window):
    segs = segments(fixture_db, *day_window)
    gh = next(s for s in segs if s.domain == "github.com")
    # GitHub session is 15 frames over 14 min; active time must not
    # include the 60-minute away gap before it.
    assert 10 <= gh.active_seconds / 60 <= 15


def test_dwell_cap_limits_sparse_frames(fixture_db, day_window):
    segs = segments(fixture_db, *day_window)
    cur = next(s for s in segs if s.app == "Cursor")
    # 25 frames at 60s spacing, dwell 60s each (under the 90s cap).
    assert 20 <= cur.active_seconds / 60 <= 26


def test_coverage_gap_detected(fixture_db, day_window):
    cov = coverage(fixture_db, *day_window)
    assert cov.frame_count > 0
    assert any(55 <= g.minutes <= 65 for g in cov.gaps)
    assert cov.distinct_apps == 3  # Chrome, Slack, Cursor... Slack counts here
    assert cov.coverage_pct <= 100


def test_app_ledger_ordering_and_sessions(fixture_db, day_window):
    ledger = app_ledger(fixture_db, *day_window)
    assert ledger[0].app in ("Google Chrome", "Cursor")
    chrome = next(a for a in ledger if a.app == "Google Chrome")
    assert chrome.minutes > 10
    assert chrome.sessions >= 2  # linkedin block + github block


def test_empty_window(fixture_db):
    assert segments(fixture_db, "2020-01-01T00:00:00", "2020-01-02T00:00:00") == []
    cov = coverage(fixture_db, "2020-01-01T00:00:00", "2020-01-02T00:00:00")
    assert cov.frame_count == 0
