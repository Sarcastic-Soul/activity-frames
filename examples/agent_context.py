"""Give an agent eyes on the last few hours.

The integration is one call: ActivityLog().context(hours=N) returns a
compact, deterministic block you can paste into any system prompt. This
script prints what the agent would receive, then shows the shape of a
call you would make to your LLM of choice.

    python examples/agent_context.py
"""
from activity_frames import ActivityLog


def main() -> None:
    log = ActivityLog()
    context = log.context(hours=4)

    print("=== context block the agent receives ===\n")
    print(context)
    print("\n=== how you would use it ===\n")

    system_prompt = (
        "You are the user's assistant. Here is what they have actually been "
        "doing on their computer, compiled deterministically from local screen "
        "capture (measured, not guessed):\n\n"
        f"{context}\n\n"
        "Ground every answer in this activity. If something is not shown, say so."
    )
    # Pseudocode - swap in your provider:
    #   response = client.messages.create(
    #       system=system_prompt,
    #       messages=[{"role": "user", "content": "What should I pick back up?"}],
    #   )
    print(f"(system prompt is {len(system_prompt)} chars, "
          f"~{len(system_prompt)//4} tokens - fits any context window)")


if __name__ == "__main__":
    main()
