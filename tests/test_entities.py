from activity_frames.entities import parse_url


def test_linkedin_profile():
    r = parse_url("https://www.linkedin.com/in/jane-doe/")
    assert (r.kind, r.entity, r.domain) == ("profile", "jane-doe", "linkedin.com")


def test_linkedin_search_with_keywords():
    r = parse_url(
        "https://www.linkedin.com/search/results/people/?keywords=cto%20berlin"
    )
    assert r.kind == "people_search"
    assert r.entity == "cto berlin"


def test_linkedin_company_and_feed():
    assert parse_url("https://www.linkedin.com/company/acme/").kind == "company"
    assert parse_url("https://www.linkedin.com/feed/").kind == "feed"


def test_github_pr_issue_repo():
    pr = parse_url("https://github.com/acme/api/pull/7")
    assert (pr.kind, pr.entity) == ("pull_request", "acme/api#7")
    issue = parse_url("https://github.com/acme/api/issues/12")
    assert (issue.kind, issue.entity) == ("issue", "acme/api#12")
    repo = parse_url("https://github.com/acme/api")
    assert (repo.kind, repo.entity) == ("repo", "acme/api")


def test_google_search():
    r = parse_url("https://www.google.com/search?q=swift+sqlite+wrapper")
    assert r.kind == "search"
    assert r.entity == "swift sqlite wrapper"


def test_youtube_video_and_search():
    v = parse_url("https://www.youtube.com/watch?v=abc123")
    assert (v.kind, v.entity) == ("video", "abc123")
    s = parse_url("https://www.youtube.com/results?search_query=mcp+tutorial")
    assert (s.kind, s.entity) == ("search", "mcp tutorial")


def test_x_profile_vs_system_paths():
    assert parse_url("https://x.com/someuser").kind == "profile"
    assert parse_url("https://x.com/notifications").kind == "notifications"
    assert parse_url("https://x.com/i/lists/123").kind == "page"
    assert parse_url("https://x.com/user/status/999").kind == "post"


def test_generic_fallback_and_search_param():
    r = parse_url("https://example.com/docs/getting-started")
    assert (r.kind, r.domain, r.entity) == ("page", "example.com", "docs")
    s = parse_url("https://anysite.io/find?q=hello%20world")
    assert (s.kind, s.entity) == ("search", "hello world")


def test_garbage_urls_never_raise():
    assert parse_url("").kind == "page"
    assert parse_url("not a url").kind == "page"
    assert parse_url("http://").kind == "page"


def test_entity_whitespace_normalized():
    r = parse_url(
        "https://www.linkedin.com/search/results/people/?keywords=jamie%20%20founder"
    )
    assert r.entity == "jamie founder"


def test_linkedin_extended_paths():
    assert parse_url("https://www.linkedin.com/mynetwork/grow/").kind == "network"
    assert parse_url("https://www.linkedin.com/notifications/").kind == "notifications"
    assert parse_url("https://www.linkedin.com/uas/login").kind == "sign_in"
    p = parse_url("https://www.linkedin.com/posts/acme-launches-beta-abc123")
    assert p.kind == "post"


def test_x_extended_paths():
    assert parse_url("https://x.com/i/chat/123-456").kind == "messages"
    assert parse_url("https://x.com/i/flow/login").kind == "sign_in"
    assert parse_url("https://x.com/settings/profile").kind == "page"


def test_instagram():
    assert parse_url("https://www.instagram.com/p/ABC123/").kind == "post"
    reel = parse_url("https://www.instagram.com/reel/XYZ789/")
    assert (reel.kind, reel.entity) == ("reel", "XYZ789")
    assert parse_url("https://www.instagram.com/stories/someone/").kind == "story"
    assert parse_url("https://www.instagram.com/explore/").kind == "explore"
    assert parse_url("https://www.instagram.com/direct/inbox/").kind == "messages"
    assert parse_url("https://www.instagram.com/janedoe/").kind == "profile"


def test_reddit():
    sub = parse_url("https://www.reddit.com/r/AskProgramming/")
    assert (sub.kind, sub.entity) == ("subreddit", "r/AskProgramming")
    post = parse_url("https://www.reddit.com/r/AskProgramming/comments/abc/some_title/")
    assert post.kind == "post"
    u = parse_url("https://www.reddit.com/user/some_user/")
    assert (u.kind, u.entity) == ("profile", "u/spez")


def test_google_maps_and_products():
    assert parse_url("https://www.google.com/maps/place/Central+Park").kind == "map_place"
    assert parse_url("https://www.google.com/maps/dir/a/b").kind == "map_directions"
    assert parse_url("https://meet.google.com/abc-defg-hij").kind == "meeting"
    assert parse_url("https://calendar.google.com/calendar/u/0/r").kind == "calendar"


def test_events_and_dashboards():
    assert parse_url("https://luma.com/abc123").kind == "event"
    assert parse_url("https://lu.ma/xyz").kind == "event"
    assert parse_url("https://partiful.com/e/abcDEF").kind == "event"
    pp = parse_url("https://www.producthunt.com/posts/some-cool-tool")
    assert (pp.kind, pp.entity) == ("product", "some cool tool")
    assert parse_url("https://vercel.com/team/project").kind == "project"
    sb = parse_url("https://supabase.com/dashboard/project/abcref")
    assert (sb.kind, sb.entity) == ("project", "abcref")
    assert parse_url("https://dashboard.stripe.com/payments").kind == "dashboard"


def test_discord_and_notion():
    ch = parse_url("https://discord.com/channels/123/456")
    assert (ch.kind, ch.entity) == ("channel", "123")
    assert parse_url("https://discord.com/channels/@me").kind == "messages"
    n = parse_url("https://app.notion.com/workspace/My-Project-Notes-abc123")
    assert n.kind == "doc"
    assert n.entity == "My Project Notes"


def test_heuristic_layer_types_unparsed_sites():
    # No bespoke parser for these hosts, but heuristics still type them.
    assert parse_url("https://accounts.google.com/signin/v2").kind == "sign_in"
    assert parse_url("https://app.attio.com/workspace/records").kind == "dashboard"
    assert parse_url("https://us.posthog.com/dashboard").kind == "dashboard"
    assert parse_url("https://mail.proton.me/u/0/inbox").kind == "email"
    assert parse_url("https://some-startup.com/login").kind == "sign_in"
    assert parse_url("https://zoom.us/j/123456").kind == "meeting"


def test_heuristic_does_not_override_real_parsers():
    # app.notion.com starts with "app." but must stay a notion doc, not a dashboard.
    assert parse_url("https://app.notion.com/ws/Page-abc").kind == "doc"
