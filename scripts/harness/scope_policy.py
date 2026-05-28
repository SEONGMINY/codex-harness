"""Shared path scope semantics for codex-harness runtime checks."""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any


def normalize_path(raw_path: str) -> str:
    value = raw_path.strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    while "//" in value:
        value = value.replace("//", "/")
    return value.rstrip("/")


def contract_allowed_paths(contract: dict[str, Any] | None) -> list[str]:
    if not isinstance(contract, dict):
        return []
    scope = contract.get("scope")
    if not isinstance(scope, dict):
        return []
    values = scope.get("allowed_paths")
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, str) and item.strip()]


def required_output_repo_paths(task_path: Path, required_outputs: list[str]) -> list[str]:
    return [f"tasks/{task_path.name}/{raw_path.strip('/')}" for raw_path in required_outputs]


def path_allowed(path: str, allowed_paths: list[str]) -> bool:
    normalized = normalize_path(path)
    for raw_allowed in allowed_paths:
        allowed = normalize_path(raw_allowed)
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


def scope_violations(
    changed_files: list[str],
    allowed_paths: list[str],
    ignored_paths: list[str],
) -> list[str]:
    violations = []
    for path in changed_files:
        if path_allowed(path, ignored_paths):
            continue
        if not path_allowed(path, allowed_paths):
            violations.append(path)
    return sorted(violations)


def traceable_changed_files(task_path: Path, changed_files: list[str], required_outputs: list[str]) -> list[str]:
    ignored_paths = required_output_repo_paths(task_path, required_outputs)
    return [
        path
        for path in changed_files
        if not path_allowed(path, ignored_paths)
    ]
