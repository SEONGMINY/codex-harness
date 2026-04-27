#!/usr/bin/env python3
"""Install codex-harness into a Codex project or user Codex home."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path


INSTALL_PATHS = [
    (Path(".agents") / "skills" / "codex-harness", Path(".agents") / "skills" / "codex-harness"),
    (Path("scripts") / "harness", Path("scripts") / "harness"),
]
PROJECT_HOOKS_SOURCE = Path(".codex") / "hooks"
PROJECT_HOOKS_TARGET = Path(".codex") / "hooks" / "codex-harness"
USER_SKILL_SOURCE = Path(".agents") / "skills" / "codex-harness"
USER_SKILL_TARGET = Path("skills") / "codex-harness"
USER_HOOKS_SOURCE = Path(".codex") / "hooks"
USER_HOOKS_TARGET = Path("hooks") / "codex-harness"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser().resolve()


def copy_tree(source: Path, target: Path, force: bool) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Missing source path: {source}")
    source = source.resolve()
    target = target.resolve()
    if source == target:
        return
    if target.exists():
        if not force:
            raise FileExistsError(f"Target already exists: {target}. Re-run with --force.")
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if source in target.parents:
        with tempfile.TemporaryDirectory(prefix="codex-harness-copy-") as tmp:
            staged = Path(tmp) / source.name
            shutil.copytree(source, staged)
            shutil.copytree(staged, target)
    else:
        shutil.copytree(source, target)


def copy_file(source: Path, target: Path, force: bool) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Missing source path: {source}")
    if source.resolve() == target.resolve():
        return
    if target.exists() and not force:
        raise FileExistsError(f"Target already exists: {target}. Re-run with --force.")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def copy_optional_file(source: Path, target: Path, force: bool) -> bool:
    if target.exists() and not force:
        return False
    copy_file(source, target, force)
    return True


def project_hook_command(script_name: str) -> str:
    return f'python3 "$(git rev-parse --show-toplevel)/.codex/hooks/codex-harness/{script_name}"'


def project_hook_groups(optional_hooks: bool) -> dict[str, list[dict[str, object]]]:
    groups: dict[str, list[dict[str, object]]] = {
        "PreToolUse": [
            {
                "matcher": "Bash|apply_patch|Edit|Write",
                "hooks": [
                    {
                        "type": "command",
                        "command": project_hook_command("harness_pre_tool_use.py"),
                        "timeout": 30,
                        "statusMessage": "Checking harness phase scope",
                    }
                ],
            }
        ],
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": project_hook_command("harness_stop.py"),
                        "timeout": 30,
                        "statusMessage": "Checking harness required outputs",
                    }
                ],
            }
        ],
    }
    if optional_hooks:
        groups["PostToolUse"] = [
            {
                "matcher": "Bash|apply_patch|Edit|Write",
                "hooks": [
                    {
                        "type": "command",
                        "command": project_hook_command("harness_post_tool_use.py"),
                        "timeout": 30,
                        "statusMessage": "Reviewing harness phase scope",
                    }
                ],
            }
        ]
        groups["UserPromptSubmit"] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": project_hook_command("harness_user_prompt_submit.py"),
                        "timeout": 30,
                        "statusMessage": "Adding harness context",
                    }
                ],
            }
        ]
    return groups


def install_project_hooks(source_root: Path, target_root: Path, force: bool, optional_hooks: bool) -> None:
    copy_tree(source_root / PROJECT_HOOKS_SOURCE, target_root / PROJECT_HOOKS_TARGET, force)
    merge_hooks_json(target_root / ".codex" / "hooks.json", project_hook_groups(optional_hooks))
    copied_optional = copy_optional_file(
        source_root / Path(".codex") / "hooks.optional.json",
        target_root / Path(".codex") / "hooks.optional.json",
        force,
    )
    print(f"installed {PROJECT_HOOKS_TARGET}")
    print("updated .codex/hooks.json")
    if copied_optional:
        print("installed .codex/hooks.optional.json")
    else:
        print("skipped existing .codex/hooks.optional.json")


def install_project(
    source_root: Path,
    target_root: Path,
    force: bool,
    with_hooks: bool,
    optional_hooks: bool,
) -> None:
    if not target_root.exists() or not target_root.is_dir():
        raise FileNotFoundError(f"Target directory does not exist: {target_root}")

    for source_rel, target_rel in INSTALL_PATHS:
        copy_tree(source_root / source_rel, target_root / target_rel, force)
        print(f"installed {target_rel}")

    for rel_path in [Path("docs"), Path("tasks")]:
        (target_root / rel_path).mkdir(parents=True, exist_ok=True)
        print(f"ensured {rel_path}")

    if with_hooks:
        install_project_hooks(source_root, target_root, force, optional_hooks)

    print(f"project install complete: {target_root}")


def install_user_skill(source_root: Path, user_home: Path, force: bool) -> None:
    target = user_home / USER_SKILL_TARGET
    copy_tree(source_root / USER_SKILL_SOURCE, target, force)
    assets_dir = target / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    copy_file(source_root / "scripts" / "bootstrap-install.py", assets_dir / "bootstrap-install.py", True)
    print(f"installed user skill {target}")


def hook_command(user_home: Path, script_name: str) -> str:
    return f'python3 "{user_home / USER_HOOKS_TARGET / script_name}"'


def user_hook_groups(user_home: Path, optional_hooks: bool) -> dict[str, list[dict[str, object]]]:
    groups: dict[str, list[dict[str, object]]] = {
        "PreToolUse": [
            {
                "matcher": "Bash|apply_patch|Edit|Write",
                "hooks": [
                    {
                        "type": "command",
                        "command": hook_command(user_home, "harness_pre_tool_use.py"),
                        "timeout": 30,
                        "statusMessage": "Checking harness phase scope",
                    }
                ],
            }
        ],
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": hook_command(user_home, "harness_stop.py"),
                        "timeout": 30,
                        "statusMessage": "Checking harness required outputs",
                    }
                ],
            }
        ],
    }
    if optional_hooks:
        groups["PostToolUse"] = [
            {
                "matcher": "Bash|apply_patch|Edit|Write",
                "hooks": [
                    {
                        "type": "command",
                        "command": hook_command(user_home, "harness_post_tool_use.py"),
                        "timeout": 30,
                        "statusMessage": "Reviewing harness phase scope",
                    }
                ],
            }
        ]
        groups["UserPromptSubmit"] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": hook_command(user_home, "harness_user_prompt_submit.py"),
                        "timeout": 30,
                        "statusMessage": "Adding harness context",
                    }
                ],
            }
        ]
    return groups


def group_commands(group: dict[str, object]) -> set[str]:
    hooks = group.get("hooks")
    if not isinstance(hooks, list):
        return set()
    commands = set()
    for hook in hooks:
        if not isinstance(hook, dict):
            continue
        command = hook.get("command")
        if isinstance(command, str):
            commands.add(command)
    return commands


def merge_hooks_json(path: Path, groups_by_event: dict[str, list[dict[str, object]]]) -> None:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Invalid hooks file: {path}")
    else:
        data = {}

    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"Invalid hooks section: {path}")

    for event, new_groups in groups_by_event.items():
        event_groups = hooks.setdefault(event, [])
        if not isinstance(event_groups, list):
            raise ValueError(f"Invalid hook event section: {event}")
        existing_commands = set()
        for group in event_groups:
            if isinstance(group, dict):
                existing_commands.update(group_commands(group))
        for group in new_groups:
            if group_commands(group).isdisjoint(existing_commands):
                event_groups.append(group)
                existing_commands.update(group_commands(group))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ensure_codex_hooks_feature(config_path: Path) -> None:
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    features_match = re.search(r"(?ms)^\[features\]\n(?P<body>.*?)(?=^\[|\Z)", text)
    if not features_match:
        separator = "\n\n" if text and not text.endswith("\n\n") else ""
        text = f"{text}{separator}[features]\ncodex_hooks = true\n"
    else:
        start, end = features_match.span("body")
        body = features_match.group("body")
        if re.search(r"(?m)^\s*codex_hooks\s*=", body):
            body = re.sub(r"(?m)^(\s*codex_hooks\s*=\s*).*$", r"\1true", body)
        else:
            body = f"codex_hooks = true\n{body}"
        text = f"{text[:start]}{body}{text[end:]}"

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(text, encoding="utf-8")


def install_user_hooks(source_root: Path, user_home: Path, force: bool, optional_hooks: bool) -> None:
    copy_tree(source_root / USER_HOOKS_SOURCE, user_home / USER_HOOKS_TARGET, force)
    merge_hooks_json(user_home / "hooks.json", user_hook_groups(user_home, optional_hooks))
    ensure_codex_hooks_feature(user_home / "config.toml")
    print(f"installed user hooks {user_home / USER_HOOKS_TARGET}")
    print(f"updated {user_home / 'hooks.json'}")
    print(f"enabled codex_hooks in {user_home / 'config.toml'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=".", help="Target Codex project or repository root.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Install user skill, user hooks, and project harness.",
    )
    parser.add_argument(
        "--scope",
        choices=["project", "user", "both"],
        default="project",
        help="Install into the current project, user Codex home, or both.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing harness files.")
    parser.add_argument(
        "--with-hooks",
        action="store_true",
        help="Install repo-local Codex hook config and hook scripts.",
    )
    parser.add_argument(
        "--user-hooks",
        action="store_true",
        help="Install user-level hooks into CODEX_HOME or ~/.codex.",
    )
    parser.add_argument(
        "--optional-hooks",
        action="store_true",
        help="Also install optional PostToolUse and UserPromptSubmit hooks.",
    )
    args = parser.parse_args()
    if args.all:
        args.scope = "both"
        args.user_hooks = True

    source_root = repo_root()
    target_root = Path(args.target).expanduser().resolve()
    user_home = codex_home()

    try:
        if args.scope in {"project", "both"}:
            install_project(source_root, target_root, args.force, args.with_hooks, args.optional_hooks)
        if args.scope in {"user", "both"}:
            install_user_skill(source_root, user_home, args.force)
            if args.user_hooks:
                install_user_hooks(source_root, user_home, args.force, args.optional_hooks)
            elif args.optional_hooks:
                raise ValueError("--optional-hooks requires --user-hooks when --scope is user-only")
    except (FileExistsError, FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
