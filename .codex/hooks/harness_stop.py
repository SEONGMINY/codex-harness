#!/usr/bin/env python3
"""Continue Codex when a phase tries to stop without required outputs."""

from __future__ import annotations

from harness_common import active_context, contract_required_outputs, read_event, write_json


def main() -> int:
    event = read_event()
    ctx = active_context(event)
    if ctx is None:
        return 0

    missing = [
        raw_path
        for raw_path in contract_required_outputs(ctx.contract)
        if not (ctx.task_path / raw_path).exists()
    ]
    if not missing:
        return 0

    message = (
        "codex-harness phase is missing required outputs: "
        + ", ".join(missing)
        + ". Create the missing files, then stop again. "
        "Do not edit runner-owned runtime proof files."
    )
    if event.get("stop_hook_active"):
        write_json({"systemMessage": message})
        return 0

    write_json({"decision": "block", "reason": message})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
