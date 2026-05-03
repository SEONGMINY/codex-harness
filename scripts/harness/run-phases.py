#!/usr/bin/env python3
"""Run harness task phases with runner-owned status transitions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

from codex_exec import CODEX_IDLE_EXIT_CODE, add_output_schema, run_codex_exec
from phase_contract import (
    checklist_markdown,
    contract_acceptance_commands,
    contract_allowed_paths,
    contract_required_outputs,
    parse_phase_contract,
    scope_violations,
    validate_phase_contract,
)


TEXT_EXTENSIONS = {".md", ".txt", ".json"}
RUNNABLE_PHASE_STATUSES = {"pending", "running"}
HARNESS_VERSION = "0.1.0"
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
MANDATORY_STATIC_FILES = [
    "original-prompt.md",
    "product.md",
    "decisions.md",
    "rejected-options.md",
    "constraints.md",
    "test-policy.md",
    "clarify-review.md",
    "docs-approval.md",
    "context-gathering.md",
    "docs-index.md",
]
PLACEHOLDER_PATTERNS = [
    re.compile(r"^\s*TODO\b", re.MULTILINE),
    re.compile(r"\[TODO", re.IGNORECASE),
    re.compile(r"PLACEHOLDER", re.IGNORECASE),
]


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def harness_install_errors(root: Path) -> list[str]:
    manifest_path = root / "codex-harness.json"
    if not manifest_path.exists():
        return ["Missing codex-harness.json. Reinstall codex-harness in this project."]
    try:
        manifest = read_json(manifest_path)
    except (json.JSONDecodeError, OSError) as exc:
        return [f"Invalid codex-harness.json: {exc}"]

    version = manifest.get("version")
    if version != HARNESS_VERSION:
        return [
            "codex-harness version mismatch: "
            f"script={HARNESS_VERSION}, manifest={version or '(missing)'}. "
            "Reinstall or update codex-harness in this project."
        ]
    return []


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


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
        if phase.get("status") in RUNNABLE_PHASE_STATUSES:
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


def runtime_context_files(
    task_path: Path,
    phase_number: int,
    include_current_failure_context: bool = True,
) -> list[Path]:
    runtime_dir = task_path / "context-pack" / "runtime"
    paths = [
        runtime_dir / "docs-diff.md",
    ]
    if include_current_failure_context:
        paths.extend(
            [
                runtime_dir / f"phase{phase_number}-last-error.md",
                runtime_dir / f"phase{phase_number}-repair-packet.md",
                runtime_dir / f"phase{phase_number}-repair-packet.json",
                runtime_dir / f"phase{phase_number}-gate.json",
                runtime_dir / f"phase{phase_number}-reconciliation.md",
                runtime_dir / f"phase{phase_number}-evidence.json",
            ]
        )
    for previous in range(phase_number):
        paths.extend(
            [
                runtime_dir / f"phase{previous}-reconciliation.md",
                runtime_dir / f"phase{previous}-gate.json",
            ]
        )
    return paths


def phase_result_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-result.json"


def phase_contract_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-contract.json"


def phase_checklist_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-checklist.md"


def phase_evidence_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-evidence.json"


def phase_reconciliation_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-reconciliation.json"


def phase_reconciliation_summary_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-reconciliation.md"


def phase_gate_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-gate.json"


def phase_repair_packet_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-repair-packet.json"


def phase_repair_packet_summary_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-repair-packet.md"


def runner_lock_path(task_path: Path) -> Path:
    return task_path / "context-pack" / "runtime" / "run-phases.lock"


def phase_handoff_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "handoffs" / f"phase{phase_number}.md"


def ac_results_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-ac-attempt{attempt}.json"


def task_doc_files(root: Path, task_index: dict) -> list[Path]:
    return [root / raw_path for raw_path in task_index.get("docs") or []]


def common_doc_files(root: Path, task_index: dict) -> list[Path]:
    return [root / raw_path for raw_path in task_index.get("common_docs") or []]


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


def markdown_bullets(items: object, fallback: str = "- none") -> str:
    if not isinstance(items, list):
        return fallback
    lines = [f"- {item}" for item in items if isinstance(item, str) and item.strip()]
    return "\n".join(lines) if lines else fallback


def fallback_behavior_text(contract: dict) -> str:
    value = contract.get("fallback_behavior")
    if isinstance(value, dict):
        lines = [
            f"- {key}: {item}"
            for key, item in value.items()
            if isinstance(key, str) and isinstance(item, str) and item.strip()
        ]
        return "\n".join(lines) if lines else "- none"
    return "- none"


def validation_budget_text(contract: dict) -> str:
    value = contract.get("validation_budget")
    if not isinstance(value, dict):
        return "- none"
    lines = []
    for key in ["max_attempts", "command_timeout_seconds"]:
        if key in value:
            lines.append(f"- {key}: `{value[key]}`")
    return "\n".join(lines) if lines else "- none"


def contract_validation_budget(contract: dict | None, args: argparse.Namespace) -> tuple[int, int]:
    budget = contract.get("validation_budget") if isinstance(contract, dict) else None
    if not isinstance(budget, dict):
        return args.max_attempts, args.ac_timeout

    max_attempts = budget.get("max_attempts")
    command_timeout = budget.get("command_timeout_seconds")
    return (
        max_attempts if isinstance(max_attempts, int) and max_attempts > 0 else args.max_attempts,
        command_timeout if isinstance(command_timeout, int) and command_timeout > 0 else args.ac_timeout,
    )


def build_prompt(
    root: Path,
    task_path: Path,
    task_index: dict,
    phase: dict,
    include_repair_packet: bool = True,
) -> str:
    phase_number = int(phase["phase"])
    phase_path = phase_file(task_path, phase_number)
    phase_markdown = phase_path.read_text(encoding="utf-8")
    contract_data = materialize_phase_contract(task_path, phase_number, phase_markdown)

    common_docs_context = collect_files(root, common_doc_files(root, task_index), 60_000)
    docs_context = collect_files(root, task_doc_files(root, task_index), 80_000)
    static_context = collect_files(root, static_context_files(task_path), 80_000)
    handoffs = collect_files(root, previous_handoff_files(task_path, phase_number), 60_000)
    runtime = collect_files(
        root,
        runtime_context_files(
            task_path,
            phase_number,
            include_current_failure_context=include_repair_packet,
        ),
        60_000,
    )
    checklist_context = phase_checklist_path(task_path, phase_number).read_text(encoding="utf-8")
    repair_summary = phase_repair_packet_summary_path(task_path, phase_number)
    repair_mode = ""
    if include_repair_packet and repair_summary.exists():
        repair_mode = f"""

