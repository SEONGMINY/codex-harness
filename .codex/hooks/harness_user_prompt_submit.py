#!/usr/bin/env python3
"""Optional context injection for direct codex-harness prompts."""

from __future__ import annotations

import json
import re
from pathlib import Path

from harness_common import read_event, repo_root, write_json


def skill_version(skill_path: Path) -> str | None:
    try:
        text = skill_path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"(?m)^version:\s*['\"]?([^'\"\n]+)", text)
    return match.group(1).strip() if match else None


def expected_harness_version(root: Path) -> str | None:
    config_path = root / "codex-harness.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        config = None
    if isinstance(config, dict) and isinstance(config.get("version"), str) and config["version"].strip():
        return config["version"].strip()
    runtime_skill = root / ".codex" / "harness" / "scripts" / "skill" / "SKILL.md"
    return skill_version(runtime_skill)


def local_skill_warning(event: dict) -> str:
    cwd = Path(str(event.get("cwd") or ".")).resolve()
    root = repo_root(cwd)
    skill_path = root / ".agents" / "skills" / "codex-harness" / "SKILL.md"
    if not skill_path.exists():
        return ""
    expected_version = expected_harness_version(root)
    if expected_version is None:
        return ""
    version = skill_version(skill_path) or "(missing)"
    if version == expected_version:
        return ""
    return (
        " Project-local .agents/skills/codex-harness is stale and can shadow "
        "the global skill. Run the installer before continuing."
    )


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
                    + local_skill_warning(event)
                ),
            }
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
