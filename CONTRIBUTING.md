# Contributing

Thanks for helping build a shared, honest representation of computer activity for agents.

## The easiest, highest-value contribution: a site parser

44% of a real browser history is niche sites. Every site parser you add makes activity frames sharper for everyone. A parser is a pure function of the URL - no network, no state, reviewable in one sitting.

1. Open `src/activity_frames/entities.py`.
2. Add a function that takes `(domain, parts, q)` and returns a `PageRef` (or `None` to fall through). `parts` is the path split on `/`; `q` is the parsed query dict.
3. Register it in `_SITE_PARSERS` by host.
4. Add a test in `tests/test_entities.py`.

```python
def _hackernews(domain, parts, q):
    if parts and parts[0] == "item":
        return PageRef(kind="post", domain=domain, entity=q.get("id", [None])[0])
    if parts and parts[0] == "user":
        return PageRef(kind="profile", domain=domain, entity=q.get("id", [None])[0])
    return None

# in _SITE_PARSERS:
"news.ycombinator.com": _hackernews,
```

### Rules for parsers

- **Deterministic.** Output must be a pure function of the URL. No clocks, no randomness, no fetching.
- **Total.** Return `None` for paths you do not handle so the fallback layers can type them; never raise.
- **Honest kinds.** A `kind` describes what a page *is* (`profile`, `repo`, `event`), never what the user was *doing* there (`prospecting`, `researching`). Intent is the agent's job, not the parser's. See [SPEC.md](SPEC.md) section 7.
- **No content.** Parse the URL only. Do not pull identifiers from page bodies.

## Other contributions

- **Capture sources.** The compiler is engine-agnostic. A new source needs an adapter that presents `frames`, `ui_events`, and `elements` tables (see `db.py` and [SPEC.md](SPEC.md) section 9).
- **Bug fixes and robustness.** Edge cases in timezones, multi-monitor coordinates, and malformed capture data are always welcome.

## Development

```bash
git clone https://github.com/nossa-y/activity-frames
cd activity-frames
pip install -e ".[dev]"
pytest -q
```

Everything is standard-library Python (PyYAML is the only optional extra). Keep it that way where you can: zero required dependencies is a feature.

## Ground rules

- Determinism is the core promise. A change that makes output depend on wall-clock time, network, or a model will be declined.
- Keep the measured tier measured. New fields must be derivable by code; anything inferred belongs in the tier-2 extension with a confidence tag.
- Add a test with every behavior change.

By contributing you agree your work is licensed under the project's MIT license.
