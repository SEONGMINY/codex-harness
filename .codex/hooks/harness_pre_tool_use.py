#!/usr/bin/env python3
"""Block obvious phase-contract violations before supported tools run."""

from __future__ import annotations

from harness_common import (
    active_context,
    extract_bash_write_paths,
    extract_patch_paths,
    pre_tool_block,
    read_event,
    scope_violations,
    shell_command,
    tool_text,
)


def main() -> int:
    event = read_event()
    ctx = active_context(event)
    if ctx is None:
        return 0

    tool_name = str(event.get("tool_name") or "")
    text = tool_text(event)
    paths: list[str] = []

    if tool_name == "apply_patch" or "*** Begin Patch" in text:
        paths.extend(extract_patch_paths(text))
    elif tool_name == "Bash":
        paths.extend(extract_bash_write_paths(shell_command(event)))

    violations = scope_violations(ctx, paths)
    if not violations:
        return 0

    pre_tool_block(
        "Blocked by codex-harness PreToolUse hook. "
        "This phase may only edit Contract.scope.allowed_paths and required outputs. "
        "Rejected paths: "
        + ", ".join(violations)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
