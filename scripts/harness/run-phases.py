#!/usr/bin/env python3
"""Run harness task phases with runner-owned status transitions."""

from __future__ import annotations

import argparse
import json
import re
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


def write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_capture(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    return output or "(no output)"


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


def phase_file(task_path: Path, phase_number: int) -> Path:
    preferred = task_path / "phases" / f"phase{phase_number}.md"
    legacy = task_path / f"phase{phase_number}.md"
    if preferred.exists():
        return preferred
    if legacy.exists():
        return legacy
    raise FileNotFoundError(f"Missing phase file: phase{phase_number}.md")


def pending_phase(task_index: dict) -> dict | None:
    for phase in task_index.get("phases", []):
        if phase.get("status") == "pending":
            return phase
    return None


def collect_files(root: Path, paths: Iterable[Path], max_bytes: int) -> str:
    chunks: list[str] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        if path.suffix not in TEXT_EXTENSIONS:
            continue
        rel = path.relative_to(root)
        data = path.read_text(encoding="utf-8", errors="replace")
        if len(data.encode("utf-8")) > max_bytes:
            data = data[:max_bytes] + "\n\n[truncated]\n"
        chunks.append(f"## `{rel}`\n\n{data.rstrip()}\n")
    return "\n".join(chunks).rstrip()


def static_context_files(task_path: Path) -> list[Path]:
    static_dir = task_path / "context-pack" / "static"
    if not static_dir.exists():
        return []
    return sorted(static_dir.rglob("*"))


def previous_handoff_files(task_path: Path, phase_number: int) -> list[Path]:
    handoff_dir = task_path / "context-pack" / "handoffs"
    return [handoff_dir / f"phase{n}.md" for n in range(phase_number)]


def runtime_context_files(task_path: Path, phase_number: int) -> list[Path]:
    runtime_dir = task_path / "context-pack" / "runtime"
    return [
        runtime_dir / "docs-diff.md",
        runtime_dir / f"phase{phase_number}-last-error.md",
    ]


def git_summary(root: Path) -> str:
    status = run_capture(["git", "status", "--short"], root)
    diff_stat = run_capture(["git", "diff", "--stat"], root)
    untracked = run_capture(["git", "ls-files", "--others", "--exclude-standard"], root)
    return (
        f"## Git Status\n\n```text\n{status}\n```\n\n"
        f"## Git Diff Stat\n\n```text\n{diff_stat}\n```\n\n"
        f"## Untracked Files\n\n```text\n{untracked}\n```"
    )


def parse_ac_commands(markdown: str) -> list[str]:
    match = re.search(
        r"## Acceptance Criteria(?P<body>.*?)(?:\n## |\Z)",
        markdown,
        flags=re.DOTALL,
    )
    if not match:
        return []
    commands: list[str] = []
    for block in re.findall(r"```(?:bash|sh|shell)?\n(.*?)```", match.group("body"), re.DOTALL):
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped == "TODO":
                continue
            commands.append(stripped)
    return commands


def build_prompt(root: Path, task_path: Path, task_index: dict, phase: dict) -> str:
    phase_number = int(phase["phase"])
    phase_path = phase_file(task_path, phase_number)
    phase_markdown = phase_path.read_text(encoding="utf-8")

    static_context = collect_files(root, static_context_files(task_path), 80_000)
    handoffs = collect_files(root, previous_handoff_files(task_path, phase_number), 60_000)
    runtime = collect_files(root, runtime_context_files(task_path, phase_number), 60_000)

    contract = f"""# Harness Phase Execution Contract

You are executing one phase for `{task_index.get("project")}`.

Task: `{task_index.get("task")}`
Phase: `{phase_number} - {phase.get("name")}`

Rules:

- Implement only this phase.
- Read the included context before editing.
- Do not update any `tasks/*/index.json` file.
- Do not mark the phase completed.
- Do not decide the next phase.
- Do not spawn subagents for implementation.
- Write `tasks/{task_path.name}/context-pack/handoffs/phase{phase_number}.md`.
- Run useful local checks when possible.
- Report changed files and remaining risk.

The runner will decide success by process exit code, required outputs, and AC commands.
"""

    parts = [
        contract,
        "# Static Context\n\n" + (static_context or "(none)"),
        "# Previous Handoffs\n\n" + (handoffs or "(none)"),
        "# Runtime Context\n\n" + (runtime or "(none)"),
        "# Repository Snapshot\n\n" + git_summary(root),
        "# Current Phase File\n\n" + phase_markdown.rstrip(),
    ]
    return "\n\n".join(parts).rstrip() + "\n"


def phase_ac_commands(phase: dict, phase_markdown: str) -> list[str]:
    commands = list(phase.get("ac_commands") or [])
    commands.extend(parse_ac_commands(phase_markdown))
    return [cmd for cmd in commands if cmd and cmd != "TODO"]


def run_shell(command: str, cwd: Path, timeout: int) -> tuple[int, str]:
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
    return result.returncode, output


def set_phase_status(task_index: dict, phase_number: int, status: str, **fields: object) -> None:
    for phase in task_index["phases"]:
        if int(phase["phase"]) == phase_number:
            phase["status"] = status
            phase.update(fields)
            return
    raise KeyError(f"Unknown phase: {phase_number}")


def update_top_index(root: Path, task_dir: str, status: str) -> None:
    top_index_path = root / "tasks" / "index.json"
    if not top_index_path.exists():
        return
    top_index = read_json(top_index_path)
    for task in top_index.get("tasks", []):
        if task.get("dir") == task_dir:
            task["status"] = status
            if status == "completed":
                task["completed_at"] = now()
            if status == "error":
                task["failed_at"] = now()
            write_json(top_index_path, top_index)
            return


def write_last_error(task_path: Path, phase_number: int, message: str) -> None:
    runtime_dir = task_path / "context-pack" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / f"phase{phase_number}-last-error.md").write_text(
        f"# Phase {phase_number} Last Error\n\n{message.rstrip()}\n",
        encoding="utf-8",
    )


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


