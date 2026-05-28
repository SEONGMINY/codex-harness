#!/usr/bin/env python3
"""Evaluate a harness task from fresh context."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

from artifact_io import atomic_write_json, atomic_write_text
from codex_exec import CODEX_MAX_RUNTIME_EXIT_CODE, add_output_schema, run_codex_exec
from command_policy import run_command
from file_lock import LockHandle, acquire_repo_execution_lock, acquire_task_runtime_lock, release_lock
from harness_attestation import harness_attestation
from policy_pack import policy_pack_metadata
from policy_lineage import policy_pack_fingerprint, validate_current_policy_lineage
from task_paths import resolve_task_path


TEXT_EXTENSIONS = {".md", ".txt", ".json"}
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"


def runtime_policy_pack() -> dict[str, str]:
    return policy_pack_metadata()


def current_policy_lineage_errors(task_path: Path) -> list[str]:
    approval_path = task_path / "context-pack" / "static" / "design-approval.json"
    if not approval_path.exists():
        return []
    try:
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid design approval JSON before evaluation: {exc}"]
    current = policy_pack_fingerprint(runtime_policy_pack())
    return validate_current_policy_lineage(approval, current, action_label="evaluation")


def design_approval_scope_sha(task_path: Path) -> str | None:
    approval_path = task_path / "context-pack" / "static" / "design-approval.json"
    if not approval_path.exists():
        return None
    try:
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    value = approval.get("design_approval_scope_sha256") if isinstance(approval, dict) else None
    return value if isinstance(value, str) and value else None


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def task_relative(task_path: Path, path: Path) -> str:
    return str(path.relative_to(task_path))


def artifact_ref(task_path: Path, name: str, path: Path) -> dict[str, object]:
    item: dict[str, object] = {
        "name": name,
        "path": task_relative(task_path, path),
        "exists": path.exists() and path.is_file(),
    }
    if item["exists"]:
        item["sha256"] = file_sha256(path)
    return item


def phase_attempt_from_result(task_path: Path, phase_number: int) -> int | None:
    result_path = task_path / "context-pack" / "runtime" / f"phase{phase_number}-result.json"
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    attempt = result.get("attempt") if isinstance(result, dict) else None
    return attempt if isinstance(attempt, int) and attempt > 0 else None


def completed_phase_proofs(task_path: Path, task_index: dict) -> list[dict[str, object]]:
    proofs: list[dict[str, object]] = []
    runtime_dir = task_path / "context-pack" / "runtime"
    for phase in task_index.get("phases") or []:
        if not isinstance(phase, dict) or phase.get("status") != "completed":
            continue
        phase_number = phase.get("phase")
        if not isinstance(phase_number, int):
            continue
        attempt = phase.get("attempts")
        if not isinstance(attempt, int) or attempt <= 0:
            attempt = phase_attempt_from_result(task_path, phase_number)
        if not isinstance(attempt, int) or attempt <= 0:
            continue
        commit_path = runtime_dir / f"phase{phase_number}-attempt{attempt}-commit.json"
        proof: dict[str, object] = {
            "phase": phase_number,
            "attempt": attempt,
            "attempt_commit": artifact_ref(task_path, "attempt_commit", commit_path),
        }
        try:
            commit = json.loads(commit_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            commit = {}
        result_ref = commit.get("result") if isinstance(commit, dict) else None
        result_path = result_ref.get("path") if isinstance(result_ref, dict) else None
        if isinstance(result_path, str) and result_path.strip():
            proof["result"] = artifact_ref(task_path, "result", task_path / result_path)
        proofs.append(proof)
    return proofs


def write_evaluation_commit(
    task_path: Path,
    task_index: dict,
    artifacts: dict[str, Path],
) -> Path:
    runtime_dir = task_path / "context-pack" / "runtime"
    final_path = artifacts["last_message"]
    try:
        final = json.loads(final_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        final = {}
    commit = {
        "schema_version": 1,
        "commit_scope": "evaluation_bundle",
        "status": "committed",
        "verdict": final.get("verdict") if isinstance(final, dict) else None,
        "evaluated_at": now(),
        "policy_pack": runtime_policy_pack(),
        "harness_attestation": harness_attestation(),
        "design_approval_scope_sha256": design_approval_scope_sha(task_path),
        "task_index": artifact_ref(task_path, "task_index", task_path / "index.json"),
        "phase_proofs": completed_phase_proofs(task_path, task_index),
        "evaluation_artifacts": [
            artifact_ref(task_path, name, path)
            for name, path in artifacts.items()
        ],
    }
    path = runtime_dir / "evaluation-commit.json"
    atomic_write_json(path, commit)
    return path


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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
    code, output, timed_out, _argv = run_command(command, cwd, timeout)
    return {
        "command": command,
        "returncode": code,
        "output": output,
        "timed_out": timed_out,
    }


def collect_files(root: Path, paths: Iterable[Path], max_bytes: int) -> str:
    chunks: list[str] = []
    for path in paths:
        if not path.exists() or not path.is_file() or path.suffix not in TEXT_EXTENSIONS:
            continue
        rel = path.relative_to(root)
        if rel.as_posix().endswith("context-pack/static/design-approval.json"):
            continue
        data = path.read_text(encoding="utf-8", errors="replace")
        if len(data.encode("utf-8")) > max_bytes:
            data = data[:max_bytes] + "\n\n[truncated]\n"
        chunks.append(f"## `{rel}`\n\n{data.rstrip()}\n")
    return "\n".join(chunks).rstrip()


def context_files(root: Path, task_path: Path, task_index: dict) -> list[Path]:
    context_path = task_path / "context-pack"
    files: list[Path] = []
    for raw_path in task_index.get("common_docs") or []:
        files.append(root / raw_path)
    for raw_path in task_index.get("docs") or []:
        files.append(root / raw_path)
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
    context = collect_files(root, context_files(root, task_path, task_index), 100_000)
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

## Goal

Decide whether the task should be accepted from fresh evidence.

## Success Criteria

- The implementation satisfies the original intent.
- Validation commands passed or failures are explicitly blocking.
- Diffs stay within the approved task scope.
- Constraints and rejected options were respected.

## Hard Invariants

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

# Required Output

Return only the structured final output requested by the active output schema.
Use `approved` or `rejected` for `verdict`.
"""


