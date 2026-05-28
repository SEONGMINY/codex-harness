#!/usr/bin/env python3
"""Optional feedback after supported tools touch paths outside phase scope."""

from __future__ import annotations

from harness_common import (
    active_context,
    extract_tool_write_paths,
    post_tool_block,
    read_event,
    scope_violations,
)


def main() -> int:
    event = read_event()
    ctx = active_context(event)
    if ctx is None:
        return 0

    paths = extract_tool_write_paths(event)
    violations = scope_violations(ctx, paths)
    if not violations:
        return 0

    post_tool_block(
        "codex-harness detected a phase-scope violation after the tool ran. "
        "Revert or repair these paths before continuing: "
        + ", ".join(violations)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