def verify_required_outputs(task_path: Path, phase: dict) -> list[str]:
    missing = []
    for raw_path in phase.get("required_outputs") or []:
        target = task_path / raw_path
        if not target.exists():
            missing.append(raw_path)
    return missing


def execute_phase(root: Path, task_path: Path, args: argparse.Namespace) -> bool:
    index_path = task_path / "index.json"
    task_index = read_json(index_path)
    phase = pending_phase(task_index)
    if not phase:
        update_top_index(root, task_path.name, "completed")
        print("No pending phases.")
        return False

    phase_number = int(phase["phase"])
    prompt = build_prompt(root, task_path, task_index, phase)
    prompt_path = task_path / "context-pack" / "runtime" / f"phase{phase_number}-prompt.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")

    if args.dry_run:
        print(prompt_path)
        return False

    attempts = int(phase.get("attempts", 0))
    for attempt in range(attempts + 1, args.max_attempts + 1):
        task_index = read_json(index_path)
        set_phase_status(
            task_index,
            phase_number,
            "running",
            started_at=phase.get("started_at") or now(),
            attempts=attempt,
        )
        write_json(index_path, task_index)

        output_path = task_path / "context-pack" / "runtime" / f"phase{phase_number}-output-attempt{attempt}.jsonl"
        stderr_path = task_path / "context-pack" / "runtime" / f"phase{phase_number}-stderr-attempt{attempt}.txt"
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
            message = f"codex exec failed with exit code {returncode}. See {stderr_path}."
            write_last_error(task_path, phase_number, message)
            if attempt < args.max_attempts:
                prompt = build_prompt(root, task_path, read_json(index_path), phase)
                continue
            task_index = read_json(index_path)
            set_phase_status(task_index, phase_number, "error", failed_at=now(), error_message=message)
            write_json(index_path, task_index)
            update_top_index(root, task_path.name, "error")
            print(message, file=sys.stderr)
            return False

        phase_markdown = phase_file(task_path, phase_number).read_text(encoding="utf-8")
        for command in phase_ac_commands(phase, phase_markdown):
            ac_returncode, ac_output = run_shell(command, root, args.ac_timeout)
            if ac_returncode != 0:
                message = f"AC command failed: {command}\n\n{ac_output}"
                write_last_error(task_path, phase_number, message)
                if attempt < args.max_attempts:
                    prompt = build_prompt(root, task_path, read_json(index_path), phase)
                    break
                task_index = read_json(index_path)
                set_phase_status(task_index, phase_number, "error", failed_at=now(), error_message=message)
                write_json(index_path, task_index)
                update_top_index(root, task_path.name, "error")
                print(message, file=sys.stderr)
                return False
        else:
            missing_outputs = verify_required_outputs(task_path, phase)
            if missing_outputs:
                message = "Missing required outputs: " + ", ".join(missing_outputs)
                write_last_error(task_path, phase_number, message)
                if attempt < args.max_attempts:
                    prompt = build_prompt(root, task_path, read_json(index_path), phase)
                    continue
                task_index = read_json(index_path)
                set_phase_status(task_index, phase_number, "error", failed_at=now(), error_message=message)
                write_json(index_path, task_index)
                update_top_index(root, task_path.name, "error")
                print(message, file=sys.stderr)
                return False

            task_index = read_json(index_path)
            set_phase_status(
                task_index,
                phase_number,
                "completed",
                completed_at=now(),
                error_message=None,
            )
            write_json(index_path, task_index)
            print(f"Completed phase {phase_number}: {phase.get('name')}")
            return True

    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", help="Task directory name or path.")
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument("--codex-bin", default="codex", help="Codex executable.")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--ac-timeout", type=int, default=600)
    parser.add_argument("--dry-run", action="store_true", help="Only build the next prompt.")
    parser.add_argument("--one", action="store_true", help="Run only one pending phase.")
    parser.add_argument("--full-auto", action="store_true", help="Pass --full-auto to codex exec.")
    parser.add_argument(
        "--yolo",
        action="store_true",
        help="Pass --dangerously-bypass-approvals-and-sandbox to codex exec.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    task_path = resolve_task_path(root, args.task)

    while True:
        progressed = execute_phase(root, task_path, args)
        if args.dry_run or args.one or not progressed:
            break

    task_index = read_json(task_path / "index.json")
    if all(phase.get("status") == "completed" for phase in task_index.get("phases", [])):
        update_top_index(root, task_path.name, "completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
