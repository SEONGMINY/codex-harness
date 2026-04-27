#!/usr/bin/env python3
"""Optional context injection for direct codex-harness prompts."""

from __future__ import annotations

from harness_common import read_event, write_json


def main() -> int:
    event = read_event()
    prompt = str(event.get("prompt") or "")
    lowered = prompt.lower()
    if "$codex-harness" not in lowered and "codex-harness" not in lowered:
        return 0

    write_json(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": (
                    "codex-harness reminder: clarify first, ask approval before "
                    "creating docs, use scripts/harness/run-phases.py for Generate, "
                    "and judge completion from runner artifacts."
                ),
            }
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