Repair mode:

- A previous attempt for this phase failed.
- Read `tasks/{task_path.name}/context-pack/runtime/phase{phase_number}-repair-packet.md` first.
- Fix only the failures listed in the repair packet.
- Keep the phase contract unchanged.
- Do not expand scope or edit runner-owned runtime files.
"""

    contract = f"""# Harness Phase Execution Contract

You are executing one phase for `{task_index.get("project")}`.

Task: `{task_index.get("task")}`
Phase: `{phase_number} - {phase.get("name")}`

## Goal

Deliver only the outcome required by this phase contract.

## Success Criteria

{markdown_bullets(contract_data.get("success_criteria"))}

The runner also requires:

- Codex exits successfully.
- Contract acceptance commands pass.
- Required outputs exist.
- Changed files stay within `scope.allowed_paths`.

## Hard Invariants

- Implement only this phase.
- Read the included context before editing.
- Do not update any `tasks/*/index.json` file.
- Do not mark the phase completed.
- Do not decide the next phase.
- Do not spawn subagents for implementation.
- Do not edit runner-owned runtime proof files.

## Output Contract

- Write `tasks/{task_path.name}/context-pack/handoffs/phase{phase_number}.md`.
- Run useful local checks when possible.
- Return only the structured final output requested by the active output schema.

## Stop Rules

{markdown_bullets(contract_data.get("stop_rules"))}

## Fallback Behavior

{fallback_behavior_text(contract_data)}

## Validation Budget

{validation_budget_text(contract_data)}

## Missing Evidence Behavior

{contract_data.get("missing_evidence_behavior")}

