"""Draft a standup from a day of activity - without an LLM.

Demonstrates that a useful, structured artifact can come straight out of
the measured tier: no model, no guessing, fully reproducible. An agent
could of course phrase it more naturally; the point is that the facts
are already there.

    python examples/daily_standup.py [YYYY-MM-DD]
"""
import sys

from activity_frames import ActivityLog


def main() -> None:
    day = sys.argv[1] if len(sys.argv) > 1 else None
    log = ActivityLog()
    doc = log.day(day, min_minutes=3.0)

    projects: dict[str, float] = {}
    for f in doc.frames:
        key = f.site or f.app
        projects[key] = projects.get(key, 0.0) + f.duration_min

    top = sorted(projects.items(), key=lambda kv: -kv[1])[:6]
    cov = doc.to_dict()["coverage"]

    print(f"# Standup - {doc.to_dict()['window'].get('day', 'today')}\n")
    print(f"Active {cov['active_minutes']} min "
          f"({cov['first_activity']}-{cov['last_activity']}), "
          f"{cov['distinct_apps']} apps.\n")
    print("Where the time went:")
    for name, mins in top:
        print(f"  - {name}: {round(mins)} min")

    # Surface concrete entities touched (deterministic highlights).
    highlights = []
    for f in doc.frames:
        for p in f.pages:
            if p.entity and p.kind in {
                "pull_request", "issue", "repo", "doc", "profile", "company",
                "event", "product", "project",
            }:
                highlights.append(f"{p.kind}: {p.entity}")
    if highlights:
        seen, uniq = set(), []
        for h in highlights:
            if h not in seen:
                seen.add(h)
                uniq.append(h)
        print("\nTouched:")
        for h in uniq[:12]:
            print(f"  - {h}")


if __name__ == "__main__":
    main()
