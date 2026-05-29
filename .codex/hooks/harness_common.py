"""Shared helpers for codex-harness hooks."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shlex
import subprocess
import sys
import importlib.util
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any


PATCH_PATH_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.MULTILINE)
PATCH_MOVE_RE = re.compile(r"^\*\*\* Move to: (.+)$", re.MULTILINE)
REDIRECT_RE = re.compile(r"(?:^|\s)(?:>|>>)\s*([^\s;&|]+)")
SHELL_COMMAND_SEPARATORS = {"&&", "||", ";", "|"}
REDIRECT_TOKENS = {">", ">>", "1>", "1>>", "2>", "2>>", "&>", "&>>", "<", "<<", "<<<"}
SUPPORTED_WRITE_TOOLS = ["Bash", "apply_patch", "Edit", "Write", "MultiEdit", "NotebookEdit"]
HOOK_WRITE_TOOL_MATCHER = "|".join(SUPPORTED_WRITE_TOOLS)
OPAQUE_BASH_EVAL_FLAGS = {
    "bash": {"-c", "-lc"},
    "node": {"-e", "--eval"},
    "perl": {"-e"},
    "python": {"-c"},
    "python3": {"-c"},
    "ruby": {"-e"},
    "sh": {"-c"},
    "zsh": {"-c"},
}
OPAQUE_BASH_COMMANDS = {"tee"}
RUNNER_OWNED_PATTERNS = [
    re.compile(r"^tasks/index\.json$"),
    re.compile(r"^tasks/[^/]+/index\.json$"),
    re.compile(r"^tasks/[^/]+/context-pack/runtime/docs-diff\.md$"),
    re.compile(r"^tasks/[^/]+/context-pack/runtime/progress\.md$"),
    re.compile(r"^tasks/[^/]+/context-pack/runtime/install-preflight\.json$"),
    re.compile(
        r"^tasks/[^/]+/context-pack/runtime/evaluation-"
        r"(?:command-results|prompt|output)\.(?:json|md|jsonl)$"
    ),
    re.compile(
        r"^tasks/[^/]+/context-pack/runtime/phase\d+-"
        r"(?:prompt(?:-attempt\d+)?|contract(?:-attempt\d+)?|checklist(?:-attempt\d+)?|"
        r"output-attempt\d+|stderr-attempt\d+|ac-attempt\d+|"
        r"evidence(?:-attempt\d+)?|reconciliation(?:-attempt\d+)?|gate(?:-attempt\d+)?|"
        r"quality(?:-attempt\d+)?|handoff-attempt\d+|result(?:-attempt\d+)?|"
        r"last-error|repair-packet(?:-attempt\d+)?|reset-marker|baseline|"
        r"attempt\d+-commit|attempt-manifest|obligation-closure-attempt\d+)"
        r"\.(?:md|json|jsonl|txt)$"
    ),
    re.compile(r"^tasks/[^/]+/context-pack/runtime/run-phases\.lock$"),
    re.compile(r"^tasks/[^/]+/context-pack/runtime/evaluation-last-message\.json$"),
    re.compile(
        r"^tasks/[^/]+/context-pack/runtime/evaluation-repair\d+-"
        r"(?:prompt|output|stderr|last-message|result)\.(?:md|json|jsonl|txt)$"
    ),
]
SCOPE_POLICY_CACHE: dict[str, Any] = {}


@dataclass(frozen=True)
class HarnessContext:
    root: Path
    task_path: Path
    phase: int
    contract_path: Path
    contract: dict[str, Any]
    cwd: Path | None = None


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


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def safe_relative_path(raw_value: str | None) -> Path | None:
    if not raw_value:
        return None
    path = Path(raw_value)
    if path.is_absolute() or ".." in path.parts:
        return None
    return path


def active_context(event: dict[str, Any]) -> HarnessContext | None:
    if os.environ.get("CODEX_HARNESS_ACTIVE") != "1":
        return None

    cwd = Path(str(event.get("cwd") or os.getcwd())).resolve()
    root = Path(os.environ.get("CODEX_HARNESS_ROOT") or repo_root(cwd)).resolve()
    if root != repo_root(cwd):
        return None
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
    if phase < 0:
        return None

    if task_rel:
        safe_task_rel = safe_relative_path(task_rel)
        if safe_task_rel is None:
            return None
        task_path = (root / safe_task_rel).resolve()
    elif task_name:
        safe_task_name = safe_relative_path(task_name)
        if safe_task_name is None or len(safe_task_name.parts) != 1:
            return None
        task_path = (root / "tasks" / task_name).resolve()
    else:
        return None
    if not is_relative_to(task_path, root / "tasks"):
        return None

    safe_contract_rel = safe_relative_path(contract_rel)
    if safe_contract_rel is None:
        return None
    contract_path = (root / safe_contract_rel).resolve()
    if not is_relative_to(contract_path, task_path / "context-pack" / "runtime"):
        return None
    if not contract_path.exists():
        return None
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(contract, dict):
        return None
    contract_phase = contract.get("phase")
    if isinstance(contract_phase, int) and contract_phase != phase:
        return None
    return HarnessContext(root, task_path, phase, contract_path, contract, cwd)


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


def bash_policy_violations(command: str) -> list[str]:
    errors: list[str] = []
    if "<<" in command:
        errors.append("Bash here-doc input is opaque to codex-harness scope checks.")
    try:
        tokens = _shell_tokens(command)
    except ValueError as exc:
        return [f"Bash command must parse before phase execution: {exc}"]
    for simple_command in _split_simple_commands(tokens):
        effective_tokens = _without_redirections(simple_command)
        if not effective_tokens:
            continue
        executable = Path(effective_tokens[0]).name
        if executable in OPAQUE_BASH_COMMANDS:
            errors.append(f"Bash command is opaque to codex-harness scope checks: {executable}")
            continue
        eval_flags = OPAQUE_BASH_EVAL_FLAGS.get(executable, set())
        for token in effective_tokens[1:]:
            for flag in eval_flags:
                if token == flag or token.startswith(f"{flag}=") or (
                    flag in {"-c", "-e"} and token.startswith(flag) and token != flag
                ):
                    errors.append(
                        "Bash interpreter eval mode is opaque to codex-harness scope checks: "
                        f"{executable} {token}"
                    )
                    break
    return errors


def _extract_path_fields(value: Any) -> list[str]:
    if isinstance(value, dict):
        result: list[str] = []
        for key, item in value.items():
            if key in {"file_path", "path", "new_path", "notebook_path"} and isinstance(item, str):
                result.append(item)
            else:
                result.extend(_extract_path_fields(item))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_extract_path_fields(item))
        return result
    return []


def extract_tool_write_paths(event: dict[str, Any]) -> list[str]:
    tool_name = str(event.get("tool_name") or "")
    text = tool_text(event)
    if tool_name == "apply_patch" or "*** Begin Patch" in text:
        return extract_patch_paths(text)
    if tool_name == "Bash":
        return extract_bash_write_paths(shell_command(event))
    if tool_name in set(SUPPORTED_WRITE_TOOLS) - {"Bash", "apply_patch"}:
        return _extract_path_fields(event.get("tool_input"))
    return []


def normalize_repo_path(root: Path, raw_path: str, cwd: Path | None = None) -> str | None:
    value = raw_path.strip().strip('"').strip("'")
    if not value or value.startswith("-") or "://" in value:
        return None
    path = Path(value)
    if path.is_absolute():
        try:
            return str(path.resolve().relative_to(root))
        except ValueError:
            return str(path)
    base = (cwd or root).resolve()
    resolved = (base / path).resolve()
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return str(path)


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


def stable_json_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def trusted_harness_scope_policy(root: Path, candidate: Path) -> bool:
    scripts_dir = root / ".codex" / "harness" / "scripts"
    try:
        rel_path = candidate.resolve().relative_to(scripts_dir.resolve()).as_posix()
    except ValueError:
        return False
    manifest_path = root / ".codex" / "harness" / "install-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    attestation = manifest.get("runtime_attestation") if isinstance(manifest, dict) else None
    if not isinstance(attestation, dict):
        return False
    entries = attestation.get("entries")
    if not isinstance(entries, list) or attestation.get("digest") != stable_json_sha256(entries):
        return False
    expected_path = f"harness:{rel_path}"
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("path") != expected_path:
            continue
        expected_sha = entry.get("sha256")
        return isinstance(expected_sha, str) and candidate.exists() and file_sha256(candidate) == expected_sha
    return False


def scope_policy_module(root: Path) -> Any | None:
    candidates = [
        root / ".codex" / "harness" / "scripts" / "scope_policy.py",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        if not trusted_harness_scope_policy(root, candidate):
            continue
        cache_key = str(candidate.resolve())
        if cache_key in SCOPE_POLICY_CACHE:
            return SCOPE_POLICY_CACHE[cache_key]
        spec = importlib.util.spec_from_file_location("codex_harness_scope_policy", candidate)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        SCOPE_POLICY_CACHE[cache_key] = module
        return module
    return None


def path_allowed(path: str, allowed_paths: list[str], root: Path | None = None) -> bool:
    if root is not None:
        module = scope_policy_module(root)
        if module is not None:
            return bool(module.path_allowed(path, allowed_paths))
    normalized = path.strip("/")
    for raw_allowed in allowed_paths:
        allowed = raw_allowed.strip("/")
        if not allowed:
            continue
        if _path_glob_match(normalized, allowed):
            return True
        if any(char in allowed for char in "*?["):
            if allowed.endswith("/**"):
                prefix = allowed[:-3].rstrip("/")
                if normalized == prefix or normalized.startswith(prefix + "/"):
                    return True
            continue
        if normalized == allowed:
            return True
        if raw_allowed.endswith("/") and normalized.startswith(allowed + "/"):
            return True
        if normalized.startswith(allowed + "/") and "." not in Path(allowed).name:
            return True
    return False


def _path_glob_match(path: str, pattern: str) -> bool:
    if not any(char in pattern for char in "*?["):
        return False

    def match_parts(path_parts: list[str], pattern_parts: list[str]) -> bool:
        if not pattern_parts:
            return not path_parts
        head = pattern_parts[0]
        tail = pattern_parts[1:]
        if head == "**":
            return match_parts(path_parts, tail) or (
                bool(path_parts) and match_parts(path_parts[1:], pattern_parts)
            )
        if not path_parts:
            return False
        return fnmatchcase(path_parts[0], head) and match_parts(path_parts[1:], tail)

    return match_parts(path.split("/") if path else [], pattern.split("/") if pattern else [])


def runner_owned(path: str) -> bool:
    return any(pattern.match(path.strip("/")) for pattern in RUNNER_OWNED_PATTERNS)


def scope_violations(ctx: HarnessContext, raw_paths: list[str]) -> list[str]:
    allowed = [*contract_allowed_paths(ctx.contract), *required_output_repo_paths(ctx)]
    violations = []
    for raw_path in raw_paths:
        path = normalize_repo_path(ctx.root, raw_path, ctx.cwd)
        if path is None:
            continue
        if runner_owned(path):
            violations.append(f"{path} (runner-owned)")
            continue
        if not path_allowed(path, allowed, ctx.root):
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
