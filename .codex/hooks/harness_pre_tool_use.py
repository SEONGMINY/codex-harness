#!/usr/bin/env python3
"""Block obvious phase-contract violations before supported tools run."""

from __future__ import annotations

from harness_common import (
    active_context,
    bash_policy_violations,
    extract_tool_write_paths,
    pre_tool_block,
    read_event,
    shell_command,
    scope_violations,
)


def main() -> int:
    event = read_event()
    ctx = active_context(event)
    if ctx is None:
        return 0

    if event.get("tool_name") == "Bash":
        policy_violations = bash_policy_violations(shell_command(event))
        if policy_violations:
            pre_tool_block(
                "Blocked by codex-harness PreToolUse hook. "
                "This Bash command cannot be proven against Contract.scope.allowed_paths. "
                "Use apply_patch or a simple path-explicit command instead. "
                "Rejected command shape: "
                + "; ".join(sorted(set(policy_violations)))
            )
            return 0

    paths = extract_tool_write_paths(event)
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
