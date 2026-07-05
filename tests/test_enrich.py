from activity_frames.enrich import decode_text, enrich_events, nearest_index


def test_layout_decode_azerty():
    # "hello zorld" recorded on AZERTY hardware decoded via the map:
    # z -> w, so "zorld" becomes "world"; plain letters pass through.
    assert decode_text("hello zorld", "azerty") == "hello world"
    assert decode_text("qm", "azerty") == "a,"  # a<->q swap, m -> ','


def test_layout_none_is_identity():
    assert decode_text("hello zorld", None) == "hello zorld"


def test_nearest_index():
    epochs = [10.0, 20.0, 30.0]
    assert nearest_index(epochs, 9.0) == 0
    assert nearest_index(epochs, 14.0) == 0
    assert nearest_index(epochs, 16.0) == 1
    assert nearest_index(epochs, 100.0) == 2
    assert nearest_index([], 5.0) is None


SCREEN = dict(screen_w=1728.0, screen_h=1117.0)  # fixture coords assume this


def test_enrich_attributes_app_from_frames(fixture_db, day_window):
    events = enrich_events(fixture_db, *day_window, **SCREEN)
    assert events, "should enrich fixture events"
    # Every event should be attributed to a frame.
    assert all(e.frame_id is not None for e in events)
    clicks = [e for e in events if e.event_type == "click"]
    assert all(e.app for e in clicks)


def test_click_resolution_from_elements(fixture_db, day_window):
    events = enrich_events(fixture_db, *day_window, **SCREEN)
    anon = [e for e in events if e.event_type == "click" and e.resolution != "native"]
    assert anon, "fixture has one anonymous click"
    resolved = anon[0]
    # The fixture element 'Message' covers the click point.
    assert resolved.label == "Message"
    assert resolved.resolution in ("exact", "tolerance")


def test_native_labels_kept_high_confidence(fixture_db, day_window):
    events = enrich_events(fixture_db, *day_window, **SCREEN)
    native = [e for e in events if e.resolution == "native"]
    assert native
    assert all(e.confidence == "high" for e in native)
    assert all(e.label == "Connect" for e in native)


def test_click_rescued_via_element_bearing_neighbor(fixture_db, day_window):
    """A click whose nearest frame has no element tree resolves against a
    neighboring frame (within the rescue window) that has one."""
    events = enrich_events(fixture_db, *day_window, **SCREEN)
    rescued = [
        e for e in events
        if e.event_type == "click" and e.label == "Follow"
    ]
    assert rescued, "click at 17:15:01 should resolve via the 17:15:03 frame"
    assert rescued[0].resolution in ("exact", "tolerance")


def test_rescue_respects_window(fixture_db, day_window):
    """With the rescue window shrunk below the 2s gap, the click stays
    unresolved instead of borrowing a too-distant frame."""
    events = enrich_events(fixture_db, *day_window, element_rescue_window=0.5, **SCREEN)
    at_15 = [
        e for e in events
        if e.event_type == "click" and abs(e.epoch % 3600 - 901) < 2  # 17:15:01
        and e.label == "Follow"
    ]
    assert not at_15


def test_text_excluded_by_default(fixture_db, day_window):
    events = enrich_events(fixture_db, *day_window, **SCREEN)
    assert all(e.text is None for e in events)
    with_text = enrich_events(fixture_db, *day_window, include_text=True, layout="azerty", **SCREEN)
    texts = [e.text for e in with_text if e.text]
    assert "hello world" in texts
