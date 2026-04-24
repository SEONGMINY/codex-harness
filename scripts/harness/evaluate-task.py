#!/usr/bin/env python3
"""Evaluate a harness task from fresh context."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable


TEXT_EXTENSIONS = {".md", ".txt", ".json"}


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_task_path(root: Path, task_arg: str) -> Path:
    candidate = Path(task_arg)
    if candidate.is_absolute() and candidate.is_dir():
        return candidate
    if candidate.is_dir():
        return candidate.resolve()
    task_path = root / "tasks" / task_arg
    if task_path.is_dir():
        return task_path
    raise FileNotFoundError(f"Task directory not found: {task_arg}")


def run_capture(args: list[str], cwd: Path, max_chars: int = 120_000) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    if len(output) > max_chars:
        output = output[:max_chars] + "\n\n[truncated]\n"
    return output or "(no output)"


def run_shell(command: str, cwd: Path, timeout: int) -> dict:
    result = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    return {
        "command": command,
        "returncode": result.returncode,
        "output": output,
    }


def collect_files(root: Path, paths: Iterable[Path], max_bytes: int) -> str:
    chunks: list[str] = []
    for path in paths:
        if not path.exists() or not path.is_file() or path.suffix not in TEXT_EXTENSIONS:
            continue
        rel = path.relative_to(root)
        data = path.read_text(encoding="utf-8", errors="replace")
        if len(data.encode("utf-8")) > max_bytes:
            data = data[:max_bytes] + "\n\n[truncated]\n"
        chunks.append(f"## `{rel}`\n\n{data.rstrip()}\n")
    return "\n".join(chunks).rstrip()


def context_files(task_path: Path) -> list[Path]:
    context_path = task_path / "context-pack"
    files: list[Path] = []
    for relative in ["static", "handoffs"]:
        target = context_path / relative
        if target.exists():
            files.extend(sorted(target.rglob("*")))
    runtime = context_path / "runtime" / "docs-diff.md"
    if runtime.exists():
        files.append(runtime)
    return files


def untracked_text_files(root: Path) -> list[Path]:
    output = run_capture(["git", "ls-files", "--others", "--exclude-standard"], root)
    files: list[Path] = []
    for line in output.splitlines():
        if not line or line == "(no output)":
            continue
        path = root / line
        if path.is_file() and path.suffix in TEXT_EXTENSIONS:
            files.append(path)
    return files


def build_prompt(root: Path, task_path: Path, command_results: list[dict]) -> str:
    task_index = read_json(task_path / "index.json")
    context = collect_files(root, context_files(task_path), 100_000)
    status = run_capture(["git", "status", "--short"], root)
    diff_stat = run_capture(["git", "diff", "--stat"], root)
    diff = run_capture(["git", "diff"], root, max_chars=160_000)
    untracked = collect_files(root, untracked_text_files(root), 120_000)

    command_json = json.dumps(command_results, ensure_ascii=False, indent=2)

    return f"""# Harness Evaluation Contract

Evaluate this task from fresh context.

Project: `{task_index.get("project")}`
Task: `{task_index.get("task")}`
Time: `{now()}`

Rules:

- Do not trust phase self-reporting.
- Verify the implementation against the original intent.
- Check tests, diffs, scope, constraints, and rejected options.
- Identify concrete blockers first.
- Do not modify files.

# Context

{context or "(none)"}

# Command Results

```json
{command_json}
```

# Git Status

```text
{status}
```

# Git Diff Stat

```text
{diff_stat}
```

# Git Diff

```diff
{diff}
```

# Untracked Text Files

{untracked or "(none)"}

# Required Output Format

판정: 승인 | 거부
신뢰도: 0-100
핵심 근거: <한 문장>

상세:

* 테스트: <판단 결과>
* 구현: <판단 결과>
* 스코프: <판단 결과>
* 리스크: <판단 결과>
* 후속 작업: <없으면 "없음">
"""


def run_codex(
    root: Path,
    prompt: str,
    output_path: Path,
    stderr_path: Path,
    codex_bin: str,
    full_auto: bool,
    yolo: bool,
) -> int:
    command = [codex_bin, "exec", "--json"]
    if yolo:
        command.append("--dangerously-bypass-approvals-and-sandbox")
    elif full_auto:
        command.append("--full-auto")
    command.append("-")

    result = subprocess.run(
        command,
        cwd=root,
        input=prompt,
        text=True,
        capture_output=True,
        check=False,
    )
    output_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", help="Task directory name or path.")
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument("--codex-bin", default="codex", help="Codex executable.")
    parser.add_argument("--command", action="append", default=[], help="Validation command.")
    parser.add_argument("--timeout", type=int, default=600, help="Validation command timeout.")
    parser.add_argument("--dry-run", action="store_true", help="Only write the evaluation prompt.")
    parser.add_argument("--full-auto", action="store_true", help="Pass --full-auto to codex exec.")
    parser.add_argument(
        "--yolo",
        action="store_true",
        help="Pass --dangerously-bypass-approvals-and-sandbox to codex exec.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    task_path = resolve_task_path(root, args.task)
    runtime_dir = task_path / "context-pack" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    task_index = read_json(task_path / "index.json")
    commands = list(args.command or task_index.get("evaluation_commands") or [])
    command_results = [run_shell(command, root, args.timeout) for command in commands]

    results_path = runtime_dir / "evaluation-command-results.json"
    results_path.write_text(
        json.dumps(command_results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    prompt = build_prompt(root, task_path, command_results)
    prompt_path = runtime_dir / "evaluation-prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")

    failed_commands = [item for item in command_results if item["returncode"] != 0]
    if args.dry_run:
        print(prompt_path)
        return 1 if failed_commands else 0

    output_path = runtime_dir / "evaluation-output.jsonl"
    stderr_path = runtime_dir / "evaluation-stderr.txt"
    returncode = run_codex(
        root,
        prompt,
        output_path,
        stderr_path,
        args.codex_bin,
        args.full_auto,
        args.yolo,
    )
    if returncode != 0:
        print(f"codex exec failed. See {stderr_path}.", file=sys.stderr)
        return returncode
    if failed_commands:
        print(f"validation command failed. See {results_path}.", file=sys.stderr)
        return 1
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
