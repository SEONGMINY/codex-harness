#!/usr/bin/env python3
"""Run conservative quality checks for a harness phase."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import shlex
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from artifact_io import atomic_write_json
from command_policy import run_command
from redaction import redact_text

CODE_EXTENSIONS = {
    ".c",
    ".cc",
    ".css",
    ".go",
    ".h",
    ".html",
    ".java",
    ".js",
    ".jsx",
    ".json",
    ".kt",
    ".md",
    ".mjs",
    ".py",
    ".rs",
    ".scss",
    ".sh",
    ".swift",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
TEXT_EXTENSIONS = CODE_EXTENSIONS | {".toml", ".ini", ".cfg"}
DEFAULT_TIMEOUT_SECONDS = 120
PROJECT_LINT_LEVELS = {"warning", "block"}


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    atomic_write_json(path, data)


def run_capture(command: list[str], cwd: Path, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> tuple[int, str]:
    code, output, _timed_out, _argv = run_command(shlex.join(command), cwd, timeout)
    return code, output.strip()


def truncate_text(value: str, limit: int = 4000) -> str:
    value = redact_text(value)
    if len(value) <= limit:
        return value
    return value[-limit:]


def repo_changed_files(root: Path) -> list[str]:
    changed: set[str] = set()
    for command in (
        ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB", "HEAD"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        code, output = run_capture(command, root, 30)
        if code != 0:
            continue
        for line in output.splitlines():
            line = line.strip()
            if line:
                changed.add(line)
    return sorted(changed)


def normalize_path(raw_path: str) -> str:
    return raw_path.strip().lstrip("./")


def path_allowed(path: str, allowed_paths: list[str]) -> bool:
    if not allowed_paths:
        return True
    normalized = normalize_path(path)
    for pattern in allowed_paths:
        item = normalize_path(pattern)
        if not item:
            continue
        if item.endswith("/**"):
            prefix = item[:-3].rstrip("/")
            if normalized == prefix or normalized.startswith(f"{prefix}/"):
                return True
        if fnmatchcase(normalized, item):
            return True
        if normalized == item or normalized.startswith(f"{item.rstrip('/')}/"):
            return True
    return False


def contract_allowed_paths(contract: dict[str, Any]) -> list[str]:
    scope = contract.get("scope")
    if not isinstance(scope, dict):
        return []
    values = scope.get("allowed_paths")
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, str) and item.strip()]


def changed_files_from_args(root: Path, raw_files: list[str], contract: dict[str, Any]) -> list[str]:
    files = [normalize_path(item) for item in raw_files if item.strip()]
    if not files:
        files = repo_changed_files(root)
    allowed = contract_allowed_paths(contract)
    return sorted(path for path in files if path_allowed(path, allowed))


def package_manager(root: Path, package_json: dict[str, Any]) -> str:
    package_manager_value = str(package_json.get("packageManager") or "")
    if (root / "pnpm-workspace.yaml").exists() or package_manager_value.startswith("pnpm@"):
        return "pnpm"
    if (root / "yarn.lock").exists() or package_manager_value.startswith("yarn@"):
        return "yarn"
    return "npm"


def project_lint_commands(root: Path) -> list[list[str]]:
    package_json_path = root / "package.json"
    package_json = read_json(package_json_path)
    if package_json:
        scripts = package_json.get("scripts")
        if isinstance(scripts, dict):
            manager = package_manager(root, package_json)
            if not shutil.which(manager):
                return []
            commands = []
            for script_name in ["format:check", "lint"]:
                if isinstance(scripts.get(script_name), str):
                    commands.append([manager, "run", script_name])
            if commands:
                return commands

    if (root / "pyproject.toml").exists() or (root / "ruff.toml").exists():
        ruff = shutil.which("ruff")
        if ruff:
            return [[ruff, "check", "."], [ruff, "format", "--check", "."]]

    return []


def project_lint_checks(root: Path, level: str) -> list[dict[str, Any]]:
    package_json = read_json(root / "package.json")
    if package_json:
        scripts = package_json.get("scripts")
        if isinstance(scripts, dict) and any(isinstance(scripts.get(name), str) for name in ["format:check", "lint"]):
            manager = package_manager(root, package_json)
            if not shutil.which(manager):
                return [
                    {
                        "id": f"project-command:{manager}",
                        "level": level,
                        "status": "failed",
                        "command": [manager],
                        "exit_code": 127,
                        "output_tail": f"Package manager not found on PATH: {manager}",
                    }
                ]
            return [command_check(command, root, level) for command in project_lint_commands(root)]

    if (root / "pyproject.toml").exists() or (root / "ruff.toml").exists():
        ruff = shutil.which("ruff")
        if not ruff:
            return [
                {
                    "id": "project-command:ruff",
                    "level": level,
                    "status": "failed",
                    "command": ["ruff"],
                    "exit_code": 127,
                    "output_tail": "ruff configuration exists, but ruff was not found on PATH.",
                }
            ]
        return [
            command_check([ruff, "check", "."], root, level),
            command_check([ruff, "format", "--check", "."], root, level),
        ]

    return []


def command_check(command: list[str], root: Path, level: str) -> dict[str, Any]:
    code, output = run_capture(command, root)
    return {
        "id": "project-command:" + " ".join(command),
        "level": level,
        "status": "passed" if code == 0 else "failed",
        "command": command,
        "exit_code": code,
        "output_tail": truncate_text(output),
    }


def has_runnable_project_check(checks: list[dict[str, Any]]) -> bool:
    for check in checks:
        command = check.get("command")
        if isinstance(command, list) and len(command) > 1:
            return True
    return False


def readable_text_file(path: Path) -> bool:
    return path.suffix in TEXT_EXTENSIONS


def baseline_findings(root: Path, files: list[str]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for raw_path in files:
        path = root / raw_path
        if not path.is_file() or not readable_text_file(path):
            continue
        try:
            data = path.read_bytes()
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            findings.append({"path": raw_path, "reason": "text file is not valid UTF-8"})
            continue
        except OSError as exc:
            findings.append({"path": raw_path, "reason": f"could not read file: {exc}"})
            continue
        for index, line in enumerate(text.splitlines(), start=1):
            if line.rstrip(" \t") != line:
                findings.append({"path": raw_path, "line": str(index), "reason": "trailing whitespace"})
            if line.startswith(("<<<<<<< ", "=======", ">>>>>>> ")):
                findings.append({"path": raw_path, "line": str(index), "reason": "merge conflict marker"})
        if text and not text.endswith("\n"):
            findings.append({"path": raw_path, "reason": "missing final newline"})
    return findings


def python_compile_findings(root: Path, files: list[str]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for raw_path in files:
        if Path(raw_path).suffix != ".py":
            continue
        code, output = run_capture([sys.executable, "-m", "py_compile", raw_path], root, 30)
        if code != 0:
            findings.append(
                {
                    "path": raw_path,
                    "reason": "python syntax check failed",
                    "output_tail": truncate_text(output, 1000),
                }
            )
    return findings


def builtin_checks(root: Path, changed_files: list[str]) -> list[dict[str, Any]]:
    style_findings = baseline_findings(root, changed_files)
    compile_findings = python_compile_findings(root, changed_files)
    return [
        {
            "id": "harness-baseline-style",
            "level": "block",
            "status": "passed" if not style_findings else "failed",
            "findings": style_findings,
        },
        {
            "id": "harness-python-compile",
            "level": "block",
            "status": "passed" if not compile_findings else "failed",
            "findings": compile_findings,
        },
    ]


def summarize(checks: list[dict[str, Any]]) -> tuple[str, list[str]]:
    blocking = []
    for check in checks:
        if check.get("level") == "block" and check.get("status") == "failed":
            blocking.append(str(check.get("id") or "unknown check"))
    return ("failed" if blocking else "passed"), blocking


def run_quality_checks(
    root: Path,
    contract: dict[str, Any],
    changed_files: list[str],
    project_lint_level: str = "warning",
) -> dict[str, Any]:
    if project_lint_level not in PROJECT_LINT_LEVELS:
        project_lint_level = "warning"
    project = project_lint_checks(root, project_lint_level)
    if has_runnable_project_check(project):
        checks = project
        source = "project"
    else:
        baseline = builtin_checks(root, changed_files)
        checks = [*baseline, *project]
        source = "mixed" if project else "harness"
    status, blocking = summarize(checks)
    warning = [
        str(check.get("id") or "unknown check")
        for check in checks
        if check.get("level") == "warning" and check.get("status") == "failed"
    ]
    return {
        "status": status,
        "source": source,
        "changed_files": changed_files,
        "checks": checks,
        "blocking_reasons": [f"Quality check failed: {item}" for item in blocking],
        "warning_reasons": [f"Quality check warning: {item}" for item in warning],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--task-path", type=Path)
    parser.add_argument("--phase", type=int)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--project-lint-level",
        choices=sorted(PROJECT_LINT_LEVELS),
        default=os.environ.get("CODEX_HARNESS_PROJECT_LINT_LEVEL", "warning"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    contract = read_json(args.contract) if args.contract else {}
    changed_files = changed_files_from_args(root, args.changed_file, contract)
    result = run_quality_checks(root, contract, changed_files, args.project_lint_level)
    if args.task_path is not None:
        result["task"] = str(args.task_path)
    if args.phase is not None:
        result["phase"] = args.phase
    if args.output is not None:
        output = args.output
        if not output.is_absolute():
            output = root / output
        write_json(output, result)
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
