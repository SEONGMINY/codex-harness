"""Shared helpers for codex-harness hooks."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PATCH_PATH_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.MULTILINE)
PATCH_MOVE_RE = re.compile(r"^\*\*\* Move to: (.+)$", re.MULTILINE)
REDIRECT_RE = re.compile(r"(?:^|\s)(?:>|>>)\s*([^\s;&|]+)")
SHELL_COMMAND_SEPARATORS = {"&&", "||", ";", "|"}
REDIRECT_TOKENS = {">", ">>", "1>", "1>>", "2>", "2>>", "&>", "&>>", "<", "<<", "<<<"}
RUNNER_OWNED_PATTERNS = [
    re.compile(r"^tasks/index\.json$"),
    re.compile(r"^tasks/[^/]+/index\.json$"),
    re.compile(r"^tasks/[^/]+/context-pack/runtime/docs-diff\.md$"),
    re.compile(
        r"^tasks/[^/]+/context-pack/runtime/evaluation-"
        r"(?:command-results|prompt|output)\.(?:json|md|jsonl)$"
    ),
    re.compile(
        r"^tasks/[^/]+/context-pack/runtime/phase\d+-"
        r"(?:prompt|contract|checklist|output-attempt\d+|stderr-attempt\d+|"
        r"ac-attempt\d+|evidence|reconciliation|gate|result|last-error|repair-packet)"
        r"\.(?:md|json|jsonl|txt)$"
    ),
]


@dataclass(frozen=True)
class HarnessContext:
    root: Path
    task_path: Path
    phase: int
    contract_path: Path
    contract: dict[str, Any]


def read_event() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_json(data: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")


def repo_root(cwd: Path) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return cwd.resolve()


def active_context(event: dict[str, Any]) -> HarnessContext | None:
    if os.environ.get("CODEX_HARNESS_ACTIVE") != "1":
        return None

    cwd = Path(str(event.get("cwd") or os.getcwd())).resolve()
    root = Path(os.environ.get("CODEX_HARNESS_ROOT") or repo_root(cwd)).resolve()
    task_rel = os.environ.get("CODEX_HARNESS_TASK_PATH")
    task_name = os.environ.get("CODEX_HARNESS_TASK")
    phase_raw = os.environ.get("CODEX_HARNESS_PHASE")
    contract_rel = os.environ.get("CODEX_HARNESS_CONTRACT_PATH")

    if not phase_raw or not contract_rel:
        return None
    try:
        phase = int(phase_raw)
    except ValueError:
        return None

    if task_rel:
        task_path = (root / task_rel).resolve()
    elif task_name:
        task_path = (root / "tasks" / task_name).resolve()
    else:
        return None

    contract_path = (root / contract_rel).resolve()
    if not contract_path.exists():
        return None
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(contract, dict):
        return None
    return HarnessContext(root, task_path, phase, contract_path, contract)


def flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(flatten_strings(item))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(flatten_strings(item))
        return result
    return []


def tool_text(event: dict[str, Any]) -> str:
    return "\n".join(flatten_strings(event.get("tool_input")))


def shell_command(event: dict[str, Any]) -> str:
    tool_input = event.get("tool_input")
    if isinstance(tool_input, dict):
        command = tool_input.get("command") or tool_input.get("cmd")
        if isinstance(command, str):
            return command
    return tool_text(event)


def extract_patch_paths(text: str) -> list[str]:
    return [*PATCH_PATH_RE.findall(text), *PATCH_MOVE_RE.findall(text)]


def _non_option_tokens(tokens: list[str]) -> list[str]:
    result = []
    for token in tokens:
        if token.startswith("-"):
            continue
        result.append(token)
    return result


def _shell_tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _split_simple_commands(tokens: list[str]) -> list[list[str]]:
    commands: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in SHELL_COMMAND_SEPARATORS or all(char in ";&|" for char in token):
            if current:
                commands.append(current)
                current = []
            continue
        current.append(token)
    if current:
        commands.append(current)
    return commands


def _without_redirections(tokens: list[str]) -> list[str]:
    result: list[str] = []
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if token in REDIRECT_TOKENS:
            skip_next = True
            continue
        if token.startswith((">", ">>", "1>", "1>>", "2>", "2>>", "&>", "&>>")):
            continue
        result.append(token)
    return result


def _simple_command_write_paths(tokens: list[str]) -> list[str]:
    tokens = _without_redirections(tokens)
    if not tokens:
        return []

    command_name = Path(tokens[0]).name
    args = tokens[1:]
    if command_name in {"touch", "rm", "mkdir"}:
        return _non_option_tokens(args)
    if command_name == "cp" and len(args) >= 2:
        non_options = _non_option_tokens(args)
        return non_options[-1:] if non_options else []
    if command_name == "mv" and len(args) >= 2:
        return _non_option_tokens(args)
    return []


def extract_bash_write_paths(command: str) -> list[str]:
    paths = [match.group(1) for match in REDIRECT_RE.finditer(command)]
    if "*** Begin Patch" in command:
        paths.extend(extract_patch_paths(command))

    try:
        tokens = _shell_tokens(command)
    except ValueError:
        return paths
    for simple_command in _split_simple_commands(tokens):
        paths.extend(_simple_command_write_paths(simple_command))
    return paths


def normalize_repo_path(root: Path, raw_path: str) -> str | None:
    value = raw_path.strip().strip('"').strip("'")
    if not value or value.startswith("-") or "://" in value:
        return None
    path = Path(value)
    if path.is_absolute():
        try:
            return str(path.resolve().relative_to(root))
        except ValueError:
            return str(path)
    if ".." in path.parts:
        return str(path)
    normalized = str(path)
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def contract_allowed_paths(contract: dict[str, Any]) -> list[str]:
    scope = contract.get("scope")
    if not isinstance(scope, dict):
        return []
    values = scope.get("allowed_paths")
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, str) and item.strip()]


def contract_required_outputs(contract: dict[str, Any]) -> list[str]:
    values = contract.get("required_outputs")
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, str) and item.strip()]


def required_output_repo_paths(ctx: HarnessContext) -> list[str]:
    task_rel = str(ctx.task_path.relative_to(ctx.root)).strip("/")
    return [f"{task_rel}/{path.strip('/')}" for path in contract_required_outputs(ctx.contract)]


def path_allowed(path: str, allowed_paths: list[str]) -> bool:
    normalized = path.strip("/")
    for raw_allowed in allowed_paths:
        allowed = raw_allowed.strip("/")
        if normalized == allowed:
            return True
        if raw_allowed.endswith("/") and normalized.startswith(allowed + "/"):
            return True
        if normalized.startswith(allowed + "/") and "." not in Path(allowed).name:
            return True
    return False


def runner_owned(path: str) -> bool:
    return any(pattern.match(path.strip("/")) for pattern in RUNNER_OWNED_PATTERNS)


def scope_violations(ctx: HarnessContext, raw_paths: list[str]) -> list[str]:
    allowed = [*contract_allowed_paths(ctx.contract), *required_output_repo_paths(ctx)]
    violations = []
    for raw_path in raw_paths:
        path = normalize_repo_path(ctx.root, raw_path)
        if path is None:
            continue
        if runner_owned(path):
            violations.append(f"{path} (runner-owned)")
            continue
        if not path_allowed(path, allowed):
            violations.append(path)
    return sorted(set(violations))


def pre_tool_block(reason: str) -> None:
    write_json(
        {
            "decision": "block",
            "reason": reason,
            "systemMessage": reason,
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            },
        }
    )


def post_tool_block(reason: str) -> None:
    write_json(
        {
            "decision": "block",
            "reason": reason,
            "continue": False,
            "stopReason": reason,
            "systemMessage": reason,
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": reason,
            },
        }
    )
