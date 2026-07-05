---
name: Site parser request
about: Ask for (or propose) typing support for a website
title: "Parser: <site>"
labels: parser
---

**Site**: <e.g. news.ycombinator.com>

**Example URLs and what they should become:**

| URL | kind | entity |
|-----|------|--------|
| https://news.ycombinator.com/item?id=123 | post | 123 |
| https://news.ycombinator.com/user?id=pg | profile | pg |

**Notes** (path structure, query params that matter, anything tricky):

Parsers are pure functions of the URL and take about 15 minutes to add - see
[CONTRIBUTING.md](../../CONTRIBUTING.md). PRs very welcome.