The runner will decide success by process exit code, required outputs, and AC commands.
The runner will generate `tasks/{task_path.name}/context-pack/runtime/phase{phase_number}-result.json`.
{repair_mode}"""

    parts = [
        contract,
        "# Common Docs\n\n" + (common_docs_context or "(none)"),
        "# Mandatory Docs\n\n" + (docs_context or "(none)"),
        "# Static Context\n\n" + (static_context or "(none)"),
        "# Previous Handoffs\n\n" + (handoffs or "(none)"),
        "# Runtime Context\n\n" + (runtime or "(none)"),
        "# Repository Snapshot\n\n" + git_summary(root),
        "# Current Phase Checklist\n\n" + checklist_context.rstrip(),
        "# Current Phase File\n\n" + phase_markdown.rstrip(),
    ]
    return "\n\n".join(parts).rstrip() + "\n"


def materialize_phase_contract(task_path: Path, phase_number: int, phase_markdown: str) -> dict:
    contract_data, contract_errors = parse_phase_contract(phase_markdown)
    if contract_errors or contract_data is None:
        raise ValueError("; ".join(contract_errors))
    phase_contract_path(task_path, phase_number).parent.mkdir(parents=True, exist_ok=True)
    write_json(phase_contract_path(task_path, phase_number), contract_data)
    phase_checklist_path(task_path, phase_number).write_text(
        checklist_markdown(contract_data),
        encoding="utf-8",
    )
    return contract_data


def runtime_phase_contract(task_path: Path, phase_number: int) -> dict:
    path = phase_contract_path(task_path, phase_number)
    if not path.exists():
        raise FileNotFoundError(f"Missing runtime phase contract: {path}")
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"Runtime phase contract must be a JSON object: {path}")
    return data


def verify_phase_contract_unchanged(task_path: Path, phase_number: int, original_contract: dict) -> list[str]:
    current_markdown = phase_file(task_path, phase_number).read_text(encoding="utf-8")
    current_contract, errors = parse_phase_contract(current_markdown)
    if errors or current_contract is None:
        return ["Phase contract block missing or invalid after Codex execution: " + "; ".join(errors)]
    if phase_contract_hash(current_contract) != phase_contract_hash(original_contract):
        return ["Phase contract changed during Codex execution."]
    return []


def phase_ac_commands(phase: dict, phase_markdown: str) -> list[str]:
    contract, _ = parse_phase_contract(phase_markdown)
    if contract is not None:
        commands = contract_acceptance_commands(contract)
        if commands:
            return commands
    commands = list(phase.get("ac_commands") or [])
    commands.extend(parse_ac_commands(phase_markdown))
    unique_commands = []
    seen = set()
    for command in commands:
        if not command or command == "TODO" or command in seen:
            continue
        seen.add(command)
        unique_commands.append(command)
    return unique_commands


def phase_required_outputs(phase: dict, phase_markdown: str) -> list[str]:
    contract, _ = parse_phase_contract(phase_markdown)
    if contract is not None:
        outputs = contract_required_outputs(contract)
        if outputs:
            return outputs
    return list(phase.get("required_outputs") or [])


def contract_ac_commands(phase: dict, contract: dict) -> list[str]:
    commands = contract_acceptance_commands(contract)
    if commands:
        return commands
    return list(phase.get("ac_commands") or [])


def contract_outputs(phase: dict, contract: dict) -> list[str]:
    outputs = contract_required_outputs(contract)
    if outputs:
        return outputs
    return list(phase.get("required_outputs") or [])


def phase_contract_hash(contract: dict) -> str:
    payload = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def has_placeholder(text: str) -> bool:
    return any(pattern.search(text) for pattern in PLACEHOLDER_PATTERNS)


def require_real_file(root: Path, path: Path, label: str) -> list[str]:
    if not path.exists():
        return [f"Missing {label}: {path.relative_to(root)}"]
    if not path.is_file():
        return [f"Not a file: {path.relative_to(root)}"]

    errors = []
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        errors.append(f"Empty {label}: {path.relative_to(root)}")
    if has_placeholder(text):
        errors.append(f"Placeholder remains in {label}: {path.relative_to(root)}")
    return errors


def preflight_phase(root: Path, task_path: Path, task_index: dict, phase: dict) -> list[str]:
    errors = []
    phase_number = int(phase["phase"])
    phase_path = phase_file(task_path, phase_number)
    phase_markdown = phase_path.read_text(encoding="utf-8")
    contract, contract_errors = validate_phase_contract(
        root,
        task_path,
        phase_number,
        phase.get("name"),
        phase_markdown,
        require_previous_outputs=True,
    )
    errors.extend(contract_errors)

    if has_placeholder(phase_markdown):
        errors.append(f"Placeholder remains in phase file: {phase_path.relative_to(root)}")

    if not phase_ac_commands(phase, phase_markdown):
        errors.append(f"Missing AC commands for phase {phase_number}.")

    if not phase_required_outputs(phase, phase_markdown):
        errors.append(f"Missing required_outputs for phase {phase_number}.")
    if contract is not None and phase.get("required_outputs"):
        contract_outputs = contract_required_outputs(contract)
        if list(phase.get("required_outputs") or []) != contract_outputs:
            errors.append(
                "Phase index required_outputs must match Contract.required_outputs. "
                f"expected={contract_outputs!r} actual={list(phase.get('required_outputs') or [])!r}"
            )
    if contract is not None and phase.get("ac_commands"):
        contract_commands = contract_acceptance_commands(contract)
        if list(phase.get("ac_commands") or []) != contract_commands:
            errors.append(
                "Phase index ac_commands must match Contract.acceptance_commands. "
                f"expected={contract_commands!r} actual={list(phase.get('ac_commands') or [])!r}"
            )

    docs = task_doc_files(root, task_index)
    if len(docs) < 5:
        errors.append("Task index must list mandatory docs.")
    for path in common_doc_files(root, task_index):
        errors.extend(require_real_file(root, path, "common doc"))
    for path in docs:
        errors.extend(require_real_file(root, path, "doc"))

    static_dir = task_path / "context-pack" / "static"
    for filename in MANDATORY_STATIC_FILES:
        errors.extend(require_real_file(root, static_dir / filename, "static context"))

    for prior_phase in range(phase_number):
        handoff = task_path / "context-pack" / "handoffs" / f"phase{prior_phase}.md"
        if not handoff.exists():
            errors.append(f"Missing previous handoff: {handoff.relative_to(root)}")

    return errors


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


def git_lines(args: list[str], root: Path) -> list[str]:
    result = subprocess.run(
        args,
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def file_digest(path: Path) -> str:
    if not path.exists():
        return "<deleted>"
    if not path.is_file():
        return "<non-file>"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def worktree_snapshot(root: Path) -> dict[str, str]:
    paths: set[str] = set()
    for command in [
        ["git", "diff", "--name-only"],
        ["git", "diff", "--name-only", "--cached"],
        ["git", "ls-files", "--deleted"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]:
        paths.update(git_lines(command, root))
    return {path: file_digest(root / path) for path in sorted(paths)}


def changed_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )


def phase_changed_paths(task_path: Path, before: dict[str, str], after: dict[str, str]) -> list[str]:
    runtime_prefix = f"tasks/{task_path.name}/context-pack/runtime/"
    return [
        path
        for path in changed_paths(before, after)
        if not path.startswith(runtime_prefix)
    ]


def set_phase_status(task_index: dict, phase_number: int, status: str, **fields: object) -> None:
    for phase in task_index["phases"]:
        if int(phase["phase"]) == phase_number:
            phase["status"] = status
            phase.update(fields)
            return
    raise KeyError(f"Unknown phase: {phase_number}")


def reset_phase_statuses(task_index: dict, from_phase: int, reset_at: str) -> list[dict]:
    reset_results = []
    for phase in task_index.get("phases", []):
        phase_number = int(phase["phase"])
        old_status = phase.get("status")
        if phase_number < from_phase:
            continue

        phase["status"] = "pending"
        phase["reset_at"] = reset_at
        phase["attempts"] = 0
        for field in ["started_at", "completed_at", "failed_at", "error_message"]:
            phase.pop(field, None)
        reset_results.append(
            {
                "phase": phase_number,
                "name": phase.get("name"),
                "from_status": old_status,
                "to_status": "pending",
            }
        )
    return reset_results


def print_reset_summary(from_phase: int, reset_results: list[dict], dry_run: bool) -> None:
    label = "Dry-run reset" if dry_run else "Reset"
    print(f"{label} from phase {from_phase}:")
    if not reset_results:
        print("- No phases reset.")
        return

    for item in reset_results:
        name = f" {item['name']}" if item.get("name") else ""
        print(
            f"- phase {item['phase']}{name}: "
            f"{item['from_status']} -> {item['to_status']}"
        )


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
                task.pop("failed_at", None)
            if status == "error":
                task["failed_at"] = now()
                task.pop("completed_at", None)
            if status == "pending":
                task.pop("completed_at", None)
                task.pop("failed_at", None)
            write_json(top_index_path, top_index)
            return


def write_last_error(task_path: Path, phase_number: int, message: str) -> None:
    runtime_dir = task_path / "context-pack" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / f"phase{phase_number}-last-error.md").write_text(
        f"# Phase {phase_number} Last Error\n\n{message.rstrip()}\n",
        encoding="utf-8",
    )


def process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_is_stale(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    pid = data.get("pid") if isinstance(data, dict) else None
    if not isinstance(pid, int) or pid <= 0:
        return True
    return not process_is_alive(pid)


def acquire_runner_lock(task_path: Path, dry_run: bool) -> Path | None:
    if dry_run:
        return None
    path = runner_lock_path(task_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"pid": os.getpid(), "started_at": now()}
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            if lock_is_stale(path):
                path.unlink(missing_ok=True)
                continue
            raise RuntimeError(f"Another run-phases process is active: {path}") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        return path


def release_runner_lock(path: Path | None) -> None:
    if path is not None:
        path.unlink(missing_ok=True)


def allowed_path_activity_root(root: Path, raw_path: str) -> Path | None:
    value = raw_path.strip().lstrip("./")
    if not value or value.startswith("../") or Path(value).is_absolute():
        return None
    if "*" in value:
        prefix = value.split("*", 1)[0].rstrip("/")
        if not prefix:
            return root
        return root / prefix
    return root / value


def phase_activity_paths(root: Path, task_path: Path, phase_number: int) -> list[Path]:
    paths = [phase_handoff_path(task_path, phase_number)]
    try:
        contract = runtime_phase_contract(task_path, phase_number)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return paths
    for raw_path in contract_allowed_paths(contract):
        activity_root = allowed_path_activity_root(root, raw_path)
        if activity_root is not None:
            paths.append(activity_root)
    return paths


def run_codex(
    root: Path,
    task_path: Path,
    phase_number: int,
    prompt: str,
    output_path: Path,
    stderr_path: Path,
    codex_bin: str,
    full_auto: bool,
    yolo: bool,
    idle_timeout: int,
) -> int:
    command = [codex_bin, "exec", "--json"]
    add_output_schema(command, SCHEMA_DIR / "phase-final.schema.json")
    if yolo:
        command.append("--dangerously-bypass-approvals-and-sandbox")
    elif full_auto:
        command.append("--full-auto")
    command.append("-")

    env = os.environ.copy()
    env.update(
        {
            "CODEX_HARNESS_ACTIVE": "1",
            "CODEX_HARNESS_ROOT": str(root),
            "CODEX_HARNESS_TASK": task_path.name,
            "CODEX_HARNESS_TASK_PATH": str(task_path.relative_to(root)),
            "CODEX_HARNESS_PHASE": str(phase_number),
            "CODEX_HARNESS_CONTRACT_PATH": str(
                phase_contract_path(task_path, phase_number).relative_to(root)
            ),
        }
    )

    return run_codex_exec(
        command,
        cwd=root,
        prompt=prompt,
        output_path=output_path,
        stderr_path=stderr_path,
        env=env,
        idle_timeout=idle_timeout,
        activity_paths=phase_activity_paths(root, task_path, phase_number),
    )


def verify_required_outputs(task_path: Path, required_outputs: list[str]) -> list[str]:
    missing = []
    for raw_path in required_outputs:
        target = task_path / raw_path
        if not target.exists():
            missing.append(raw_path)
    return missing


def required_output_results(task_path: Path, required_outputs: list[str]) -> list[dict[str, object]]:
    return [
        {
            "path": raw_path,
            "exists": (task_path / raw_path).exists(),
        }
        for raw_path in required_outputs
    ]


def task_relative(path: Path, task_path: Path) -> str:
    return str(path.relative_to(task_path))


def write_ac_results(
    task_path: Path,
    phase_number: int,
    attempt: int,
    command_results: list[dict[str, object]],
) -> Path:
    path = ac_results_path(task_path, phase_number, attempt)
    write_json(
        path,
        {
            "phase": phase_number,
            "attempt": attempt,
            "commands": command_results,
        },
    )
    return path


def write_phase_result(
    task_path: Path,
    phase_number: int,
    attempt: int,
    codex_exit_code: int,
    changed_files: list[str],
    command_results: list[dict[str, object]],
    required_outputs: list[str],
    prompt_path: Path,
    output_path: Path,
    stderr_path: Path,
    ac_results: Path,
) -> None:
    result = {
        "phase": phase_number,
        "status": "completed",
        "attempt": attempt,
        "codex_exit_code": codex_exit_code,
        "changed_files": changed_files,
        "commands_run": [
            {
                "command": item["command"],
                "exit_code": item["exit_code"],
            }
            for item in command_results
        ],
        "tests_passed": all(item["exit_code"] == 0 for item in command_results),
        "required_outputs": required_output_results(task_path, required_outputs),
        "artifacts": {
            "contract": task_relative(phase_contract_path(task_path, phase_number), task_path),
            "checklist": task_relative(phase_checklist_path(task_path, phase_number), task_path),
            "prompt": task_relative(prompt_path, task_path),
            "stdout": task_relative(output_path, task_path),
            "stderr": task_relative(stderr_path, task_path),
            "ac_results": task_relative(ac_results, task_path),
            "handoff": task_relative(phase_handoff_path(task_path, phase_number), task_path),
            "evidence": task_relative(phase_evidence_path(task_path, phase_number), task_path),
            "reconciliation": task_relative(phase_reconciliation_path(task_path, phase_number), task_path),
            "reconciliation_summary": task_relative(phase_reconciliation_summary_path(task_path, phase_number), task_path),
            "gate": task_relative(phase_gate_path(task_path, phase_number), task_path),
        },
    }
    repair_packet = phase_repair_packet_path(task_path, phase_number)
    repair_packet_summary = phase_repair_packet_summary_path(task_path, phase_number)
    if repair_packet.exists():
        result["artifacts"]["repair_packet"] = task_relative(repair_packet, task_path)
    if repair_packet_summary.exists():
        result["artifacts"]["repair_packet_summary"] = task_relative(repair_packet_summary, task_path)
    write_json(phase_result_path(task_path, phase_number), result)


def required_output_repo_paths(task_path: Path, required_outputs: list[str]) -> list[str]:
    return [f"tasks/{task_path.name}/{raw_path.strip('/')}" for raw_path in required_outputs]


def build_gate(
    task_path: Path,
    phase_number: int,
    contract: dict,
    changed_files: list[str],
    command_results: list[dict[str, object]],
    required_outputs: list[str],
) -> dict[str, object]:
    failed_commands = [item for item in command_results if item.get("exit_code") != 0]
    missing_outputs = verify_required_outputs(task_path, required_outputs)
    violations = scope_violations(
        changed_files,
        contract_allowed_paths(contract),
        required_output_repo_paths(task_path, required_outputs),
    )
    blocking_reasons: list[str] = []
    if failed_commands:
        blocking_reasons.append("One or more acceptance commands failed.")
    if missing_outputs:
        blocking_reasons.append("One or more required outputs are missing.")
    if violations:
        blocking_reasons.append("Changed files include paths outside Contract.scope.allowed_paths.")

    checks = [
        {
            "name": "acceptance_commands",
            "status": "passed" if not failed_commands else "failed",
            "failed_commands": [item.get("command") for item in failed_commands],
        },
        {
            "name": "required_outputs",
            "status": "passed" if not missing_outputs else "failed",
            "missing_outputs": missing_outputs,
        },
        {
            "name": "scope",
            "status": "passed" if not violations else "failed",
            "violations": violations,
        },
    ]
    return {
        "phase": phase_number,
        "status": "passed" if not blocking_reasons else "failed",
        "checks": checks,
        "blocking_reasons": blocking_reasons,
    }


def build_evidence(
    phase_number: int,
    attempt: int,
    changed_files: list[str],
    command_results: list[dict[str, object]],
    required_outputs: list[str],
    task_path: Path,
) -> dict[str, object]:
    return {
        "phase": phase_number,
        "attempt": attempt,
        "changed_files": changed_files,
        "commands": command_results,
        "required_outputs": required_output_results(task_path, required_outputs),
    }


def _normalized_evidence_path(raw_path: object) -> str | None:
    if not isinstance(raw_path, str):
        return None
    value = raw_path.strip().strip("`").strip()
    if not value:
        return None
    return value.lstrip("./")


def _path_matches(expected: str, observed: str) -> bool:
    return observed == expected or observed.endswith(f"/{expected}")


def expected_evidence_matched(expected: object, evidence: dict[str, object]) -> bool:
    expected_text = _normalized_evidence_path(expected)
    if expected_text is None:
        return False

    for item in evidence.get("commands", []) or []:
        if (
            isinstance(item, dict)
            and item.get("command") == expected_text
            and item.get("exit_code") == 0
        ):
            return True

    for item in evidence.get("required_outputs", []) or []:
        if (
            isinstance(item, dict)
            and item.get("exists") is True
            and item.get("path") == expected_text
        ):
            return True

    for raw_path in evidence.get("changed_files", []) or []:
        observed = _normalized_evidence_path(raw_path)
        if observed and _path_matches(expected_text, observed):
            return True

    return False


def build_reconciliation(contract: dict, evidence: dict[str, object], gate: dict[str, object]) -> dict[str, object]:
    gate_passed = gate.get("status") == "passed"
    observed_evidence = [
        f"changed_files={evidence.get('changed_files', [])!r}",
        f"commands={[item.get('command') for item in evidence.get('commands', [])]!r}",
        f"gate={gate.get('status')}",
    ]
    instruction_results = []
    for instruction in contract.get("instructions") or []:
        expected_items = instruction.get("expected_evidence") or []
        matched_expected = [
            item
            for item in expected_items
            if expected_evidence_matched(item, evidence)
        ]
        if not gate_passed:
            status = "blocked"
        elif expected_items and len(matched_expected) == len(expected_items):
            status = "satisfied"
        else:
            status = "unverified"
        instruction_results.append(
            {
                "id": instruction.get("id"),
                "task": instruction.get("task"),
                "expected_evidence": expected_items,
                "matched_expected_evidence": matched_expected,
                "observed_evidence": observed_evidence,
                "status": status,
                "method": "structured_evidence_match",
            }
        )
    aggregate_status = "satisfied" if gate_passed else "blocked"
    return {
        "phase": contract.get("phase"),
        "status": aggregate_status,
        "instruction_results": instruction_results,
        "extra_changes": [
            violation
            for check in gate.get("checks", [])
            if check.get("name") == "scope"
            for violation in check.get("violations", [])
        ],
        "blocking_reasons": gate.get("blocking_reasons", []),
    }


def reconciliation_markdown(reconciliation: dict[str, object], gate: dict[str, object]) -> str:
    lines = [
        f"# Phase {reconciliation.get('phase')} Reconciliation",
        "",
        f"Gate: `{gate.get('status')}`",
        f"Status: `{reconciliation.get('status')}`",
        "",
        "Unverified items are QA notes. They do not trigger a retry when the gate passes.",
        "",
        "## Instruction Results",
        "",
    ]
    for item in reconciliation.get("instruction_results", []):
        lines.append(f"- `{item.get('id')}` {item.get('status')}: {item.get('task')}")
    lines.extend(["", "## Blocking Reasons", ""])
    reasons = gate.get("blocking_reasons") or []
    if reasons:
        for reason in reasons:
            lines.append(f"- {reason}")
    else:
        lines.append("- none")
    lines.extend(["", "## Extra Changes", ""])
    extra_changes = reconciliation.get("extra_changes") or []
    if extra_changes:
        for path in extra_changes:
            lines.append(f"- `{path}`")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_runtime_review_artifacts(
    task_path: Path,
    phase_number: int,
    contract: dict,
    evidence: dict[str, object],
    gate: dict[str, object],
) -> dict[str, object]:
    reconciliation = build_reconciliation(contract, evidence, gate)
    write_json(phase_evidence_path(task_path, phase_number), evidence)
    write_json(phase_gate_path(task_path, phase_number), gate)
    write_json(phase_reconciliation_path(task_path, phase_number), reconciliation)
    phase_reconciliation_summary_path(task_path, phase_number).write_text(
        reconciliation_markdown(reconciliation, gate),
        encoding="utf-8",
    )
    return reconciliation


def truncate_text(value: object, max_chars: int = 4_000) -> str:
    text = "" if value is None else str(value)
    if len(text) <= max_chars:
        return text
    return "[truncated]\n" + text[-max_chars:]


def compact_command_results(command_results: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "command": item.get("command"),
            "exit_code": item.get("exit_code"),
            "output_tail": truncate_text(item.get("output"), 3_000),
        }
        for item in command_results
    ]


def failed_gate_checks(gate: dict[str, object] | None) -> list[dict[str, object]]:
    if not gate:
        return []
    return [
        check
        for check in gate.get("checks", [])
        if isinstance(check, dict) and check.get("status") != "passed"
    ]


def failed_instruction_results(reconciliation: dict[str, object] | None) -> list[dict[str, object]]:
    if not reconciliation:
        return []
    return [
        item
        for item in reconciliation.get("instruction_results", [])
        if isinstance(item, dict) and item.get("status") != "satisfied"
    ]


def contract_summary(contract: dict | None, phase: dict, required_outputs: list[str]) -> dict[str, object] | None:
    if contract is None:
        return None
    return {
        "phase": contract.get("phase"),
        "name": contract.get("name") or phase.get("name"),
        "read_first": contract.get("read_first") or [],
        "allowed_paths": contract_allowed_paths(contract),
        "acceptance_commands": contract_ac_commands(phase, contract),
        "required_outputs": required_outputs,
        "success_criteria": contract.get("success_criteria") or [],
        "stop_rules": contract.get("stop_rules") or [],
        "fallback_behavior": contract.get("fallback_behavior") or {},
        "validation_budget": contract.get("validation_budget") or {},
        "missing_evidence_behavior": contract.get("missing_evidence_behavior"),
        "instructions": [
            {
                "id": item.get("id"),
                "task": item.get("task"),
                "expected_evidence": item.get("expected_evidence") or [],
            }
            for item in contract.get("instructions") or []
            if isinstance(item, dict)
        ],
    }


def build_repair_packet(
    task_path: Path,
    phase_number: int,
    phase: dict,
    attempt: int,
    failure_type: str,
    message: str,
    *,
    retryable: bool,
    contract: dict | None = None,
    codex_exit_code: int | None = None,
    stderr_path: Path | None = None,
    command_results: list[dict[str, object]] | None = None,
    required_outputs: list[str] | None = None,
    missing_outputs: list[str] | None = None,
    changed_files: list[str] | None = None,
    gate: dict[str, object] | None = None,
    reconciliation: dict[str, object] | None = None,
) -> dict[str, object]:
    commands = command_results or []
    outputs = required_outputs or []
    stderr_tail = ""
    if stderr_path and stderr_path.exists():
        stderr_tail = truncate_text(stderr_path.read_text(encoding="utf-8", errors="replace"), 4_000)
    return {
        "phase": phase_number,
        "attempt": attempt,
        "status": "repair_required",
        "created_at": now(),
        "failure": {
            "type": failure_type,
            "message": truncate_text(message, 4_000),
            "retryable": retryable,
            "codex_exit_code": codex_exit_code,
            "stderr_tail": stderr_tail,
        },
        "contract": contract_summary(contract, phase, outputs),
        "failed_commands": [
            item
            for item in compact_command_results(commands)
            if item.get("exit_code") != 0
        ],
        "commands": compact_command_results(commands),
        "required_outputs": required_output_results(task_path, outputs),
        "missing_outputs": missing_outputs or [],
        "changed_files": changed_files or [],
        "failed_gate_checks": failed_gate_checks(gate),
        "blocking_reasons": list(gate.get("blocking_reasons") or []) if gate else [],
        "instruction_results_to_repair": failed_instruction_results(reconciliation),
        "next_attempt_instructions": [
            "Repair only the current phase.",
            "Read this repair packet before editing.",
            "Keep the phase contract unchanged.",
            "Do not change task indexes or runner-owned runtime files.",
            "Fix the listed failures before doing unrelated cleanup.",
            "Leave the required handoff for this phase.",
        ],
    }


def repair_packet_markdown(packet: dict[str, object]) -> str:
    failure = packet.get("failure") or {}
    contract = packet.get("contract") or {}
    lines = [
        f"# Phase {packet.get('phase')} Repair Packet",
        "",
        f"Attempt: `{packet.get('attempt')}`",
        f"Failure type: `{failure.get('type')}`",
        f"Retryable: `{failure.get('retryable')}`",
        "",
        "## Failure",
        "",
        str(failure.get("message") or "(none)").rstrip(),
        "",
        "## Next Attempt",
        "",
    ]
    for item in packet.get("next_attempt_instructions") or []:
        lines.append(f"- {item}")

    failed_commands = packet.get("failed_commands") or []
    lines.extend(["", "## Failed Commands", ""])
    if failed_commands:
        for item in failed_commands:
            lines.append(f"- `{item.get('command')}` exited `{item.get('exit_code')}`")
            output = item.get("output_tail")
            if output:
                lines.extend(["", "```text", str(output).rstrip(), "```", ""])
    else:
        lines.append("- none")

    missing_outputs = packet.get("missing_outputs") or []
    lines.extend(["", "## Missing Outputs", ""])
    if missing_outputs:
        for path in missing_outputs:
            lines.append(f"- `{path}`")
    else:
        lines.append("- none")

    failed_checks = packet.get("failed_gate_checks") or []
    lines.extend(["", "## Failed Gate Checks", ""])
    if failed_checks:
        for check in failed_checks:
            lines.append(f"- `{check.get('name')}`: {json.dumps(check, ensure_ascii=False)}")
    else:
        lines.append("- none")

    instructions = packet.get("instruction_results_to_repair") or []
    lines.extend(["", "## Instructions To Repair", ""])
    if instructions:
        for item in instructions:
            lines.append(f"- `{item.get('id')}` {item.get('status')}: {item.get('task')}")
    else:
        lines.append("- none")

    lines.extend(["", "## Contract Reminders", ""])
    if contract:
        lines.append("Allowed paths:")
        for path in contract.get("allowed_paths") or []:
            lines.append(f"- `{path}`")
        lines.extend(["", "Acceptance commands:"])
        for command in contract.get("acceptance_commands") or []:
            lines.append(f"- `{command}`")
        lines.extend(["", "Required outputs:"])
        for path in contract.get("required_outputs") or []:
            lines.append(f"- `{path}`")
    else:
        lines.append("- contract unavailable")
    lines.append("")
    return "\n".join(lines)


def write_repair_packet(
    task_path: Path,
    phase_number: int,
    packet: dict[str, object],
) -> None:
    write_json(phase_repair_packet_path(task_path, phase_number), packet)
    phase_repair_packet_summary_path(task_path, phase_number).write_text(
        repair_packet_markdown(packet),
        encoding="utf-8",
    )


def clear_attempt_artifacts(task_path: Path, phase_number: int) -> None:
    for path in [
        phase_result_path(task_path, phase_number),
        phase_handoff_path(task_path, phase_number),
        phase_evidence_path(task_path, phase_number),
        phase_reconciliation_path(task_path, phase_number),
        phase_reconciliation_summary_path(task_path, phase_number),
        phase_gate_path(task_path, phase_number),
    ]:
        path.unlink(missing_ok=True)


def clear_repair_packet(task_path: Path, phase_number: int) -> None:
    for path in [
        phase_repair_packet_path(task_path, phase_number),
        phase_repair_packet_summary_path(task_path, phase_number),
    ]:
        path.unlink(missing_ok=True)


def generate_docs_diff(root: Path, task_path: Path, baseline: str | None) -> None:
    output_path = task_path / "context-pack" / "runtime" / "docs-diff.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not baseline:
        diff = "(no baseline recorded)"
    else:
        result = subprocess.run(
            ["git", "diff", baseline, "--", "docs/", str((task_path / "docs").relative_to(root))],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        diff = result.stdout.strip() or "(no docs diff)"

    output_path.write_text(
        f"# docs-diff: {task_path.name}\n\n"
        f"Baseline: `{baseline or 'none'}`\n\n"
        "```diff\n"
        f"{diff}\n"
        "```\n",
        encoding="utf-8",
    )


def run_evaluation(root: Path, task_path: Path, args: argparse.Namespace) -> int:
    command = [
        sys.executable,
        str(root / "scripts" / "harness" / "evaluate-task.py"),
        task_path.name,
        "--root",
        str(root),
    ]
    for eval_command in args.eval_command or []:
        command.extend(["--command", eval_command])
    if args.full_auto:
        command.append("--full-auto")
    if args.yolo:
        command.append("--yolo")
    return subprocess.run(command, cwd=root, check=False).returncode


def verify_task(root: Path, task_path: Path, require_evaluation: bool = False) -> int:
    command = [
        sys.executable,
        str(root / "scripts" / "harness" / "verify-task.py"),
        task_path.name,
        "--root",
        str(root),
    ]
    if require_evaluation:
        command.append("--require-evaluation")
    return subprocess.run(command, cwd=root, check=False).returncode


def apply_phase_reset(
    root: Path,
    task_path: Path,
    from_phase: int | None,
    dry_run: bool,
) -> dict | None:
    if from_phase is None:
        return None

    index_path = task_path / "index.json"
    task_index = read_json(index_path)
    reset_results = reset_phase_statuses(task_index, from_phase, now())
    print_reset_summary(from_phase, reset_results, dry_run)

    if dry_run:
        return task_index

    if reset_results:
        write_json(index_path, task_index)
        update_top_index(root, task_path.name, "pending")
        for item in reset_results:
            clear_repair_packet(task_path, int(item["phase"]))
    return None


def execute_phase(
    root: Path,
    task_path: Path,
    args: argparse.Namespace,
    task_index_override: dict | None = None,
) -> bool:
    index_path = task_path / "index.json"
    task_index = task_index_override or read_json(index_path)
    phase = pending_phase(task_index)
    if not phase:
        if not args.dry_run:
            if verify_task(root, task_path) != 0:
                args.failed = True
                update_top_index(root, task_path.name, "error")
                return False
            update_top_index(root, task_path.name, "completed")
        print("No pending phases.")
        return False

    phase_number = int(phase["phase"])
    attempts = int(phase.get("attempts", 0) or 0)
    if attempts <= 0 and not args.dry_run:
        clear_repair_packet(task_path, phase_number)

    preflight_errors = preflight_phase(root, task_path, task_index, phase)
    if preflight_errors:
        message = "Preflight failed:\n" + "\n".join(f"- {error}" for error in preflight_errors)
        write_last_error(task_path, phase_number, message)
        print(message, file=sys.stderr)
        args.failed = True
        return False

    prompt = build_prompt(
        root,
        task_path,
        task_index,
        phase,
        include_repair_packet=attempts > 0,
    )
    prompt_path = task_path / "context-pack" / "runtime" / f"phase{phase_number}-prompt.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    try:
        initial_contract = runtime_phase_contract(task_path, phase_number)
    except (FileNotFoundError, ValueError):
        initial_contract = None
    max_attempts, ac_timeout = contract_validation_budget(initial_contract, args)

    if args.dry_run:
        print(prompt_path)
        return False

    if attempts >= max_attempts:
        message = (
            "Phase attempt budget exhausted: "
            f"attempts={attempts}, max_attempts={max_attempts}."
        )
        write_last_error(task_path, phase_number, message)
        task_index = read_json(index_path)
        set_phase_status(task_index, phase_number, "error", failed_at=now(), error_message=message)
        write_json(index_path, task_index)
        update_top_index(root, task_path.name, "error")
        print(message, file=sys.stderr)
        args.failed = True
        return False

    phase_start_snapshot: dict[str, str] | None = None
    for attempt in range(attempts + 1, max_attempts + 1):
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
        clear_attempt_artifacts(task_path, phase_number)
        if phase_start_snapshot is None:
            phase_start_snapshot = worktree_snapshot(root)
        prompt_path.write_text(prompt, encoding="utf-8")
        returncode = run_codex(
            root,
            task_path,
            phase_number,
            prompt,
            output_path,
            stderr_path,
            args.codex_bin,
            args.full_auto,
            args.yolo,
            args.codex_idle_timeout,
        )
        if returncode != 0:
            message = f"codex exec failed with exit code {returncode}. See {stderr_path}."
            write_last_error(task_path, phase_number, message)
            try:
                contract = runtime_phase_contract(task_path, phase_number)
                required_outputs = contract_outputs(phase, contract)
            except (FileNotFoundError, ValueError):
                contract = None
                required_outputs = []
            if contract is not None:
                contract_tamper_errors = verify_phase_contract_unchanged(task_path, phase_number, contract)
                if contract_tamper_errors:
                    message = "; ".join(contract_tamper_errors)
                    write_last_error(task_path, phase_number, message)
                    task_index = read_json(index_path)
                    set_phase_status(task_index, phase_number, "error", failed_at=now(), error_message=message)
                    write_json(index_path, task_index)
                    update_top_index(root, task_path.name, "error")
                    print(message, file=sys.stderr)
                    args.failed = True
                    return False
            write_repair_packet(
                task_path,
                phase_number,
                build_repair_packet(
                    task_path,
                    phase_number,
                    phase,
                    attempt,
                    "codex_exec",
                    message,
                    retryable=attempt < max_attempts,
                    contract=contract,
                    codex_exit_code=returncode,
                    stderr_path=stderr_path,
                    required_outputs=required_outputs,
                ),
            )
            if attempt < max_attempts:
                prompt = build_prompt(root, task_path, read_json(index_path), phase)
                continue
            task_index = read_json(index_path)
            set_phase_status(task_index, phase_number, "error", failed_at=now(), error_message=message)
            write_json(index_path, task_index)
            update_top_index(root, task_path.name, "error")
            print(message, file=sys.stderr)
            args.failed = True
            return False

        try:
            contract = runtime_phase_contract(task_path, phase_number)
        except (FileNotFoundError, ValueError) as exc:
            message = str(exc)
            write_last_error(task_path, phase_number, message)
            task_index = read_json(index_path)
            set_phase_status(task_index, phase_number, "error", failed_at=now(), error_message=message)
            write_json(index_path, task_index)
            update_top_index(root, task_path.name, "error")
            print(message, file=sys.stderr)
            args.failed = True
            return False
        contract_tamper_errors = verify_phase_contract_unchanged(task_path, phase_number, contract)
        if contract_tamper_errors:
            message = "; ".join(contract_tamper_errors)
            write_last_error(task_path, phase_number, message)
            task_index = read_json(index_path)
            set_phase_status(task_index, phase_number, "error", failed_at=now(), error_message=message)
            write_json(index_path, task_index)
            update_top_index(root, task_path.name, "error")
            print(message, file=sys.stderr)
            args.failed = True
            return False
        required_outputs = contract_outputs(phase, contract)
        command_results: list[dict[str, object]] = []
        for command in contract_ac_commands(phase, contract):
            ac_returncode, ac_output = run_shell(command, root, ac_timeout)
            command_results.append(
                {
                    "command": command,
                    "exit_code": ac_returncode,
                    "output": ac_output,
                }
            )
            if ac_returncode != 0:
                message = f"AC command failed: {command}\n\n{ac_output}"
                write_last_error(task_path, phase_number, message)
                write_ac_results(task_path, phase_number, attempt, command_results)
                write_repair_packet(
                    task_path,
                    phase_number,
                    build_repair_packet(
                        task_path,
                        phase_number,
                        phase,
                        attempt,
                        "acceptance_commands",
                        message,
                        retryable=attempt < max_attempts,
                        contract=contract,
                        command_results=command_results,
                        required_outputs=required_outputs,
                    ),
                )
                if attempt < max_attempts:
                    prompt = build_prompt(root, task_path, read_json(index_path), phase)
                    break
                task_index = read_json(index_path)
                set_phase_status(task_index, phase_number, "error", failed_at=now(), error_message=message)
                write_json(index_path, task_index)
                update_top_index(root, task_path.name, "error")
                print(message, file=sys.stderr)
                args.failed = True
                return False
        else:
            ac_results = write_ac_results(task_path, phase_number, attempt, command_results)
            missing_outputs = verify_required_outputs(task_path, required_outputs)
            if missing_outputs:
                message = "Missing required outputs: " + ", ".join(missing_outputs)
                write_last_error(task_path, phase_number, message)
                write_repair_packet(
                    task_path,
                    phase_number,
                    build_repair_packet(
                        task_path,
                        phase_number,
                        phase,
                        attempt,
                        "required_outputs",
                        message,
                        retryable=attempt < max_attempts,
                        contract=contract,
                        command_results=command_results,
                        required_outputs=required_outputs,
                        missing_outputs=missing_outputs,
                    ),
                )
                if attempt < max_attempts:
                    prompt = build_prompt(root, task_path, read_json(index_path), phase)
                    continue
                task_index = read_json(index_path)
                set_phase_status(task_index, phase_number, "error", failed_at=now(), error_message=message)
                write_json(index_path, task_index)
                update_top_index(root, task_path.name, "error")
                print(message, file=sys.stderr)
                args.failed = True
                return False

            final_snapshot = worktree_snapshot(root)
            changed_files = phase_changed_paths(task_path, phase_start_snapshot, final_snapshot)
            evidence = build_evidence(
                phase_number,
                attempt,
                changed_files,
                command_results,
                required_outputs,
                task_path,
            )
            gate = build_gate(task_path, phase_number, contract, changed_files, command_results, required_outputs)
            reconciliation = write_runtime_review_artifacts(task_path, phase_number, contract, evidence, gate)
            if gate.get("status") != "passed":
                reasons = list(gate.get("blocking_reasons") or [])
                message = "Phase gate failed: " + "; ".join(reasons)
                write_last_error(task_path, phase_number, message)
                write_repair_packet(
                    task_path,
                    phase_number,
                    build_repair_packet(
                        task_path,
                        phase_number,
                        phase,
                        attempt,
                        "gate",
                        message,
                        retryable=attempt < max_attempts,
                        contract=contract,
                        command_results=command_results,
                        required_outputs=required_outputs,
                        changed_files=changed_files,
                        gate=gate,
                        reconciliation=reconciliation,
                    ),
                )
                if attempt < max_attempts:
                    prompt = build_prompt(root, task_path, read_json(index_path), phase)
                    continue
                task_index = read_json(index_path)
                set_phase_status(task_index, phase_number, "error", failed_at=now(), error_message=message)
                write_json(index_path, task_index)
                update_top_index(root, task_path.name, "error")
                print(message, file=sys.stderr)
                args.failed = True
                return False

            write_phase_result(
                task_path=task_path,
                phase_number=phase_number,
                attempt=attempt,
                codex_exit_code=returncode,
                changed_files=changed_files,
                command_results=command_results,
                required_outputs=required_outputs,
                prompt_path=prompt_path,
                output_path=output_path,
                stderr_path=stderr_path,
                ac_results=ac_results,
            )

            task_index = read_json(index_path)
            set_phase_status(
                task_index,
                phase_number,
                "completed",
                completed_at=now(),
                error_message=None,
            )
            write_json(index_path, task_index)
            if phase_number == 0:
                generate_docs_diff(root, task_path, task_index.get("baseline"))
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
    parser.add_argument(
        "--codex-idle-timeout",
        type=non_negative_int,
        default=300,
        help="Fail codex exec after this many seconds with no stdout/stderr/stdin or watched file activity. Use 0 to disable.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only build the next prompt.")
    parser.add_argument("--one", action="store_true", help="Run only one pending phase.")
    parser.add_argument(
        "--from",
        dest="from_phase",
        type=non_negative_int,
        help="Reset terminal phases from this phase number before running.",
    )
    parser.add_argument("--evaluate", action="store_true", help="Run fresh evaluation after all phases complete.")
    parser.add_argument("--eval-command", action="append", default=[], help="Evaluation command.")
    parser.add_argument("--full-auto", action="store_true", help="Pass --full-auto to codex exec.")
    parser.add_argument(
        "--yolo",
        action="store_true",
        help="Pass --dangerously-bypass-approvals-and-sandbox to codex exec.",
    )
    args = parser.parse_args()
    args.failed = False

    root = Path(args.root).resolve()
    install_errors = harness_install_errors(root)
    if install_errors:
        print("[ERROR] Invalid codex-harness installation:", file=sys.stderr)
        for error in install_errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    task_path = resolve_task_path(root, args.task)
    try:
        lock_path = acquire_runner_lock(task_path, args.dry_run)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        task_index_override = apply_phase_reset(root, task_path, args.from_phase, args.dry_run)

        while True:
            progressed = execute_phase(root, task_path, args, task_index_override)
            task_index_override = None
            if args.dry_run or args.one or not progressed:
                break

        task_index = read_json(task_path / "index.json")
        if not args.dry_run and all(phase.get("status") == "completed" for phase in task_index.get("phases", [])):
            if verify_task(root, task_path) != 0:
                update_top_index(root, task_path.name, "error")
                args.failed = True
                return 1
            update_top_index(root, task_path.name, "completed")
            if args.evaluate:
                eval_returncode = run_evaluation(root, task_path, args)
                if eval_returncode != 0:
                    args.failed = True
                elif verify_task(root, task_path, require_evaluation=True) != 0:
                    args.failed = True
        return 1 if args.failed else 0
    finally:
        release_runner_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