def run_codex(
    root: Path,
    prompt: str,
    output_path: Path,
    stderr_path: Path,
    last_message_path: Path | None,
    codex_bin: str,
    full_auto: bool,
    yolo: bool,
    idle_timeout: int,
    activity_paths: Iterable[Path],
    max_runtime: int = 1800,
) -> int:
    command = [codex_bin, "exec", "--json"]
    if last_message_path is not None:
        command.extend(["--output-last-message", str(last_message_path)])
    add_output_schema(command, SCHEMA_DIR / "evaluation-final.schema.json")
    if yolo:
        command.append("--dangerously-bypass-approvals-and-sandbox")
    elif full_auto:
        command.append("--full-auto")
    command.append("-")

    return run_codex_exec(
        command,
        cwd=root,
        prompt=prompt,
        output_path=output_path,
        stderr_path=stderr_path,
        idle_timeout=idle_timeout,
        max_runtime=max_runtime,
        activity_paths=activity_paths,
    )


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
        "--codex-idle-timeout",
        type=non_negative_int,
        default=300,
        help="Fail codex exec after this many seconds with no activity. Use 0 to disable.",
    )
    parser.add_argument(
        "--codex-max-runtime",
        type=non_negative_int,
        default=1800,
        help="Fail codex exec after this many wall-clock seconds even if activity continues. Use 0 to disable.",
    )
    parser.add_argument(
        "--yolo",
        action="store_true",
        help="Pass --dangerously-bypass-approvals-and-sandbox to codex exec.",
    )
    parser.add_argument("--task-lock-held", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--repo-lock-held", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--strict-current-harness",
        action="store_true",
        help="Require evaluation to use the current harness policy lineage.",
    )
    parser.add_argument(
        "--repo-lock-timeout",
        type=int,
        default=0,
        help="Wait up to this many seconds for another run-phases repo execution to finish.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    task_path = resolve_task_path(root, args.task)
    runtime_dir = task_path / "context-pack" / "runtime"
    lock_handle: LockHandle | None = None
    repo_lock_handle: LockHandle | None = None

    try:
        if not args.task_lock_held:
            try:
                lock_handle = acquire_task_runtime_lock(task_path, "evaluate-task")
            except RuntimeError as exc:
                print(f"Another codex-harness task operation is active: {exc}", file=sys.stderr)
                return 1
        if not args.repo_lock_held:
            try:
                repo_lock_handle = acquire_repo_execution_lock(
                    root,
                    "evaluate-task",
                    task_path=task_path,
                    wait_timeout_seconds=args.repo_lock_timeout,
                )
            except RuntimeError as exc:
                print(f"Another codex-harness repo execution is active: {exc}", file=sys.stderr)
                return 1

        if args.strict_current_harness:
            lineage_errors = current_policy_lineage_errors(task_path)
            if lineage_errors:
                for error in lineage_errors:
                    print(error, file=sys.stderr)
                return 1

        task_index = read_json(task_path / "index.json")
        commands = list(args.command or task_index.get("evaluation_commands") or [])
        command_results = [run_shell(command, root, args.timeout) for command in commands]

        results_path = runtime_dir / "evaluation-command-results.json"
        metadata = {
            "schema_version": 1,
            "policy_pack": runtime_policy_pack(),
            "harness_attestation": harness_attestation(),
            "design_approval_scope_sha256": design_approval_scope_sha(task_path),
            "commands": command_results,
        }
        atomic_write_json(results_path, metadata)

        prompt = build_prompt(root, task_path, command_results)
        prompt_path = runtime_dir / "evaluation-prompt.md"
        atomic_write_text(prompt_path, prompt)

        failed_commands = [item for item in command_results if item["returncode"] != 0]
        if args.dry_run:
            print(prompt_path)
            return 1 if failed_commands else 0

        output_path = runtime_dir / "evaluation-output.jsonl"
        stderr_path = runtime_dir / "evaluation-stderr.txt"
        last_message_path = runtime_dir / "evaluation-last-message.json"
        returncode = run_codex(
            root,
            prompt,
            output_path,
            stderr_path,
            last_message_path,
            args.codex_bin,
            args.full_auto,
            args.yolo,
            args.codex_idle_timeout,
            [runtime_dir],
            max_runtime=args.codex_max_runtime,
        )
        if returncode != 0:
            print(f"codex exec failed. See {stderr_path}.", file=sys.stderr)
            return returncode
        write_evaluation_commit(
            task_path,
            task_index,
            {
                "command_results": results_path,
                "prompt": prompt_path,
                "output": output_path,
                "stderr": stderr_path,
                "last_message": last_message_path,
            },
        )
        if failed_commands:
            print(f"validation command failed. See {results_path}.", file=sys.stderr)
            return 1
        print(output_path)
        return 0
    finally:
        release_lock(repo_lock_handle)
        release_lock(lock_handle)


if __name__ == "__main__":
    raise SystemExit(main())
