#!/usr/bin/env python3
"""Optional feedback after supported tools touch paths outside phase scope."""

from __future__ import annotations

from harness_common import (
    active_context,
    extract_bash_write_paths,
    extract_patch_paths,
    post_tool_block,
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

    post_tool_block(
        "codex-harness detected a phase-scope violation after the tool ran. "
        "Revert or repair these paths before continuing: "
        + ", ".join(violations)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
