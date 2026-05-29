#!/usr/bin/env python3
"""Run harness task phases with runner-owned status transitions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

HARNESS_VERSION = "0.1.5"

if __name__ == "__main__":
    try:
        from install_preflight import validate_entrypoint_install_or_exit
    except Exception as exc:  # noqa: BLE001 - entrypoint preflight must fail closed before runtime imports.
        print(f"[ERROR] codex-harness install preflight is unavailable: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    validate_entrypoint_install_or_exit(sys.argv[1:], HARNESS_VERSION)

from codex_exec import (
    CODEX_CLEANUP_FAILED_EXIT_CODE,
    CODEX_IDLE_EXIT_CODE,
    CODEX_MAX_RUNTIME_EXIT_CODE,
    CODEX_STARTUP_EXIT_CODE,
    add_output_schema,
    run_codex_exec,
)
from artifact_io import atomic_write_json, atomic_write_text, open_append_text
from decision_registry import (
    load_decision_registry,
    validate_decision_files,
    validate_dependency_changes,
    validate_open_decisions,
)
from phase_contract import (
    IMPLEMENTATION_QUALITY_DOC,
    checklist_markdown,
    contract_acceptance_commands,
    contract_allowed_paths,
    contract_required_outputs,
    contract_required_repo_outputs,
    handoff_block_reasons,
    handoff_change_trace_errors,
    path_allowed,
    parse_phase_contract,
    scope_violations,
    validate_phase_contract,
)
from phase_semantics import analyze_phase
from command_policy import run_command
from env_policy import sanitized_env
from process_runner import PROCESS_TIMEOUT_EXIT_CODE, ProcessResult, run_process
from file_lock import (
    LockHandle,
    acquire_lock,
    acquire_repo_execution_lock as acquire_shared_repo_execution_lock,
    acquire_task_runtime_lock,
    probe_lock_state,
    release_lock,
    remove_stale_lock,
    repo_execution_lock_path,
    task_runtime_lock_path,
)
from harness_attestation import attestation_fingerprint, harness_attestation
from install_preflight import install_validation_errors
from obligation_ledger import build_phase_obligation_assertion_outcomes, design_obligations_by_id
from policy_pack import policy_pack_metadata
from policy_lineage import (
    allowed_policy_fingerprints,
    normalize_policy_pack_lineage_entries,
    policy_pack_fingerprint,
    stable_json_sha256,
    validate_current_policy_lineage,
)
from scope_policy import required_output_repo_paths, traceable_changed_files
from task_paths import resolve_task_path
from redaction import redact_text
from runtime_protocol import (
    TERMINAL_ATTEMPT_RECORD_TYPES,
    artifact_ref,
    attempt_manifest_semantic_errors,
    file_sha256,
    phase_attempt_manifest_path,
    read_attempt_manifest_records_with_errors,
    resolve_task_artifact_path,
    runtime_artifact_ref_errors,
    task_relative,
)
from runtime_integrity import (
    build_runtime_integrity_report,
    restore_attempt_manifest_content,
    runtime_artifact_integrity_changes,
    runtime_artifact_stable_snapshot,
    runtime_artifact_snapshot,
    write_runtime_integrity_report,
)


TEXT_EXTENSIONS = {".md", ".txt", ".json"}
RUNNABLE_PHASE_STATUSES = {"pending", "running"}
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_AC_TIMEOUT = 600
DEFAULT_RUNTIME_SETTLE_SECONDS = 0.05
DEFAULT_RUNTIME_SETTLE_POLL_SECONDS = 0.05
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
SCRIPT_DIR = Path(__file__).resolve().parent
RUNTIME_HARNESS_ATTESTATION = harness_attestation()
INSTALL_PREFLIGHT_LOCK_EXIT_CODE = 125
MANDATORY_STATIC_FILES = [
    "original-prompt.md",
    "product.md",
    "decisions.md",
    "decisions.json",
    "open-decisions.json",
    "architecture.json",
    "dependency-policy.json",
    "context-gathering-budget.json",
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
    re.compile(r"Replace this", re.IGNORECASE),
    re.compile(r"Replace with", re.IGNORECASE),
]


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    atomic_write_json(path, data)


def write_prompt_artifact(path: Path, prompt: str) -> None:
    atomic_write_text(path, redact_text(prompt))


def append_progress(task_path: Path, message: str) -> None:
    path = task_path / "context-pack" / "runtime" / "progress.md"
    with open_append_text(path) as handle:
        handle.write(f"- `{now()}` {message}\n")


def harness_install_errors(root: Path) -> list[str]:
    return install_validation_errors(root, HARNESS_VERSION)


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def runtime_settle_seconds(args: argparse.Namespace) -> float:
    configured = getattr(args, "runtime_settle_seconds", None)
    if configured is not None:
        return float(configured)
    if getattr(args, "strict_current_harness", False):
        return DEFAULT_RUNTIME_SETTLE_SECONDS
    return 0.0


def runtime_settle_poll_seconds(args: argparse.Namespace) -> float:
    return float(getattr(args, "runtime_settle_poll_seconds", DEFAULT_RUNTIME_SETTLE_POLL_SECONDS))


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def apply_inherited_yolo(args: argparse.Namespace) -> None:
    args.yolo_inherited = False
    if (
        not getattr(args, "yolo", False)
        and getattr(args, "allow_inherited_yolo", False)
        and env_flag("CODEX_HARNESS_CHILD_CODEX_YOLO")
    ):
        args.yolo = True
        args.yolo_inherited = True


def nested_codex_preflight_errors(args: argparse.Namespace) -> list[str]:
    if getattr(args, "dry_run", False):
        return []
    if getattr(args, "yolo", False):
        return []
    if not env_flag("CODEX_HARNESS_SESSION"):
        return []
    return [
        "run-phases.py is running inside a launcher Codex session, but phase child "
        "codex exec is not configured with --yolo. Re-run the launcher with --yolo "
        "or pass --allow-inherited-yolo with CODEX_HARNESS_CHILD_CODEX_YOLO=1 only "
        "when that privilege escalation was explicitly approved."
    ]


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


def package_manager_install_command(root: Path) -> list[str] | None:
    package_json = root / "package.json"
    if not package_json.exists():
        return None
    try:
        package_data = json.loads(package_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        package_data = {}
    package_manager = package_data.get("packageManager") if isinstance(package_data, dict) else ""
    if (root / "pnpm-workspace.yaml").exists() or str(package_manager).startswith("pnpm@"):
        return ["pnpm", "install", "--frozen-lockfile", "--ignore-scripts"]
    if (root / "yarn.lock").exists() or str(package_manager).startswith("yarn@"):
        if not str(package_manager).startswith("yarn@"):
            return ["yarn", "install", "--frozen-lockfile", "--ignore-scripts"]
        yarn_version = str(package_manager).split("@", 1)[1]
        if yarn_version.startswith("1."):
            return ["yarn", "install", "--frozen-lockfile", "--ignore-scripts"]
        return ["yarn", "install", "--immutable", "--mode=skip-builds"]
    if (root / "package-lock.json").exists() or (root / "npm-shrinkwrap.json").exists():
        return ["npm", "ci", "--ignore-scripts"]
    return None


def install_preflight_needed(root: Path) -> bool:
    if not (root / "package.json").exists():
        return False
    return package_manager_install_command(root) is not None


def install_preflight_path(task_path: Path) -> Path:
    return task_path / "context-pack" / "runtime" / "install-preflight.json"


def install_preflight_lock_path(root: Path) -> Path:
    return root / ".codex" / "harness" / "install-preflight.lock"


def top_index_lock_path(root: Path) -> Path:
    return root / ".codex" / "harness" / "tasks-index.lock"


def run_install_preflight(root: Path, task_path: Path, args: argparse.Namespace) -> list[str]:
    if getattr(args, "skip_install", False) or getattr(args, "install_preflight_done", False):
        return []
    args.install_preflight_done = True
    if not install_preflight_needed(root):
        return []
    command = package_manager_install_command(root)
    if command is None:
        return []
    started_at = now()
    lock_handle: LockHandle | None = None
    install_path = install_preflight_path(task_path)
    try:
        lock_handle = acquire_lock(install_preflight_lock_path(root))
        result = run_process(
            command,
            cwd=root,
            env=sanitized_env(allow_harness_policy_controls=True),
            timeout=getattr(args, "install_timeout", 600),
        )
        exit_code = result.returncode
        output = redact_text(result.stdout + result.stderr).strip()
        if result.timed_out:
            output = (output + f"\nTimed out after {getattr(args, 'install_timeout', 600)} seconds.").strip()
            if not result.cleanup_confirmed:
                output = (output + "\nProcess cleanup after timeout could not be confirmed.").strip()
        completed_at = now()
        lock_error = None
    except OSError as exc:
        exit_code = 127
        output = redact_text(
            f"Failed to start install preflight command {' '.join(command)}: {exc}. "
            "Ensure the package manager is installed and available on PATH."
        )
        completed_at = now()
        lock_error = None
    except RuntimeError as exc:
        exit_code = INSTALL_PREFLIGHT_LOCK_EXIT_CODE
        output = f"{exc}. Retry this phase after the active install preflight finishes."
        completed_at = now()
        lock_error = str(exc)
    finally:
        release_lock(lock_handle)
    payload = {
        "command": command,
        "started_at": started_at,
        "completed_at": completed_at,
        "exit_code": exit_code,
        "env_sanitized": True,
        "output_redacted": True,
        "install_timeout_seconds": getattr(args, "install_timeout", 600),
        "policy_pack": runtime_policy_pack(),
        "output_tail": truncate_text(output, 6_000),
    }
    if lock_error is not None:
        payload["lock_error"] = lock_error
    install_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(install_path, payload)
    if exit_code != 0:
        return [
            "Install preflight failed: "
            f"{' '.join(command)} exited {exit_code}. "
            f"See {install_preflight_path(task_path).relative_to(root)}"
        ]
    return []


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


def path_is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def display_repo_path(root: Path, path: Path) -> str:
    root = root.resolve()
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def safe_prompt_input_text(root: Path, path: Path, label: str) -> str:
    root = root.resolve()
    display_path = display_repo_path(root, path)
    if path.is_symlink():
        raise RuntimeError(f"Unsafe {label} symlink: {display_path}")
    resolved = path.resolve()
    if not path_is_relative_to(resolved, root):
        raise RuntimeError(f"Unsafe {label} outside repository: {display_path}")
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"Missing {label}: {display_path}")
    return path.read_text(encoding="utf-8", errors="replace")


def collect_files(root: Path, paths: Iterable[Path], max_bytes: int) -> str:
    chunks: list[str] = []
    for path in paths:
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink():
            safe_prompt_input_text(root, path, "context file")
        if not path.is_file():
            continue
        if path.suffix not in TEXT_EXTENSIONS:
            continue
        data = safe_prompt_input_text(root, path, "context file")
        rel = path.resolve().relative_to(root.resolve())
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


def phase_attempt_result_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-result-attempt{attempt}.json"


def phase_contract_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-contract.json"


def phase_checklist_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-checklist.md"


def phase_attempt_prompt_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-prompt-attempt{attempt}.md"


def phase_attempt_contract_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-contract-attempt{attempt}.json"


def phase_attempt_checklist_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-checklist-attempt{attempt}.md"


def phase_evidence_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-evidence.json"


def phase_attempt_evidence_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-evidence-attempt{attempt}.json"


def phase_reconciliation_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-reconciliation.json"


def phase_attempt_reconciliation_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-reconciliation-attempt{attempt}.json"


def phase_reconciliation_summary_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-reconciliation.md"


def phase_attempt_reconciliation_summary_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-reconciliation-attempt{attempt}.md"


def phase_gate_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-gate.json"


def phase_attempt_gate_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-gate-attempt{attempt}.json"


def phase_attempt_runtime_integrity_report_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-runtime-integrity-attempt{attempt}.json"


def phase_quality_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-quality.json"


def phase_attempt_quality_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-quality-attempt{attempt}.json"


def phase_repair_packet_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-repair-packet.json"


def phase_attempt_repair_packet_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-repair-packet-attempt{attempt}.json"


def phase_repair_packet_summary_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-repair-packet.md"


def phase_attempt_repair_packet_summary_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-repair-packet-attempt{attempt}.md"


def runner_lock_path(task_path: Path) -> Path:
    return task_runtime_lock_path(task_path)


def phase_handoff_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "handoffs" / f"phase{phase_number}.md"


def phase_attempt_handoff_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-handoff-attempt{attempt}.md"


def ac_results_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-ac-attempt{attempt}.json"


def phase_attempt_commit_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-attempt{attempt}-commit.json"


def phase_result_artifacts_exist(task_path: Path, phase_number: int) -> bool:
    runtime_dir = task_path / "context-pack" / "runtime"
    return phase_result_path(task_path, phase_number).exists() or any(
        runtime_dir.glob(f"phase{phase_number}-result-attempt*.json")
    )


def phase_reset_marker_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-reset-marker.json"


def phase_baseline_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-baseline.json"


def phase_reset_boundary(task_path: Path, phase_number: int) -> tuple[int, str, bool]:
    runtime_dir = task_path / "context-pack" / "runtime"
    best_generation = 0
    best_reset_at = ""
    best_is_own_marker = False
    best_has_generation = False
    for path in runtime_dir.glob("phase*-reset-marker.json"):
        try:
            marker = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        marker_phase = marker.get("phase")
        from_phase = marker.get("from_phase")
        if not isinstance(marker_phase, int):
            continue
        if not isinstance(from_phase, int):
            from_phase = marker_phase
        if marker_phase > phase_number:
            continue
        if marker_phase != phase_number and from_phase > phase_number:
            continue
        reset_at = str(marker.get("reset_at") or "")
        if reset_at < best_reset_at:
            continue
        is_own_marker = marker_phase == phase_number
        if reset_at == best_reset_at and best_is_own_marker and not is_own_marker:
            continue
        generation = marker.get("reset_generation")
        marker_has_generation = isinstance(generation, int) and generation >= 0
        best_generation = (
            generation if is_own_marker and marker_has_generation else 0
        )
        best_has_generation = marker_has_generation
        best_is_own_marker = is_own_marker
        best_reset_at = reset_at
    return best_generation, best_reset_at, best_has_generation


def phase_reset_state(task_path: Path, phase_number: int) -> tuple[int, str]:
    reset_generation, reset_at, _has_generation = phase_reset_boundary(task_path, phase_number)
    return reset_generation, reset_at


def phase_own_reset_generation(task_path: Path, phase_number: int) -> int:
    try:
        marker = read_json(phase_reset_marker_path(task_path, phase_number))
    except (OSError, json.JSONDecodeError):
        return 0
    generation = marker.get("reset_generation")
    return generation if isinstance(generation, int) and generation >= 0 else 0


def phase_has_own_reset_marker_at(task_path: Path, phase_number: int, reset_at: str) -> bool:
    try:
        marker = read_json(phase_reset_marker_path(task_path, phase_number))
    except (OSError, json.JSONDecodeError):
        return False
    return marker.get("phase") == phase_number and str(marker.get("reset_at") or "") == reset_at


def phase_obligation_closure_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-obligation-closure-attempt{attempt}.json"


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
    materialize_runtime_artifacts: bool = True,
    contract_path: Path | None = None,
    checklist_path: Path | None = None,
) -> str:
    phase_number = int(phase["phase"])
    phase_path = phase_file(task_path, phase_number)
    try:
        phase_markdown = safe_prompt_input_text(root, phase_path, "phase file")
    except RuntimeError as exc:
        errors.append(str(exc))
        return errors
    if materialize_runtime_artifacts:
        contract_data = materialize_phase_contract_bundle(
            task_path,
            phase_number,
            phase_markdown,
            contract_path=contract_path,
            checklist_path=checklist_path,
        )
    else:
        contract_data = phase_contract_from_markdown(phase_markdown)

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
    checklist_context = checklist_markdown(contract_data)
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
- Required repo outputs exist when the contract lists them.
- The phase handoff does not report blocked, partial, skipped, or workaround status.
- The phase handoff maps each changed repository file to a Contract instruction id.
- Changed files stay within `scope.allowed_paths`.

## Hard Invariants

- Implement only this phase.
- Read the included context before editing.
- Follow `docs/harness/implementation-quality.md` when it is present in the included context.
- Follow the approved implementation design review or waiver when it is present in the included context.
- Follow only approved `decision_refs` and `architecture_refs`.
- Do not introduce new dependencies unless `dependency_policy` explicitly allows them.
- If the phase needs an unapproved architecture, dependency, data model, module boundary, layer boundary, public interface, API contract, DB/storage schema, state flow, lifecycle, transaction boundary, or user-visible behavior decision, stop blocked and explain the missing decision in the handoff.
- Do not update any `tasks/*/index.json` file.
- Do not mark the phase completed.
- Do not decide the next phase.
- Do not spawn subagents for implementation.
- Do not edit runner-owned runtime proof files.

## Output Contract

- Write `tasks/{task_path.name}/context-pack/handoffs/phase{phase_number}.md`.
- Include a `## Change Trace` section in the handoff. Map each changed repository file, except required task outputs, to one or more Contract instruction ids. Example line: - `path/to/file`: `P0-001`.
- Run useful local checks when possible.
- If you are blocked, write that honestly in the handoff. The runner will fail the phase instead of treating a blocked handoff as success.
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
The runner will snapshot the handoff and generate canonical attempt-scoped runtime proof plus latest aliases.
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


def phase_contract_from_markdown(phase_markdown: str) -> dict:
    contract_data, contract_errors = parse_phase_contract(phase_markdown)
    if contract_errors or contract_data is None:
        raise ValueError("; ".join(contract_errors))
    return contract_data


def materialize_phase_contract(task_path: Path, phase_number: int, phase_markdown: str) -> dict:
    return materialize_phase_contract_bundle(task_path, phase_number, phase_markdown)


def materialize_phase_contract_bundle(
    task_path: Path,
    phase_number: int,
    phase_markdown: str,
    *,
    contract_path: Path | None = None,
    checklist_path: Path | None = None,
) -> dict:
    contract_data = phase_contract_from_markdown(phase_markdown)
    contract_target = contract_path or phase_contract_path(task_path, phase_number)
    checklist_target = checklist_path or phase_checklist_path(task_path, phase_number)
    contract_target.parent.mkdir(parents=True, exist_ok=True)
    write_json(contract_target, contract_data)
    atomic_write_text(
        checklist_target,
        checklist_markdown(contract_data),
    )
    phase_contract_alias = phase_contract_path(task_path, phase_number)
    phase_checklist_alias = phase_checklist_path(task_path, phase_number)
    if contract_target != phase_contract_alias:
        phase_contract_alias.parent.mkdir(parents=True, exist_ok=True)
        write_json(phase_contract_alias, contract_data)
    if checklist_target != phase_checklist_alias:
        atomic_write_text(phase_checklist_alias, checklist_markdown(contract_data))
    return contract_data


def runtime_phase_contract(task_path: Path, phase_number: int, attempt: int | None = None) -> dict:
    path = (
        phase_attempt_contract_path(task_path, phase_number, attempt)
        if isinstance(attempt, int) and attempt > 0
        else phase_contract_path(task_path, phase_number)
    )
    if not path.exists():
        raise FileNotFoundError(f"Missing runtime phase contract: {path}")
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"Runtime phase contract must be a JSON object: {path}")
    return data


def verify_runtime_contract_unchanged(
    task_path: Path,
    phase_number: int,
    attempt: int,
    original_contract: dict,
) -> list[str]:
    try:
        attempt_contract = runtime_phase_contract(task_path, phase_number, attempt)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        return [f"Runtime attempt contract missing or invalid after Codex execution: {exc}"]
    if phase_contract_hash(attempt_contract) != phase_contract_hash(original_contract):
        return ["Runtime attempt contract changed during Codex execution."]
    return []


def verify_phase_contract_unchanged(task_path: Path, phase_number: int, original_contract: dict) -> list[str]:
    current_markdown = phase_file(task_path, phase_number).read_text(encoding="utf-8")
    current_contract, errors = parse_phase_contract(current_markdown)
    if errors or current_contract is None:
        return ["Phase contract block missing or invalid after Codex execution: " + "; ".join(errors)]
    if phase_contract_hash(current_contract) != phase_contract_hash(original_contract):
        return ["Phase contract changed during Codex execution."]
    return []


def runtime_integrity_ignored_contract_paths(task_path: Path, phase_number: int, attempt: int) -> list[str]:
    # Contract files have dedicated semantic checks so their failure reason stays precise.
    return [
        task_relative(phase_contract_path(task_path, phase_number), task_path),
        task_relative(phase_attempt_contract_path(task_path, phase_number, attempt), task_path),
    ]


def write_attempt_runtime_integrity_report(
    task_path: Path,
    phase_number: int,
    attempt: int,
    *,
    failure_window: str,
    before: dict[str, str],
    after: dict[str, str],
    allowed_paths: Iterable[str] = (),
    ignored_paths: Iterable[str] = (),
    settle_seconds: float = 0.0,
    poll_seconds: float = 0.0,
) -> Path:
    report_path = phase_attempt_runtime_integrity_report_path(task_path, phase_number, attempt)
    write_runtime_integrity_report(
        report_path,
        build_runtime_integrity_report(
            phase_number=phase_number,
            attempt=attempt,
            runner_version=HARNESS_VERSION,
            created_at=now(),
            failure_window=failure_window,
            before=before,
            after=after,
            allowed_paths=allowed_paths,
            ignored_paths=ignored_paths,
            settle_seconds=settle_seconds,
            poll_seconds=poll_seconds,
        ),
    )
    return report_path


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


def phase_required_repo_outputs(phase_markdown: str) -> list[str]:
    contract, _ = parse_phase_contract(phase_markdown)
    if contract is None:
        return []
    return contract_required_repo_outputs(contract)


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


def contract_repo_outputs(contract: dict) -> list[str]:
    return contract_required_repo_outputs(contract)


def phase_contract_hash(contract: dict) -> str:
    payload = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def has_placeholder(text: str) -> bool:
    return any(pattern.search(text) for pattern in PLACEHOLDER_PATTERNS)


def require_real_file(root: Path, path: Path, label: str) -> list[str]:
    if not path.exists():
        return [f"Missing {label}: {display_repo_path(root, path)}"]
    if path.is_symlink():
        return [f"Unsafe {label} symlink: {display_repo_path(root, path)}"]
    if not path_is_relative_to(path.resolve(), root.resolve()):
        return [f"Unsafe {label} outside repository: {display_repo_path(root, path)}"]
    if not path.is_file():
        return [f"Not a file: {display_repo_path(root, path)}"]

    errors = []
    text = safe_prompt_input_text(root, path, label).strip()
    if not text:
        errors.append(f"Empty {label}: {display_repo_path(root, path)}")
    if has_placeholder(text):
        errors.append(f"Placeholder remains in {label}: {display_repo_path(root, path)}")
    return errors


def preflight_phase(root: Path, task_path: Path, task_index: dict, phase: dict) -> list[str]:
    errors = []
    phase_number = int(phase["phase"])
    decision_registry, registry_errors = load_decision_registry(task_path)
    errors.extend(registry_errors)
    if not registry_errors:
        errors.extend(validate_decision_files(decision_registry))
        errors.extend(validate_open_decisions(decision_registry))
    phase_path = phase_file(task_path, phase_number)
    phase_markdown = safe_prompt_input_text(root, phase_path, "phase file")
    contract, contract_errors = validate_phase_contract(
        root,
        task_path,
        phase_number,
        phase.get("name"),
        phase_markdown,
        require_previous_outputs=True,
        decision_registry=decision_registry if not registry_errors else None,
    )
    errors.extend(contract_errors)

    if has_placeholder(phase_markdown):
        errors.append(f"Placeholder remains in phase file: {phase_path.relative_to(root)}")

    if not phase_ac_commands(phase, phase_markdown):
        errors.append(f"Missing AC commands for phase {phase_number}.")

    if not phase_required_outputs(phase, phase_markdown):
        errors.append(f"Missing required_outputs for phase {phase_number}.")
    if contract is not None:
        if analyze_phase(contract, phase.get("name")).writes_product_code:
            if not contract_required_repo_outputs(contract):
                errors.append(
                    f"Missing required_repo_outputs for implementation phase {phase_number}."
                )
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
    common_docs = common_doc_files(root, task_index)
    if root / IMPLEMENTATION_QUALITY_DOC not in common_docs:
        errors.append(f"Task index common_docs must include {IMPLEMENTATION_QUALITY_DOC}")
    for path in common_docs:
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
        else:
            errors.extend(require_real_file(root, handoff, "previous handoff"))

    return errors


def run_shell(command: str, cwd: Path, timeout: int) -> tuple[int, str, bool]:
    code, output, timed_out, _argv = run_command(command, cwd, timeout)
    return code, output, timed_out


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


def runtime_policy_pack() -> dict[str, str]:
    return policy_pack_metadata()


def current_policy_lineage_errors(task_path: Path) -> list[str]:
    approval_path = task_path / "context-pack" / "static" / "design-approval.json"
    if not approval_path.exists():
        return []
    try:
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid design approval JSON before phase execution: {exc}"]
    return validate_current_policy_lineage(
        approval,
        policy_pack_fingerprint(runtime_policy_pack()),
        action_label="phase execution",
    )


def approved_policy_pack_lineage(task_path: Path) -> tuple[list[dict[str, str]], list[str]]:
    approval_path = task_path / "context-pack" / "static" / "design-approval.json"
    if not approval_path.exists():
        return [], []
    try:
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [], [f"Invalid design approval JSON: {exc}"]
    active = policy_pack_fingerprint(approval.get("active_policy_pack"))
    entries, errors = normalize_policy_pack_lineage_entries(
        approval.get("approved_policy_packs"),
        "Design approval approved_policy_packs",
        active,
    )
    return allowed_policy_fingerprints(entries), errors


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


def ignored_gate_paths(task_path: Path, required_outputs: list[str]) -> list[str]:
    return [
        *required_output_repo_paths(task_path, required_outputs),
    ]


def attempt_scope_violations(
    contract: dict | None,
    task_path: Path,
    changed_files: list[str],
    required_outputs: list[str],
) -> list[str]:
    if contract is None:
        return []
    return scope_violations(
        changed_files,
        contract_allowed_paths(contract),
        ignored_gate_paths(task_path, required_outputs),
    )


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

        apply_reset_projection_to_phase(phase, reset_at)
        reset_results.append(
            {
                "phase": phase_number,
                "name": phase.get("name"),
                "from_status": old_status,
                "to_status": "pending",
            }
        )
    return reset_results


def apply_reset_projection_to_phase(phase: dict[str, object], reset_at: str) -> None:
    phase["status"] = "pending"
    phase["reset_at"] = reset_at
    phase["attempts"] = 0
    for field in ["started_at", "completed_at", "failed_at", "error_message"]:
        phase.pop(field, None)


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
    lock_handle = acquire_lock(top_index_lock_path(root), wait_timeout_seconds=30, boundary=root)
    try:
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
    finally:
        release_lock(lock_handle)


def write_last_error(task_path: Path, phase_number: int, message: str) -> None:
    runtime_dir = task_path / "context-pack" / "runtime"
    atomic_write_text(
        runtime_dir / f"phase{phase_number}-last-error.md",
        f"# Phase {phase_number} Last Error\n\n{message.rstrip()}\n",
    )


def install_preflight_failure_retryable(task_path: Path) -> bool:
    try:
        payload = read_json(install_preflight_path(task_path))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    return payload.get("exit_code") == INSTALL_PREFLIGHT_LOCK_EXIT_CODE


def acquire_runner_lock(task_path: Path, dry_run: bool) -> LockHandle | None:
    if dry_run:
        return None
    try:
        return acquire_task_runtime_lock(task_path, "run-phases")
    except RuntimeError as exc:
        raise RuntimeError(f"Another run-phases process is active: {runner_lock_path(task_path)}") from exc


def release_runner_lock(handle: LockHandle | None) -> None:
    release_lock(handle)


def acquire_repo_execution_lock(root: Path, task_path: Path, args: argparse.Namespace) -> LockHandle | None:
    if getattr(args, "dry_run", False):
        return None
    try:
        return acquire_shared_repo_execution_lock(
            root,
            "run-phases",
            task_path=task_path,
            wait_timeout_seconds=getattr(args, "repo_lock_timeout", 0),
        )
    except RuntimeError as exc:
        raise RuntimeError(
            f"Another codex-harness repo execution is active: {repo_execution_lock_path(root)}"
        ) from exc


def release_repo_execution_lock(handle: LockHandle | None) -> None:
    release_lock(handle)


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
    max_runtime: int = 1800,
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
        max_runtime=max_runtime,
        activity_paths=phase_activity_paths(root, task_path, phase_number),
    )


def verify_required_outputs(task_path: Path, required_outputs: list[str]) -> list[str]:
    missing = []
    for raw_path in required_outputs:
        target = task_path / raw_path
        if not target.exists():
            missing.append(raw_path)
    return missing


def verify_required_repo_outputs(root: Path, required_outputs: list[str]) -> list[str]:
    missing = []
    for raw_path in required_outputs:
        target = root / raw_path
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


def required_repo_output_results(root: Path, required_outputs: list[str]) -> list[dict[str, object]]:
    return [
        {
            "path": raw_path,
            "exists": (root / raw_path).exists(),
        }
        for raw_path in required_outputs
    ]


def required_repo_output_content_results(root: Path, required_outputs: list[str]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for raw_path in required_outputs:
        path = root / raw_path
        exists = path.exists() and path.is_file()
        item: dict[str, object] = {"path": raw_path, "exists": exists}
        if exists:
            item["sha256"] = file_sha256(path)
        results.append(item)
    return results


def repo_content_attestation(
    root: Path,
    changed_files: list[str],
    required_repo_outputs: list[str],
    before_repo_outputs: list[dict[str, object]] | None = None,
    before_snapshot: dict[str, str] | None = None,
    after_snapshot: dict[str, str] | None = None,
) -> dict[str, object]:
    before_snapshot = before_snapshot or {}
    after_snapshot = after_snapshot or worktree_snapshot(root)
    before_by_path = {
        str(item.get("path")): item
        for item in (before_repo_outputs or [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    changed_entries = [
        {
            "path": path,
            "before_digest": before_snapshot.get(path, "<missing>"),
            "after_digest": after_snapshot.get(path, file_digest(root / path)),
        }
        for path in sorted(changed_files)
    ]
    required_entries = []
    for raw_path in required_repo_outputs:
        before = before_by_path.get(raw_path, {"path": raw_path, "exists": False})
        after_path = root / raw_path
        after = {"path": raw_path, "exists": after_path.exists() and after_path.is_file()}
        if after["exists"]:
            after["sha256"] = file_sha256(after_path)
        required_entries.append({"path": raw_path, "before": before, "after": after})
    content: dict[str, object] = {
        "changed_files": changed_entries,
        "changed_files_digest": stable_json_sha256(changed_entries),
        "required_repo_outputs": required_entries,
        "required_repo_outputs_digest": stable_json_sha256(required_entries),
    }
    content["digest"] = stable_json_sha256(content)
    return content


def run_quality_checks(
    root: Path,
    task_path: Path,
    phase_number: int,
    changed_files: list[str],
) -> dict[str, object]:
    output_path = phase_quality_path(task_path, phase_number)
    command = [
        sys.executable,
        str(SCRIPT_DIR / "run-quality-checks.py"),
        "--root",
        str(root),
        "--task-path",
        str(task_path),
        "--phase",
        str(phase_number),
        "--contract",
        str(phase_contract_path(task_path, phase_number)),
        "--output",
        str(output_path),
    ]
    for changed_file in changed_files:
        command.extend(["--changed-file", changed_file])

    exit_code, output, _timed_out = run_shell(" ".join(shlex.quote(item) for item in command), root, 180)
    if output_path.exists():
        try:
            result = read_json(output_path)
        except (json.JSONDecodeError, OSError):
            result = {}
    else:
        result = {}
    if not isinstance(result, dict):
        result = {}
    result.setdefault("phase", phase_number)
    result.setdefault("changed_files", changed_files)
    result.setdefault("checks", [])
    result["exit_code"] = exit_code
    if output:
        result["output_tail"] = truncate_text(output, 4000)
    if exit_code != 0 and result.get("status") != "failed":
        result["status"] = "failed"
        result["blocking_reasons"] = ["Quality check command failed."]
    if not output_path.exists():
        write_json(output_path, result)
    return result


def handoff_blockers(task_path: Path, phase_number: int) -> list[str]:
    path = phase_handoff_path(task_path, phase_number)
    if not path.exists():
        return []
    return handoff_block_reasons(path.read_text(encoding="utf-8", errors="replace"))


def handoff_change_trace_blockers(
    task_path: Path,
    phase_number: int,
    contract: dict,
    changed_files: list[str],
    required_outputs: list[str],
) -> list[str]:
    path = phase_handoff_path(task_path, phase_number)
    if not path.exists():
        return []
    instruction_ids = [
        item.get("id")
        for item in contract.get("instructions") or []
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]
    return handoff_change_trace_errors(
        path.read_text(encoding="utf-8", errors="replace"),
        traceable_changed_files(task_path, changed_files, required_outputs),
        instruction_ids,
    )


COMMAND_IDENTITY_FIELDS = ("id", "command", "role", "target", "exit_code", "timed_out")


def command_result_identity(item: dict[str, object]) -> dict[str, object]:
    return {key: item.get(key) for key in COMMAND_IDENTITY_FIELDS if key in item}


def write_ac_results(
    task_path: Path,
    phase_number: int,
    attempt: int,
    command_results: list[dict[str, object]],
) -> Path:
    path = ac_results_path(task_path, phase_number, attempt)
    command_identities = [command_result_identity(item) for item in command_results]
    write_json(
        path,
        {
            "schema_version": 1,
            "runner_version": HARNESS_VERSION,
            "phase": phase_number,
            "attempt": attempt,
            "policy_pack": runtime_policy_pack(),
            "harness_attestation": RUNTIME_HARNESS_ATTESTATION,
            "commands_digest": stable_json_sha256(command_identities),
            "commands": command_results,
        },
    )
    return path


def write_phase_result(
    root: Path,
    task_path: Path,
    phase_number: int,
    attempt: int,
    codex_exit_code: int,
    changed_files: list[str],
    command_results: list[dict[str, object]],
    required_outputs: list[str],
    required_repo_outputs: list[str],
    prompt_path: Path,
    output_path: Path,
    stderr_path: Path,
    ac_results: Path,
    before_repo_outputs: list[dict[str, object]] | None = None,
    before_snapshot: dict[str, str] | None = None,
    after_snapshot: dict[str, str] | None = None,
    contract_path: Path | None = None,
    checklist_path: Path | None = None,
    quality_path: Path | None = None,
    evidence_path: Path | None = None,
    reconciliation_path: Path | None = None,
    reconciliation_summary_path: Path | None = None,
    gate_path: Path | None = None,
) -> Path:
    contract = {}
    contract_artifact_path = contract_path or phase_contract_path(task_path, phase_number)
    checklist_artifact_path = checklist_path or phase_checklist_path(task_path, phase_number)
    quality_artifact_path = quality_path or phase_quality_path(task_path, phase_number)
    evidence_artifact_path = evidence_path or phase_evidence_path(task_path, phase_number)
    reconciliation_artifact_path = reconciliation_path or phase_reconciliation_path(task_path, phase_number)
    reconciliation_summary_artifact_path = (
        reconciliation_summary_path or phase_reconciliation_summary_path(task_path, phase_number)
    )
    gate_artifact_path = gate_path or phase_gate_path(task_path, phase_number)
    try:
        contract = read_json(contract_artifact_path)
    except (OSError, json.JSONDecodeError):
        contract = {}
    commands_run = []
    for item in command_results:
        command = {
            "command": item.get("command"),
            "exit_code": item.get("exit_code"),
        }
        for key in ["id", "role", "target", "repo_scan", "output", "output_tail", "timed_out"]:
            if key in item:
                command[key] = item[key]
        commands_run.append(command)
    repo_content = repo_content_attestation(
        root,
        changed_files,
        required_repo_outputs,
        before_repo_outputs,
        before_snapshot,
        after_snapshot,
    )
    result = {
        "schema_version": 1,
        "runner_version": HARNESS_VERSION,
        "phase": phase_number,
        "status": "completed",
        "attempt": attempt,
        "reset_generation": phase_reset_state(task_path, phase_number)[0],
        "codex_exit_code": codex_exit_code,
        "changed_files": changed_files,
        "commands_run": commands_run,
        "tests_passed": all(item["exit_code"] == 0 for item in command_results),
        "required_outputs": required_output_results(task_path, required_outputs),
        "required_repo_outputs": required_repo_output_results(root, required_repo_outputs),
        "repo_content": repo_content,
        "policy_pack": runtime_policy_pack(),
        "harness_attestation": RUNTIME_HARNESS_ATTESTATION,
        "artifacts": {
            "contract": task_relative(contract_artifact_path, task_path),
            "checklist": task_relative(checklist_artifact_path, task_path),
            "prompt": task_relative(prompt_path, task_path),
            "stdout": task_relative(output_path, task_path),
            "stderr": task_relative(stderr_path, task_path),
            "ac_results": task_relative(ac_results, task_path),
            "quality": task_relative(quality_artifact_path, task_path),
            "evidence": task_relative(evidence_artifact_path, task_path),
            "reconciliation": task_relative(reconciliation_artifact_path, task_path),
            "reconciliation_summary": task_relative(reconciliation_summary_artifact_path, task_path),
            "gate": task_relative(gate_artifact_path, task_path),
        },
    }
    attempt_handoff_path = snapshot_attempt_handoff(task_path, phase_number, attempt)
    if attempt_handoff_path is not None:
        result["artifacts"]["handoff"] = task_relative(attempt_handoff_path, task_path)
    else:
        result["artifacts"]["handoff"] = task_relative(phase_handoff_path(task_path, phase_number), task_path)
    approval_path = task_path / "context-pack" / "static" / "design-approval.json"
    if approval_path.exists():
        try:
            approval = read_json(approval_path)
            if isinstance(approval.get("approved_bundle_sha256"), str):
                result["design_approval_bundle_sha256"] = approval["approved_bundle_sha256"]
        except (OSError, json.JSONDecodeError):
            pass
    if contract.get("closes_obligations"):
        design_contract_path = task_path / "context-pack" / "static" / "design-contract.json"
        try:
            design_contract = read_json(design_contract_path)
        except (OSError, json.JSONDecodeError):
            design_contract = {}
        outcomes = build_phase_obligation_assertion_outcomes(
            contract=contract,
            phase_result=result,
            obligations=design_obligations_by_id(design_contract),
        )
        commands_by_ref: dict[str, dict[str, object]] = {}
        for command in commands_run:
            if command.get("exit_code") != 0:
                continue
            for key in ["id", "command"]:
                value = command.get(key)
                if isinstance(value, str) and value:
                    commands_by_ref[value] = command
        contract_sha = file_sha256(contract_artifact_path) if contract_artifact_path.exists() else ""
        design_sha = file_sha256(design_contract_path) if design_contract_path.exists() else ""
        assertion_entries = []
        for outcome in outcomes:
            assertion = {**outcome, "attempt": attempt, "runner_version": HARNESS_VERSION}
            assertion["phase_contract_sha256"] = contract_sha
            assertion["design_contract_sha256"] = design_sha
            command_ref = assertion.get("command_ref")
            command = commands_by_ref.get(command_ref) if isinstance(command_ref, str) else None
            if command is not None:
                output = command.get("output") if isinstance(command.get("output"), str) else str(command.get("output_tail") or "")
                assertion["command_output_sha256"] = hashlib.sha256(output.encode("utf-8")).hexdigest()
            if "value" in assertion:
                assertion["value"] = "[redacted]"
            assertion_entries.append(assertion)
        ledger_path = phase_obligation_closure_path(task_path, phase_number, attempt)
        ledger = {
            "schema_version": 1,
            "phase": phase_number,
            "attempt": attempt,
            "runner_version": HARNESS_VERSION,
            "assertions": assertion_entries,
        }
        write_json(ledger_path, ledger)
        result["artifacts"]["obligation_closure"] = task_relative(ledger_path, task_path)
    previous_failed_attempt = attempt - 1
    repair_packet = (
        phase_attempt_repair_packet_path(task_path, phase_number, previous_failed_attempt)
        if previous_failed_attempt > 0
        and phase_attempt_repair_packet_path(task_path, phase_number, previous_failed_attempt).exists()
        else phase_repair_packet_path(task_path, phase_number)
    )
    repair_packet_summary = (
        phase_attempt_repair_packet_summary_path(task_path, phase_number, previous_failed_attempt)
        if previous_failed_attempt > 0
        and phase_attempt_repair_packet_summary_path(task_path, phase_number, previous_failed_attempt).exists()
        else phase_repair_packet_summary_path(task_path, phase_number)
    )
    if repair_packet.exists():
        result["artifacts"]["repair_packet"] = task_relative(repair_packet, task_path)
    if repair_packet_summary.exists():
        result["artifacts"]["repair_packet_summary"] = task_relative(repair_packet_summary, task_path)
    result_path = phase_attempt_result_path(task_path, phase_number, attempt)
    result_alias_path = phase_result_path(task_path, phase_number)
    write_json(result_path, result)
    result["artifacts"]["attempt_commit"] = task_relative(phase_attempt_commit_path(task_path, phase_number, attempt), task_path)
    write_json(result_path, result)
    write_json(result_alias_path, result)
    return result_path


def _artifact_entry(name: str, task_path: Path, raw_path: object) -> dict[str, object] | None:
    if not isinstance(raw_path, str) or not raw_path:
        return None
    path = resolve_task_artifact_path(task_path, raw_path)
    if path is None:
        return {"name": name, "path": raw_path, "exists": False}
    entry: dict[str, object] = {"name": name, "path": raw_path, "exists": path.exists()}
    if path.exists() and path.is_file():
        entry["sha256"] = file_sha256(path)
    return entry


def append_attempt_manifest_record(
    task_path: Path,
    phase_number: int,
    attempt: int,
    record_type: str,
    **fields: object,
) -> None:
    reset_generation, reset_at = phase_reset_state(task_path, phase_number)
    record = {
        "schema_version": 1,
        "artifact_kind": "phase_attempt_manifest_record",
        "record_type": record_type,
        "phase": phase_number,
        "attempt": attempt,
        "reset_generation": reset_generation,
        "reset_at": reset_at,
        "recorded_at": now(),
        "runner_version": HARNESS_VERSION,
        "policy_pack": policy_pack_fingerprint(runtime_policy_pack()),
        "harness_attestation": RUNTIME_HARNESS_ATTESTATION,
        **fields,
    }
    with open_append_text(phase_attempt_manifest_path(task_path, phase_number)) as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def read_attempt_manifest_records(task_path: Path, phase_number: int) -> list[dict[str, object]]:
    records, _errors = read_attempt_manifest_records_with_errors(task_path, phase_number)
    return records


def manifest_record_matches_current_reset(
    record: dict[str, object],
    current_reset_generation: int,
) -> bool:
    record_generation = record.get("reset_generation")
    if current_reset_generation > 0:
        return record_generation == current_reset_generation
    return not isinstance(record_generation, int) or record_generation == current_reset_generation


def attempt_terminal_manifest_record(
    task_path: Path,
    phase_number: int,
    attempt: int,
    current_reset_generation: int,
) -> dict[str, object] | None:
    terminal_record: dict[str, object] | None = None
    for record in read_attempt_manifest_records(task_path, phase_number):
        record_type = record.get("record_type")
        if (
            record.get("attempt") == attempt
            and isinstance(record_type, str)
            and record_type in TERMINAL_ATTEMPT_RECORD_TYPES
            and manifest_record_matches_current_reset(record, current_reset_generation)
        ):
            terminal_record = record
    return terminal_record


def attempt_terminal_manifest_record_type(
    task_path: Path,
    phase_number: int,
    attempt: int,
    current_reset_generation: int,
) -> str | None:
    record = attempt_terminal_manifest_record(task_path, phase_number, attempt, current_reset_generation)
    record_type = record.get("record_type") if isinstance(record, dict) else None
    return record_type if isinstance(record_type, str) else None


def latest_nonterminal_started_attempt(
    task_path: Path,
    phase_number: int,
    current_reset_generation: int,
) -> int | None:
    started_attempts: list[int] = []
    for record in read_attempt_manifest_records(task_path, phase_number):
        attempt = record.get("attempt")
        if (
            record.get("record_type") == "attempt_started"
            and isinstance(attempt, int)
            and attempt > 0
            and manifest_record_matches_current_reset(record, current_reset_generation)
        ):
            started_attempts.append(attempt)
    for attempt in sorted(started_attempts, reverse=True):
        if attempt_terminal_manifest_record_type(task_path, phase_number, attempt, current_reset_generation) is None:
            return attempt
    return None


def phase_retry_max_attempts(task_path: Path, phase_number: int) -> int:
    contract: dict | None = None
    try:
        contract = runtime_phase_contract(task_path, phase_number)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        try:
            contract = phase_contract_from_markdown(phase_file(task_path, phase_number).read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            contract = None
    args = argparse.Namespace(max_attempts=DEFAULT_MAX_ATTEMPTS, ac_timeout=DEFAULT_AC_TIMEOUT)
    max_attempts, _ = contract_validation_budget(contract, args)
    return max_attempts


def retryable_terminal_failure_recovery_errors(
    task_path: Path,
    phase_number: int,
    attempt: int,
    record: dict[str, object] | None,
) -> list[str]:
    if not isinstance(record, dict):
        return ["missing terminal manifest record"]
    if record.get("record_type") != "attempt_failed":
        return [f"terminal record is {record.get('record_type')}"]
    if record.get("attempt") != attempt:
        return ["terminal record attempt does not match phase attempt"]
    failure = record.get("failure") if isinstance(record.get("failure"), dict) else {}
    if record.get("retryable") is not True and failure.get("retryable") is not True:
        return ["terminal failure is not retryable"]
    if attempt >= phase_retry_max_attempts(task_path, phase_number):
        return ["attempt budget exhausted"]

    errors = repair_context_integrity_errors(task_path, phase_number)
    if errors:
        return errors
    packet_path = phase_repair_packet_path(task_path, phase_number)
    if not packet_path.exists():
        return ["missing phase repair packet alias"]
    try:
        packet = read_json(packet_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid phase repair packet alias: {exc}"]
    if not isinstance(packet, dict):
        return ["phase repair packet alias must be a JSON object"]
    packet_failure = packet.get("failure") if isinstance(packet.get("failure"), dict) else {}
    if packet.get("attempt") != attempt:
        return ["phase repair packet attempt does not match phase attempt"]
    if packet_failure.get("retryable") is not True:
        return ["phase repair packet is not retryable"]
    contaminating_changes = packet.get("contaminating_changes")
    if isinstance(contaminating_changes, list) and contaminating_changes:
        return ["phase repair packet has contaminating changes"]
    return []


def attempt_runtime_artifact_refs(task_path: Path, phase_number: int, attempt: int) -> list[dict[str, object]]:
    artifact_paths = [
        ("prompt", phase_attempt_prompt_path(task_path, phase_number, attempt)),
        ("contract", phase_attempt_contract_path(task_path, phase_number, attempt)),
        ("checklist", phase_attempt_checklist_path(task_path, phase_number, attempt)),
        ("stdout", task_path / "context-pack" / "runtime" / f"phase{phase_number}-output-attempt{attempt}.jsonl"),
        ("stderr", task_path / "context-pack" / "runtime" / f"phase{phase_number}-stderr-attempt{attempt}.txt"),
        ("ac_results", ac_results_path(task_path, phase_number, attempt)),
        ("quality", phase_attempt_quality_path(task_path, phase_number, attempt)),
        ("evidence", phase_attempt_evidence_path(task_path, phase_number, attempt)),
        ("gate", phase_attempt_gate_path(task_path, phase_number, attempt)),
        ("reconciliation", phase_attempt_reconciliation_path(task_path, phase_number, attempt)),
        ("reconciliation_summary", phase_attempt_reconciliation_summary_path(task_path, phase_number, attempt)),
        ("handoff", phase_attempt_handoff_path(task_path, phase_number, attempt)),
    ]
    return [artifact_ref(task_path, name, path) for name, path in artifact_paths]


def write_interrupted_attempt_repair_packet(
    task_path: Path,
    phase_number: int,
    packet: dict[str, object],
    attempt: int,
) -> None:
    snapshot_attempt_handoff(task_path, phase_number, attempt)
    observed_artifacts = attempt_runtime_artifact_refs(task_path, phase_number, attempt)
    packet = {**packet, "failed_attempt_artifacts": observed_artifacts}
    markdown = repair_packet_markdown(packet)
    write_json(phase_attempt_repair_packet_path(task_path, phase_number, attempt), packet)
    atomic_write_text(phase_attempt_repair_packet_summary_path(task_path, phase_number, attempt), markdown)
    write_json(phase_repair_packet_path(task_path, phase_number), packet)
    atomic_write_text(phase_repair_packet_summary_path(task_path, phase_number), markdown)
    append_attempt_manifest_record(
        task_path,
        phase_number,
        attempt,
        "attempt_interrupted",
        status="interrupted",
        reason="runner_recovery_without_terminal_record",
        recovery_action="manual_required",
        repair_packet=artifact_ref(
            task_path,
            "repair_packet",
            phase_attempt_repair_packet_path(task_path, phase_number, attempt),
        ),
        repair_packet_summary=artifact_ref(
            task_path,
            "repair_packet_summary",
            phase_attempt_repair_packet_summary_path(task_path, phase_number, attempt),
        ),
        observed_artifacts=observed_artifacts,
    )


def snapshot_attempt_handoff(task_path: Path, phase_number: int, attempt: int) -> Path | None:
    handoff_path = phase_handoff_path(task_path, phase_number)
    if not handoff_path.exists():
        return None
    attempt_handoff_path = phase_attempt_handoff_path(task_path, phase_number, attempt)
    atomic_write_text(attempt_handoff_path, handoff_path.read_text(encoding="utf-8"))
    return attempt_handoff_path


def write_phase_attempt_commit(task_path: Path, phase_number: int, attempt: int, result_path: Path) -> Path:
    result = read_json(result_path)
    artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), dict) else {}
    artifact_entries = [
        entry
        for name, raw_path in artifacts.items()
        if name != "attempt_commit"
        for entry in [_artifact_entry(str(name), task_path, raw_path)]
        if entry is not None
    ]
    commit = {
        "schema_version": 1,
        "runner_version": HARNESS_VERSION,
        "commit_scope": "runtime_attempt_bundle",
        "phase": phase_number,
        "attempt": attempt,
        "reset_generation": result.get("reset_generation", phase_reset_state(task_path, phase_number)[0]),
        "status": "committed",
        "policy_pack": result.get("policy_pack", runtime_policy_pack()),
        "harness_attestation": result.get("harness_attestation", RUNTIME_HARNESS_ATTESTATION),
        "design_approval_bundle_sha256": result.get("design_approval_bundle_sha256"),
        "result": {
            "path": task_relative(result_path, task_path),
            "sha256": file_sha256(result_path),
        },
        "repo_content": result.get("repo_content", {}),
        "artifacts": artifact_entries,
        "artifact_count": len(artifact_entries),
        "committed_at": now(),
    }
    path = phase_attempt_commit_path(task_path, phase_number, attempt)
    write_json(path, commit)
    return path


def write_phase_reset_marker(task_path: Path, phase_number: int, reset_at: str, from_phase: int) -> Path:
    path = phase_reset_marker_path(task_path, phase_number)
    previous_generation = phase_own_reset_generation(task_path, phase_number)
    reset_generation = previous_generation + 1
    write_json(
        path,
        {
            "schema_version": 1,
            "phase": phase_number,
            "from_phase": from_phase,
            "reset_generation": reset_generation,
            "reset_id": f"phase{phase_number}-reset{reset_generation}",
            "reset_at": reset_at,
        },
    )
    return path


def attempt_commit_artifacts_valid(
    task_path: Path,
    commit: dict[str, object],
    result: dict[str, object] | None = None,
) -> bool:
    artifacts = commit.get("artifacts") if isinstance(commit.get("artifacts"), list) else []
    if result is not None:
        result_artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), dict) else {}
        committed_names = {item.get("name") for item in artifacts if isinstance(item, dict)}
        expected_names = {
            name
            for name, raw_path in result_artifacts.items()
            if name != "attempt_commit" and isinstance(raw_path, str) and raw_path
        }
        if not expected_names.issubset(committed_names):
            return False
    for item in artifacts:
        if not isinstance(item, dict):
            return False
        raw_path = item.get("path")
        path = resolve_task_artifact_path(task_path, raw_path)
        if path is None:
            return False
        if not path.exists() or not path.is_file():
            return False
        if item.get("sha256") != file_sha256(path):
            return False
    return True


def attempt_commit_runtime_metadata_valid(
    commit: dict[str, object],
    result: dict[str, object],
    *,
    strict_current_harness: bool,
    approved_policy_fingerprints: list[dict[str, str]] | None = None,
) -> bool:
    if commit.get("schema_version") != 1:
        return False
    if commit.get("commit_scope") != "runtime_attempt_bundle":
        return False
    if commit.get("status") != "committed":
        return False
    if result.get("status") != "completed":
        return False
    if result.get("codex_exit_code") != 0 or result.get("tests_passed") is not True:
        return False

    commit_runner = commit.get("runner_version")
    result_runner = result.get("runner_version")
    if not isinstance(commit_runner, str) or not commit_runner.strip():
        return False
    if commit_runner != result_runner:
        return False
    if strict_current_harness and commit_runner != HARNESS_VERSION:
        return False

    commit_policy = policy_pack_fingerprint(commit.get("policy_pack") if isinstance(commit.get("policy_pack"), dict) else None)
    result_policy = policy_pack_fingerprint(result.get("policy_pack") if isinstance(result.get("policy_pack"), dict) else None)
    if commit_policy is None or commit_policy != result_policy:
        return False
    if approved_policy_fingerprints is not None and commit_policy not in approved_policy_fingerprints:
        return False
    if strict_current_harness:
        current_policy = policy_pack_fingerprint(runtime_policy_pack())
        if current_policy is None or commit_policy != current_policy:
            return False

    commit_attestation = attestation_fingerprint(
        commit.get("harness_attestation") if isinstance(commit.get("harness_attestation"), dict) else None
    )
    result_attestation = attestation_fingerprint(
        result.get("harness_attestation") if isinstance(result.get("harness_attestation"), dict) else None
    )
    if commit_attestation is None or commit_attestation != result_attestation:
        return False
    if strict_current_harness:
        current_attestation = attestation_fingerprint(RUNTIME_HARNESS_ATTESTATION)
        if current_attestation is None or commit_attestation != current_attestation:
            return False
    return True


def attempt_commit_can_recover_historical_projection(
    commit: dict[str, object],
    result: dict[str, object],
    approved_policy_fingerprints: list[dict[str, str]] | None = None,
) -> bool:
    return attempt_commit_runtime_metadata_valid(
        commit,
        result,
        strict_current_harness=False,
        approved_policy_fingerprints=approved_policy_fingerprints,
    )


def attempt_commit_can_support_current_execution(
    commit: dict[str, object],
    result: dict[str, object],
    approved_policy_fingerprints: list[dict[str, str]] | None = None,
) -> bool:
    return attempt_commit_runtime_metadata_valid(
        commit,
        result,
        strict_current_harness=True,
        approved_policy_fingerprints=approved_policy_fingerprints,
    )


def latest_valid_phase_attempt_commit(
    task_path: Path,
    phase_number: int,
    *,
    strict_current_harness: bool = False,
) -> dict[str, object] | None:
    lineage, lineage_errors = approved_policy_pack_lineage(task_path)
    if lineage_errors:
        return None
    approved_fingerprints = lineage or None
    reset_generation, reset_at, reset_has_generation = phase_reset_boundary(task_path, phase_number)
    commits = sorted(
        (task_path / "context-pack" / "runtime").glob(f"phase{phase_number}-attempt*-commit.json"),
        key=phase_attempt_commit_sort_key,
    )
    valid: dict[str, object] | None = None
    for path in commits:
        try:
            data = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        commit_generation = data.get("reset_generation")
        if reset_generation > 0:
            if not isinstance(commit_generation, int) or commit_generation != reset_generation:
                continue
        elif reset_at:
            if reset_has_generation:
                continue
            if isinstance(commit_generation, int):
                continue
            if str(data.get("committed_at") or "") <= reset_at:
                continue
        result_ref = data.get("result") if isinstance(data.get("result"), dict) else {}
        result_path = resolve_task_artifact_path(task_path, result_ref.get("path"))
        if result_path is None:
            continue
        if not result_path.exists() or result_ref.get("sha256") != file_sha256(result_path):
            continue
        try:
            result_data = read_json(result_path)
        except (OSError, json.JSONDecodeError):
            continue
        attempt = data.get("attempt")
        if data.get("phase") != phase_number or result_data.get("phase") != phase_number:
            continue
        if not isinstance(attempt, int) or result_data.get("attempt") != attempt:
            continue
        if "reset_generation" in data or "reset_generation" in result_data:
            if data.get("reset_generation") != result_data.get("reset_generation"):
                continue
        if strict_current_harness:
            metadata_valid = attempt_commit_can_support_current_execution(
                data,
                result_data,
                approved_policy_fingerprints=approved_fingerprints,
            )
        else:
            metadata_valid = attempt_commit_can_recover_historical_projection(
                data,
                result_data,
                approved_policy_fingerprints=approved_fingerprints,
            )
        if not metadata_valid:
            continue
        if not attempt_commit_artifacts_valid(task_path, data, result_data):
            continue
        data["_path"] = str(path)
        valid = data
    return valid


def latest_current_phase_attempt_commit(task_path: Path, phase_number: int) -> dict[str, object] | None:
    return latest_valid_phase_attempt_commit(task_path, phase_number, strict_current_harness=True)


def phase_attempt_commit_sort_key(path: Path) -> tuple[int, str]:
    match = re.search(r"-attempt(\d+)-commit\.json$", path.name)
    attempt = int(match.group(1)) if match else -1
    return attempt, path.name


def phase_attempt_commit_files_exist(task_path: Path, phase_number: int) -> bool:
    return any((task_path / "context-pack" / "runtime").glob(f"phase{phase_number}-attempt*-commit.json"))


def recovered_commit_terminalization_error(
    task_path: Path,
    phase_number: int,
    commit: dict[str, object],
    current_reset_generation: int,
) -> str | None:
    attempt = commit.get("attempt")
    if not isinstance(attempt, int) or attempt <= 0:
        return "Recovered commit has invalid attempt metadata."
    terminal_record = attempt_terminal_manifest_record(task_path, phase_number, attempt, current_reset_generation)
    if not terminal_record:
        return None
    if terminal_record.get("record_type") == "attempt_committed":
        return None
    return (
        "Valid attempt commit conflicts with existing terminal manifest record: "
        f"{terminal_record.get('record_type')}"
    )


def terminalize_recovered_attempt_commit(
    task_path: Path,
    phase_number: int,
    commit: dict[str, object],
    current_reset_generation: int,
    *,
    recovery_action: str = "recovered_from_valid_attempt_commit",
    extra_fields: dict[str, object] | None = None,
) -> None:
    attempt = commit.get("attempt")
    if not isinstance(attempt, int) or attempt <= 0:
        return
    terminal_record = attempt_terminal_manifest_record(task_path, phase_number, attempt, current_reset_generation)
    if not terminal_record:
        raw_commit_path = commit.get("_path")
        commit_path = Path(raw_commit_path) if isinstance(raw_commit_path, str) else phase_attempt_commit_path(task_path, phase_number, attempt)
        raw_result_path = commit.get("result") if isinstance(commit.get("result"), dict) else {}
        result_path = resolve_task_artifact_path(task_path, raw_result_path.get("path"))
        result_ref = {
            "name": "result",
            "path": raw_result_path.get("path"),
            "exists": bool(result_path and result_path.exists()),
        }
        if result_path is not None and result_path.exists() and result_path.is_file():
            result_ref["sha256"] = file_sha256(result_path)
        append_attempt_manifest_record(
            task_path,
            phase_number,
            attempt,
            "attempt_committed",
            status="committed",
            result=result_ref,
            attempt_commit=artifact_ref(task_path, "attempt_commit", commit_path),
            recovery_action=recovery_action,
            **(extra_fields or {}),
        )
    clear_repair_packet(task_path, phase_number)


def active_repair_alias_paths(task_path: Path, phase_number: int) -> list[str]:
    paths = [
        phase_repair_packet_path(task_path, phase_number),
        phase_repair_packet_summary_path(task_path, phase_number),
    ]
    return [task_relative(path, task_path) for path in paths if path.exists()]


def task_relative_resolved(path: Path, task_path: Path) -> str:
    return str(path.resolve().relative_to(task_path.resolve()))


def completed_phase_runtime_check(
    task_path: Path,
    phase: dict[str, object],
    *,
    apply_backfill: bool,
) -> dict[str, object] | None:
    if phase.get("status") != "completed":
        return None
    phase_number = int(phase["phase"])
    attempts = phase.get("attempts")
    if not isinstance(attempts, int) or attempts <= 0:
        return {
            "id": "phase.completed_without_attempt",
            "severity": "error",
            "phase": phase_number,
            "message": "Completed phase has no positive attempt count.",
            "operator_action": "Reset and rerun the phase so runtime proof can be generated.",
        }

    records, manifest_errors = read_attempt_manifest_records_with_errors(task_path, phase_number)
    semantic_errors = attempt_manifest_semantic_errors(task_path, phase_number, records)
    if manifest_errors or semantic_errors:
        return {
            "id": "phase.attempt_manifest.invalid",
            "severity": "error",
            "phase": phase_number,
            "attempt": attempts,
            "message": "Completed phase attempt manifest is invalid.",
            "errors": manifest_errors + semantic_errors,
            "operator_action": "Do not backfill this phase; inspect or reset from a trusted runtime state.",
        }

    reset_generation = phase_reset_state(task_path, phase_number)[0]
    active_aliases = active_repair_alias_paths(task_path, phase_number)
    if active_aliases:
        return {
            "id": "phase.repair_alias.active_after_completion",
            "severity": "error",
            "phase": phase_number,
            "attempt": attempts,
            "paths": active_aliases,
            "message": "Completed phase still has active repair aliases.",
            "operator_action": "Inspect canonical attempt artifacts before removing aliases or resetting the phase.",
        }

    terminal = attempt_terminal_manifest_record(task_path, phase_number, attempts, reset_generation)
    if terminal and terminal.get("record_type") == "attempt_committed":
        return {
            "id": "phase.attempt_manifest.committed_present",
            "severity": "info",
            "phase": phase_number,
            "attempt": attempts,
            "message": "Completed phase already has an attempt_committed manifest record.",
        }
    if terminal:
        return {
            "id": "phase.attempt_manifest.conflicting_terminal_record",
            "severity": "error",
            "phase": phase_number,
            "attempt": attempts,
            "record_type": terminal.get("record_type"),
            "message": "Completed phase has a conflicting terminal manifest record.",
            "operator_action": "Reset and rerun the phase; do not synthesize a commit over failed/interrupted proof.",
        }

    commit = latest_valid_phase_attempt_commit(task_path, phase_number)
    commit_attempt = commit.get("attempt") if commit else None
    if not commit or commit_attempt != attempts:
        reason = (
            "missing_attempt_commit"
            if not commit and not phase_attempt_commit_files_exist(task_path, phase_number)
            else "stale_attempt_commit"
        )
        return {
            "id": f"phase.attempt_commit.{reason}",
            "severity": "error",
            "phase": phase_number,
            "attempt": attempts,
            "message": "Completed phase is missing a valid matching attempt commit.",
            "operator_action": "Reset and rerun the phase from a clean approved state.",
        }

    raw_commit_path = commit.get("_path")
    commit_path = Path(raw_commit_path) if isinstance(raw_commit_path, str) else phase_attempt_commit_path(task_path, phase_number, attempts)
    result_ref = commit.get("result") if isinstance(commit.get("result"), dict) else {}
    result_path = resolve_task_artifact_path(task_path, result_ref.get("path"))
    check: dict[str, object] = {
        "id": "phase.attempt_manifest.missing_committed_record",
        "severity": "warning",
        "phase": phase_number,
        "attempt": attempts,
        "message": "Completed phase has a valid attempt commit but no attempt_committed manifest record.",
        "operator_action": "Run with --backfill-attempt-manifests to append the missing terminal ledger row.",
        "attempt_commit_path": task_relative_resolved(commit_path, task_path),
        "attempt_commit_sha256": file_sha256(commit_path) if commit_path.exists() else None,
        "result_path": task_relative_resolved(result_path, task_path) if result_path is not None else result_ref.get("path"),
        "result_sha256": file_sha256(result_path) if result_path is not None and result_path.exists() else None,
    }
    if not apply_backfill:
        return check

    terminalize_recovered_attempt_commit(
        task_path,
        phase_number,
        commit,
        reset_generation,
        recovery_action="backfilled_from_valid_attempt_commit",
        extra_fields={
            "backfill_reason": "legacy_completed_phase_missing_attempt_manifest",
            "source_commit_path": check["attempt_commit_path"],
            "source_commit_sha256": check["attempt_commit_sha256"],
            "source_result_path": check["result_path"],
            "source_result_sha256": check["result_sha256"],
        },
    )
    records_after, errors_after = read_attempt_manifest_records_with_errors(task_path, phase_number)
    errors_after.extend(attempt_manifest_semantic_errors(task_path, phase_number, records_after))
    if errors_after:
        return {
            "id": "phase.attempt_manifest.backfill_failed",
            "severity": "error",
            "phase": phase_number,
            "attempt": attempts,
            "message": "Backfill wrote a record but manifest validation still fails.",
            "errors": errors_after,
            "operator_action": "Inspect the attempt manifest and reset from a trusted state if needed.",
        }
    check["id"] = "phase.attempt_manifest.backfilled"
    check["severity"] = "info"
    check["message"] = "Appended missing attempt_committed manifest record from a valid attempt commit."
    check.pop("operator_action", None)
    return check


def runtime_projection_drift_checks(root: Path, task_path: Path) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for change in reconcile_runtime_projection(root, task_path, dry_run=True):
        to_status = change.get("to_status")
        severity = "error" if to_status == "error" else "warning"
        checks.append(
            {
                "id": "phase.runtime_projection.drift",
                "severity": severity,
                **change,
                "message": "Task index phase projection differs from runtime proof.",
                "operator_action": "Run the phase runner normally to reconcile projection before relying on task status.",
            }
        )
    return checks


def active_repo_execution_doctor_check(root: Path) -> dict[str, object] | None:
    lock_path = repo_execution_lock_path(root)
    lock_state = probe_lock_state(lock_path, boundary=root)
    if lock_state in {"missing", "stale"}:
        return None
    if lock_state == "unsafe":
        return {
            "id": "doctor.repo_execution_lock_unsafe",
            "severity": "unstable",
            "message": "The repository execution lock path is unsafe.",
            "lock_path": str(lock_path.relative_to(root)),
            "operator_action": "Inspect the lock path before trusting runtime proof diagnostics.",
        }
    return {
        "id": "doctor.repo_execution_active",
        "severity": "unstable",
        "message": "Another phase execution holds the repository execution lock.",
        "lock_path": str(lock_path.relative_to(root)),
        "operator_action": "Rerun doctor-runtime after the active phase execution finishes.",
    }


def doctor_runtime_unstable_report(
    root: Path,
    task_path: Path,
    *,
    apply_backfill: bool,
    check: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "unstable",
        "root": str(root),
        "task": str(task_path.relative_to(root)),
        "applied": apply_backfill,
        "backfill_applied": False,
        "checks": [check],
    }


def doctor_runtime_proof(
    root: Path,
    task_path: Path,
    *,
    apply_backfill: bool,
    repo_execution_lock_held: bool = False,
) -> dict[str, object]:
    if not repo_execution_lock_held:
        active_execution_check = active_repo_execution_doctor_check(root)
        if active_execution_check is not None:
            return doctor_runtime_unstable_report(
                root,
                task_path,
                apply_backfill=apply_backfill,
                check=active_execution_check,
            )
    task_index = read_json(task_path / "index.json")
    checks: list[dict[str, object]] = []
    for phase in task_index.get("phases") or []:
        if not isinstance(phase, dict) or "phase" not in phase:
            continue
        check = completed_phase_runtime_check(task_path, phase, apply_backfill=apply_backfill)
        if check is not None:
            checks.append(check)
    checks.extend(runtime_projection_drift_checks(root, task_path))
    blocking = [
        check
        for check in checks
        if check.get("severity") in {"error", "warning"}
        and check.get("id") != "phase.attempt_manifest.backfilled"
    ]
    report = {
        "schema_version": 1,
        "status": "fail" if blocking else "ok",
        "root": str(root),
        "task": str(task_path.relative_to(root)),
        "applied": apply_backfill,
        "checks": checks,
    }
    if apply_backfill and any(check.get("id") == "phase.attempt_manifest.backfilled" for check in checks):
        append_progress(task_path, "runtime proof doctor backfilled completed phase attempt manifests")
    return report


def reconcile_runtime_projection(root: Path, task_path: Path, dry_run: bool) -> list[dict[str, object]]:
    index_path = task_path / "index.json"
    task_index = read_json(index_path)
    changes: list[dict[str, object]] = []
    for phase in task_index.get("phases") or []:
        if not isinstance(phase, dict) or "phase" not in phase:
            continue
        phase_number = int(phase["phase"])
        status = phase.get("status")
        manifest_records, manifest_errors = read_attempt_manifest_records_with_errors(task_path, phase_number)
        manifest_errors.extend(attempt_manifest_semantic_errors(task_path, phase_number, manifest_records))
        if manifest_errors:
            message = "Phase attempt manifest is invalid:\n" + "\n".join(f"- {error}" for error in manifest_errors)
            changes.append(
                {
                    "phase": phase_number,
                    "from_status": status,
                    "to_status": "error",
                    "reason": "invalid_attempt_manifest",
                }
            )
            if not dry_run:
                phase["status"] = "error"
                phase["failed_at"] = now()
                phase["error_message"] = message
                write_last_error(task_path, phase_number, message)
            continue
        commit = latest_valid_phase_attempt_commit(task_path, phase_number)
        reset_generation, reset_at = phase_reset_state(task_path, phase_number)
        if reset_at and status != "pending" and str(phase.get("reset_at") or "") != reset_at:
            changes.append(
                {
                    "phase": phase_number,
                    "from_status": status,
                    "to_status": "pending",
                    "reason": "reset_marker_without_projection",
                }
            )
            if not dry_run:
                if not phase_has_own_reset_marker_at(task_path, phase_number, reset_at):
                    write_phase_reset_marker(task_path, phase_number, reset_at, phase_number)
                apply_reset_projection_to_phase(phase, reset_at)
            continue
        attempts = int(phase.get("attempts", 0) or 0)
        commit_attempt = commit.get("attempt") if commit else None
        commit_matches_phase_attempt = attempts <= 0 or commit_attempt == attempts
        if status in RUNNABLE_PHASE_STATUSES and commit and commit_matches_phase_attempt:
            terminalization_error = recovered_commit_terminalization_error(
                task_path,
                phase_number,
                commit,
                reset_generation,
            )
            if terminalization_error:
                changes.append(
                    {
                        "phase": phase_number,
                        "from_status": status,
                        "to_status": "error",
                        "reason": "conflicting_attempt_terminal_record",
                    }
                )
                if not dry_run:
                    phase["status"] = "error"
                    phase["failed_at"] = now()
                    phase["error_message"] = terminalization_error
                    write_last_error(task_path, phase_number, terminalization_error)
                continue
            changes.append({"phase": phase_number, "from_status": status, "to_status": "completed", "reason": "valid_attempt_commit"})
            if not dry_run:
                terminalize_recovered_attempt_commit(task_path, phase_number, commit, reset_generation)
                phase["status"] = "completed"
                phase["completed_at"] = now()
                phase["attempts"] = commit.get("attempt")
        elif status == "completed" and (not commit or not commit_matches_phase_attempt):
            reason = (
                "missing_attempt_commit"
                if not commit and not phase_attempt_commit_files_exist(task_path, phase_number)
                else "stale_attempt_commit"
            )
            changes.append({"phase": phase_number, "from_status": status, "to_status": "error", "reason": reason})
            if not dry_run:
                phase["status"] = "error"
                phase["error_message"] = "Completed phase is missing a valid attempt commit."
        elif (
            status in RUNNABLE_PHASE_STATUSES
            and (not commit or (attempts > 0 and commit_attempt != attempts))
        ):
            nonterminal_started_attempt = latest_nonterminal_started_attempt(task_path, phase_number, reset_generation)
            interrupted_attempt = nonterminal_started_attempt or attempts
            if status == "pending" and interrupted_attempt <= 0:
                continue
            terminal_record_type = (
                attempt_terminal_manifest_record_type(task_path, phase_number, interrupted_attempt, reset_generation)
                if interrupted_attempt > 0
                else None
            )
            terminal_record = (
                attempt_terminal_manifest_record(task_path, phase_number, interrupted_attempt, reset_generation)
                if interrupted_attempt > 0
                else None
            )
            if (
                interrupted_attempt > 0
                and nonterminal_started_attempt is None
                and not retryable_terminal_failure_recovery_errors(
                    task_path,
                    phase_number,
                    interrupted_attempt,
                    terminal_record,
                )
            ):
                changes.append(
                    {
                        "phase": phase_number,
                        "from_status": status,
                        "to_status": "pending",
                        "reason": "retryable_attempt_failed",
                    }
                )
                if not dry_run:
                    phase["status"] = "pending"
                    phase["attempts"] = interrupted_attempt
                    phase.pop("failed_at", None)
                    phase.pop("error_message", None)
                continue
            has_result_artifact = phase_result_artifacts_exist(task_path, phase_number)
            has_commit = bool(list((task_path / "context-pack" / "runtime").glob(f"phase{phase_number}-attempt*-commit.json")))
            reason = (
                "interrupted_running_phase"
                if terminal_record_type or has_result_artifact or has_commit
                else f"interrupted_{status}_attempt"
            )
            message = (
                "Phase attempt was interrupted before terminal runtime proof was written."
                if not has_result_artifact
                else "Phase result exists without a valid attempt commit."
            )
            changes.append({"phase": phase_number, "from_status": status, "to_status": "error", "reason": reason})
            if not dry_run:
                phase["status"] = "error"
                phase["failed_at"] = now()
                phase["error_message"] = message
                if interrupted_attempt > 0:
                    phase["attempts"] = interrupted_attempt
                write_last_error(task_path, phase_number, message)
                if interrupted_attempt > 0 and terminal_record_type is None:
                    try:
                        contract = runtime_phase_contract(task_path, phase_number, interrupted_attempt)
                    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
                        try:
                            contract = runtime_phase_contract(task_path, phase_number)
                        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
                            contract = None
                    required_outputs = contract_outputs(phase, contract) if contract else []
                    required_repo_outputs = contract_repo_outputs(contract) if contract else []
                    write_interrupted_attempt_repair_packet(
                        task_path,
                        phase_number,
                        build_repair_packet(
                            task_path,
                            phase_number,
                            phase,
                            interrupted_attempt,
                            reason,
                            message,
                            retryable=False,
                            contract=contract,
                            required_outputs=required_outputs,
                            required_repo_outputs=required_repo_outputs,
                        ),
                        interrupted_attempt,
                    )
    if changes and not dry_run:
        write_json(index_path, task_index)
    return changes


def reconcile_before_execution(root: Path, task_path: Path, args: argparse.Namespace) -> list[dict[str, object]]:
    if getattr(args, "dry_run", False):
        return []
    if getattr(args, "from_phase", None) is not None or getattr(args, "resume_repair", False):
        return []
    changes = reconcile_runtime_projection(root, task_path, dry_run=False)
    if changes:
        append_progress(
            task_path,
            "runtime projection reconciled before execution: "
            + ", ".join(
                f"phase {item.get('phase')} {item.get('from_status')} -> {item.get('to_status')}"
                for item in changes
            ),
        )
    return changes


def load_or_create_phase_baseline(root: Path, task_path: Path, phase_number: int, required_repo_outputs: list[str]) -> dict[str, object]:
    path = phase_baseline_path(task_path, phase_number)
    if path.exists():
        return read_json(path)
    snapshot = worktree_snapshot(root)
    baseline = {
        "schema_version": 1,
        "phase": phase_number,
        "created_at": now(),
        "snapshot": snapshot,
        "required_repo_outputs": required_repo_output_content_results(root, required_repo_outputs),
    }
    write_json(path, baseline)
    return baseline


def baseline_snapshot(baseline: dict[str, object]) -> dict[str, str]:
    snapshot = baseline.get("snapshot")
    return {str(key): str(value) for key, value in snapshot.items()} if isinstance(snapshot, dict) else {}


def baseline_required_repo_outputs(baseline: dict[str, object]) -> list[dict[str, object]]:
    outputs = baseline.get("required_repo_outputs")
    return outputs if isinstance(outputs, list) else []


def build_gate(
    root: Path,
    task_path: Path,
    phase_number: int,
    contract: dict,
    changed_files: list[str],
    command_results: list[dict[str, object]],
    required_outputs: list[str],
    required_repo_outputs: list[str],
    handoff_reasons: list[str],
    handoff_trace_errors: list[str],
    quality_result: dict[str, object] | None = None,
    evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    if evidence is None:
        evidence = build_evidence(
            root,
            phase_number,
            0,
            changed_files,
            command_results,
            required_outputs,
            required_repo_outputs,
            task_path,
            quality_result,
        )
    failed_commands = [item for item in command_results if item.get("exit_code") != 0]
    missing_outputs = verify_required_outputs(task_path, required_outputs)
    missing_repo_outputs = verify_required_repo_outputs(root, required_repo_outputs)
    violations = scope_violations(
        changed_files,
        contract_allowed_paths(contract),
        ignored_gate_paths(task_path, required_outputs),
    )
    dependency_errors = validate_dependency_changes(contract, changed_files, root)
    blocking_reasons: list[str] = []
    if failed_commands:
        blocking_reasons.append("One or more acceptance commands failed.")
    if missing_outputs:
        blocking_reasons.append("One or more required outputs are missing.")
    if missing_repo_outputs:
        blocking_reasons.append("One or more required repo outputs are missing.")
    if violations:
        blocking_reasons.append("Changed files include paths outside Contract.scope.allowed_paths.")
    if handoff_reasons:
        blocking_reasons.append("Handoff reports blocked, partial, skipped, or workaround status.")
    if handoff_trace_errors:
        blocking_reasons.append("Handoff change trace is missing or invalid.")
    if dependency_errors:
        blocking_reasons.extend(dependency_errors)
    quality_status = quality_result.get("status") if isinstance(quality_result, dict) else "skipped"
    quality_reasons = (
        quality_result.get("blocking_reasons")
        if isinstance(quality_result, dict) and isinstance(quality_result.get("blocking_reasons"), list)
        else []
    )
    if quality_status == "failed":
        quality_blockers = [str(item) for item in quality_reasons if str(item).strip()]
        blocking_reasons.extend(quality_blockers or ["Quality checks failed."])
    expected_failures = []
    for instruction in contract.get("instructions") or []:
        if not isinstance(instruction, dict):
            continue
        missing = [
            item
            for item in instruction.get("expected_evidence") or []
            if not expected_evidence_matched(item, evidence)
        ]
        if missing:
            expected_failures.append(
                {
                    "instruction_id": instruction.get("id"),
                    "missing_expected_evidence": missing,
                }
            )
    if expected_failures:
        blocking_reasons.append("One or more instruction expected_evidence entries were not observed.")

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
            "name": "required_repo_outputs",
            "status": "passed" if not missing_repo_outputs else "failed",
            "missing_outputs": missing_repo_outputs,
        },
        {
            "name": "handoff_status",
            "status": "passed" if not handoff_reasons else "failed",
            "reasons": handoff_reasons,
        },
        {
            "name": "handoff_change_trace",
            "status": "passed" if not handoff_trace_errors else "failed",
            "errors": handoff_trace_errors,
            "traceable_changed_files": traceable_changed_files(task_path, changed_files, required_outputs),
        },
        {
            "name": "scope",
            "status": "passed" if not violations else "failed",
            "violations": violations,
        },
        {
            "name": "dependency_policy",
            "status": "passed" if not dependency_errors else "failed",
            "errors": dependency_errors,
        },
        {
            "name": "quality",
            "status": "passed" if quality_status != "failed" else "failed",
            "source": quality_result.get("source") if isinstance(quality_result, dict) else None,
            "blocking_reasons": quality_reasons,
            "artifact": task_relative(phase_quality_path(task_path, phase_number), task_path),
        },
        {
            "name": "expected_evidence",
            "status": "passed" if not expected_failures else "failed",
            "failures": expected_failures,
        },
    ]
    return {
        "phase": phase_number,
        "status": "passed" if not blocking_reasons else "failed",
        "checks": checks,
        "blocking_reasons": blocking_reasons,
    }


def build_evidence(
    root: Path,
    phase_number: int,
    attempt: int,
    changed_files: list[str],
    command_results: list[dict[str, object]],
    required_outputs: list[str],
    required_repo_outputs: list[str],
    task_path: Path,
    quality_result: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "phase": phase_number,
        "attempt": attempt,
        "changed_files": changed_files,
        "commands": command_results,
        "required_outputs": required_output_results(task_path, required_outputs),
        "required_repo_outputs": required_repo_output_results(root, required_repo_outputs),
        "quality": quality_result or {},
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


def _expected_evidence_type_and_ref(expected: object) -> tuple[str | None, str | None]:
    if isinstance(expected, dict):
        raw_type = expected.get("type")
        evidence_type = raw_type if isinstance(raw_type, str) else None
        return evidence_type, _normalized_evidence_path(expected.get("ref"))
    return None, _normalized_evidence_path(expected)


def expected_evidence_matched(expected: object, evidence: dict[str, object]) -> bool:
    evidence_type, expected_text = _expected_evidence_type_and_ref(expected)
    if expected_text is None:
        return False

    if evidence_type in {None, "command"}:
        for item in evidence.get("commands", []) or []:
            if (
                isinstance(item, dict)
                and (item.get("command") == expected_text or item.get("id") == expected_text)
                and item.get("exit_code") == 0
            ):
                return True

    if evidence_type in {None, "required_output", "path"}:
        for item in evidence.get("required_outputs", []) or []:
            if (
                isinstance(item, dict)
                and item.get("exists") is True
                and item.get("path") == expected_text
            ):
                return True

    if evidence_type in {None, "required_repo_output", "path"}:
        for item in evidence.get("required_repo_outputs", []) or []:
            if (
                isinstance(item, dict)
                and item.get("exists") is True
                and item.get("path") == expected_text
            ):
                return True

    if evidence_type in {None, "changed_file", "path"}:
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
    attempt: int,
    contract: dict,
    evidence: dict[str, object],
    gate: dict[str, object],
) -> dict[str, object]:
    reconciliation = build_reconciliation(contract, evidence, gate)
    summary = reconciliation_markdown(reconciliation, gate)
    write_json(phase_attempt_evidence_path(task_path, phase_number, attempt), evidence)
    write_json(phase_attempt_gate_path(task_path, phase_number, attempt), gate)
    write_json(phase_attempt_reconciliation_path(task_path, phase_number, attempt), reconciliation)
    atomic_write_text(phase_attempt_reconciliation_summary_path(task_path, phase_number, attempt), summary)
    write_json(phase_evidence_path(task_path, phase_number), evidence)
    write_json(phase_gate_path(task_path, phase_number), gate)
    write_json(phase_reconciliation_path(task_path, phase_number), reconciliation)
    atomic_write_text(phase_reconciliation_summary_path(task_path, phase_number), summary)
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


def gate_scope_violations(gate: dict[str, object] | None) -> list[str]:
    if not gate:
        return []
    return [
        violation
        for check in gate.get("checks", [])
        if isinstance(check, dict) and check.get("name") == "scope"
        for violation in check.get("violations", [])
        if isinstance(violation, str)
    ]


def failed_instruction_results(reconciliation: dict[str, object] | None) -> list[dict[str, object]]:
    if not reconciliation:
        return []
    return [
        item
        for item in reconciliation.get("instruction_results", [])
        if isinstance(item, dict) and item.get("status") != "satisfied"
    ]


def contract_summary(
    contract: dict | None,
    phase: dict,
    required_outputs: list[str],
    required_repo_outputs: list[str],
) -> dict[str, object] | None:
    if contract is None:
        return None
    return {
        "phase": contract.get("phase"),
        "name": contract.get("name") or phase.get("name"),
        "read_first": contract.get("read_first") or [],
        "allowed_paths": contract_allowed_paths(contract),
        "acceptance_commands": contract_ac_commands(phase, contract),
        "required_outputs": required_outputs,
        "required_repo_outputs": required_repo_outputs,
        "success_criteria": contract.get("success_criteria") or [],
        "stop_rules": contract.get("stop_rules") or [],
        "fallback_behavior": contract.get("fallback_behavior") or {},
        "validation_budget": contract.get("validation_budget") or {},
        "missing_evidence_behavior": contract.get("missing_evidence_behavior"),
        "verification_evidence": contract.get("verification_evidence") or {},
        "decision_refs": contract.get("decision_refs") or [],
        "architecture_refs": contract.get("architecture_refs") or [],
        "dependency_policy": contract.get("dependency_policy") or {},
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
    required_repo_outputs: list[str] | None = None,
    missing_outputs: list[str] | None = None,
    missing_repo_outputs: list[str] | None = None,
    contaminating_changes: list[str] | None = None,
    changed_files: list[str] | None = None,
    runtime_integrity_report_path: Path | None = None,
    gate: dict[str, object] | None = None,
    reconciliation: dict[str, object] | None = None,
) -> dict[str, object]:
    commands = command_results or []
    outputs = required_outputs or []
    repo_outputs = required_repo_outputs or []
    stderr_tail = ""
    if stderr_path and stderr_path.exists():
        stderr_tail = truncate_text(stderr_path.read_text(encoding="utf-8", errors="replace"), 4_000)
    packet = {
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
        "contract": contract_summary(contract, phase, outputs, repo_outputs),
        "failed_commands": [
            item
            for item in compact_command_results(commands)
            if item.get("exit_code") != 0
        ],
        "commands": compact_command_results(commands),
        "required_outputs": required_output_results(task_path, outputs),
        "required_repo_outputs": required_repo_output_results(task_path.parent.parent, repo_outputs),
        "missing_outputs": missing_outputs or [],
        "missing_repo_outputs": missing_repo_outputs or [],
        "contaminating_changes": contaminating_changes or [],
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
    if runtime_integrity_report_path is not None:
        packet["runtime_integrity_report"] = artifact_ref(
            task_path,
            "runtime_integrity_report",
            runtime_integrity_report_path,
        )
    return packet


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

    missing_repo_outputs = packet.get("missing_repo_outputs") or []
    lines.extend(["", "## Missing Repo Outputs", ""])
    if missing_repo_outputs:
        for path in missing_repo_outputs:
            lines.append(f"- `{path}`")
    else:
        lines.append("- none")

    contaminating_changes = packet.get("contaminating_changes") or []
    lines.extend(["", "## Cleanup Required", ""])
    if contaminating_changes:
        lines.append("These out-of-scope changes were observed in the failed attempt.")
        lines.append("The runner will not auto-retry this phase until they are reviewed or cleaned up.")
        for path in contaminating_changes:
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
        repo_outputs = contract.get("required_repo_outputs") or []
        if repo_outputs:
            lines.extend(["", "Required repo outputs:"])
            for path in repo_outputs:
                lines.append(f"- `{path}`")
    else:
        lines.append("- contract unavailable")
    lines.append("")
    return "\n".join(lines)


def write_repair_packet(
    task_path: Path,
    phase_number: int,
    packet: dict[str, object],
    attempt: int | None = None,
) -> None:
    if attempt is not None:
        snapshot_attempt_handoff(task_path, phase_number, attempt)
        artifact_paths = [
            ("prompt", phase_attempt_prompt_path(task_path, phase_number, attempt)),
            ("contract", phase_attempt_contract_path(task_path, phase_number, attempt)),
            ("checklist", phase_attempt_checklist_path(task_path, phase_number, attempt)),
            ("stdout", task_path / "context-pack" / "runtime" / f"phase{phase_number}-output-attempt{attempt}.jsonl"),
            ("stderr", task_path / "context-pack" / "runtime" / f"phase{phase_number}-stderr-attempt{attempt}.txt"),
            ("ac_results", ac_results_path(task_path, phase_number, attempt)),
            ("quality", phase_attempt_quality_path(task_path, phase_number, attempt)),
            ("evidence", phase_attempt_evidence_path(task_path, phase_number, attempt)),
            ("gate", phase_attempt_gate_path(task_path, phase_number, attempt)),
            ("reconciliation", phase_attempt_reconciliation_path(task_path, phase_number, attempt)),
            ("reconciliation_summary", phase_attempt_reconciliation_summary_path(task_path, phase_number, attempt)),
            ("handoff", phase_attempt_handoff_path(task_path, phase_number, attempt)),
        ]
        runtime_integrity_report = phase_attempt_runtime_integrity_report_path(task_path, phase_number, attempt)
        if runtime_integrity_report.exists():
            artifact_paths.append(("runtime_integrity_report", runtime_integrity_report))
        failed_attempt_artifacts = [artifact_ref(task_path, name, path) for name, path in artifact_paths]
        packet = {**packet, "failed_attempt_artifacts": failed_attempt_artifacts}
    markdown = repair_packet_markdown(packet)
    if attempt is not None:
        write_json(phase_attempt_repair_packet_path(task_path, phase_number, attempt), packet)
        atomic_write_text(phase_attempt_repair_packet_summary_path(task_path, phase_number, attempt), markdown)
    write_json(phase_repair_packet_path(task_path, phase_number), packet)
    atomic_write_text(phase_repair_packet_summary_path(task_path, phase_number), markdown)
    if attempt is not None:
        failure = packet.get("failure") if isinstance(packet.get("failure"), dict) else {}
        append_attempt_manifest_record(
            task_path,
            phase_number,
            attempt,
            "attempt_failed",
            status="failed",
            failure=failure,
            retryable=failure.get("retryable"),
            repair_packet=artifact_ref(task_path, "repair_packet", phase_attempt_repair_packet_path(task_path, phase_number, attempt)),
            repair_packet_summary=artifact_ref(
                task_path,
                "repair_packet_summary",
                phase_attempt_repair_packet_summary_path(task_path, phase_number, attempt),
            ),
            artifacts=failed_attempt_artifacts,
        )


def write_terminal_phase_failure(
    root: Path,
    task_path: Path,
    phase: dict,
    phase_number: int,
    attempt: int,
    failure_type: str,
    message: str,
    *,
    contract: dict | None,
    retryable: bool = False,
    codex_exit_code: int | None = None,
    stderr_path: Path | None = None,
    command_results: list[dict[str, object]] | None = None,
    required_outputs: list[str] | None = None,
    required_repo_outputs: list[str] | None = None,
    contaminating_changes: list[str] | None = None,
    changed_files: list[str] | None = None,
    runtime_integrity_report_path: Path | None = None,
) -> None:
    write_last_error(task_path, phase_number, message)
    write_repair_packet(
        task_path,
        phase_number,
        build_repair_packet(
            task_path,
            phase_number,
            phase,
            attempt,
            failure_type,
            message,
            retryable=retryable,
            contract=contract,
            codex_exit_code=codex_exit_code,
            stderr_path=stderr_path,
            command_results=command_results,
            required_outputs=required_outputs or [],
            required_repo_outputs=required_repo_outputs or [],
            contaminating_changes=contaminating_changes or [],
            changed_files=changed_files or [],
            runtime_integrity_report_path=runtime_integrity_report_path,
        ),
        attempt=attempt,
    )
    task_index = read_json(task_path / "index.json")
    set_phase_status(task_index, phase_number, "error", failed_at=now(), error_message=message)
    write_json(task_path / "index.json", task_index)
    update_top_index(root, task_path.name, "error")


def clear_attempt_artifacts(task_path: Path, phase_number: int) -> None:
    for path in [
        phase_result_path(task_path, phase_number),
        phase_handoff_path(task_path, phase_number),
        phase_evidence_path(task_path, phase_number),
        phase_reconciliation_path(task_path, phase_number),
        phase_reconciliation_summary_path(task_path, phase_number),
        phase_gate_path(task_path, phase_number),
        phase_quality_path(task_path, phase_number),
    ]:
        path.unlink(missing_ok=True)


def clear_repair_packet(task_path: Path, phase_number: int) -> None:
    for path in [
        phase_repair_packet_path(task_path, phase_number),
        phase_repair_packet_summary_path(task_path, phase_number),
    ]:
        path.unlink(missing_ok=True)


def repair_context_integrity_errors(task_path: Path, phase_number: int) -> list[str]:
    packet_path = phase_repair_packet_path(task_path, phase_number)
    summary_path = phase_repair_packet_summary_path(task_path, phase_number)
    if not packet_path.exists() and not summary_path.exists():
        return []
    errors: list[str] = []
    manifest_records, manifest_errors = read_attempt_manifest_records_with_errors(task_path, phase_number)
    errors.extend(manifest_errors)
    errors.extend(attempt_manifest_semantic_errors(task_path, phase_number, manifest_records))
    if not packet_path.exists() or not summary_path.exists():
        errors.append(f"Phase {phase_number} repair context requires both packet JSON and summary markdown.")
        return errors
    try:
        packet = read_json(packet_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Invalid phase {phase_number} repair packet JSON: {exc}"]
    if not isinstance(packet, dict):
        return [f"Phase {phase_number} repair packet must be a JSON object."]
    if repair_packet_markdown(packet) != summary_path.read_text(encoding="utf-8", errors="replace"):
        errors.append(f"Phase {phase_number} repair packet summary does not match packet JSON.")
    attempt = packet.get("attempt")
    if not isinstance(attempt, int) or attempt <= 0:
        errors.append(f"Phase {phase_number} repair packet attempt must be a positive integer.")
        return errors
    attempt_packet_path = phase_attempt_repair_packet_path(task_path, phase_number, attempt)
    attempt_summary_path = phase_attempt_repair_packet_summary_path(task_path, phase_number, attempt)
    if not attempt_packet_path.exists() or not attempt_summary_path.exists():
        errors.append(f"Phase {phase_number} repair packet alias is missing attempt-scoped repair artifacts.")
        return errors
    try:
        attempt_packet = read_json(attempt_packet_path)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"Invalid phase {phase_number} attempt {attempt} repair packet JSON: {exc}")
        attempt_packet = None
    if isinstance(attempt_packet, dict) and attempt_packet != packet:
        errors.append(f"Phase {phase_number} repair packet alias does not match attempt-scoped repair packet.")
    if attempt_summary_path.read_text(encoding="utf-8", errors="replace") != summary_path.read_text(
        encoding="utf-8", errors="replace"
    ):
        errors.append(f"Phase {phase_number} repair packet summary alias does not match attempt-scoped summary.")
    matching_records = [
        record
        for record in manifest_records
        if record.get("attempt") == attempt and record.get("record_type") in {"attempt_failed", "attempt_interrupted"}
    ]
    if not matching_records:
        errors.append(f"Phase {phase_number} repair packet has no matching failed/interrupted manifest record.")
        return errors
    record = matching_records[-1]
    for key, expected_path in [
        ("repair_packet", attempt_packet_path),
        ("repair_packet_summary", attempt_summary_path),
    ]:
        ref = record.get(key) if isinstance(record.get(key), dict) else {}
        if ref.get("sha256") != file_sha256(expected_path):
            errors.append(f"Phase {phase_number} manifest {key} sha256 does not match repair artifact.")
    return errors


def generate_docs_diff(root: Path, task_path: Path, baseline: str | None) -> None:
    output_path = task_path / "context-pack" / "runtime" / "docs-diff.md"
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

    atomic_write_text(
        output_path,
        f"# docs-diff: {task_path.name}\n\n"
        f"Baseline: `{baseline or 'none'}`\n\n"
        "```diff\n"
        f"{diff}\n"
        "```\n",
    )


def generate_relationship_graph(root: Path, task_path: Path) -> None:
    from relationship_graph import write_relationship_graph_outputs

    result = write_relationship_graph_outputs(root, task_path)
    if result.get("status") == "warning":
        warning = result.get("warning")
        if warning:
            message = f"relationship graph warning: {warning}"
        else:
            detail = result.get("warning_error") or result.get("error") or "warning file unavailable"
            message = f"relationship graph warning file unavailable: {detail}"
        append_progress(task_path, message)
        print(message[:1].upper() + message[1:], file=sys.stderr)


def evaluation_final_path(task_path: Path) -> Path:
    return task_path / "context-pack" / "runtime" / "evaluation-last-message.json"


def read_evaluation_final(task_path: Path) -> dict[str, object] | None:
    path = evaluation_final_path(task_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def run_evaluation(root: Path, task_path: Path, args: argparse.Namespace) -> int:
    command = [
        sys.executable,
        str(SCRIPT_DIR / "evaluate-task.py"),
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
    if getattr(args, "strict_current_harness", False):
        command.append("--strict-current-harness")
    command.extend(["--codex-max-runtime", str(getattr(args, "codex_max_runtime", 1800))])
    command.append("--task-lock-held")
    command.append("--repo-lock-held")
    subprocess_timeout = getattr(args, "subprocess_timeout", 1800)
    try:
        result = run_process(
            command,
            cwd=root,
            env=sanitized_env(overrides={"PWD": str(root)}, allow_harness_policy_controls=True),
            timeout=subprocess_timeout or None,
        )
    except OSError as exc:
        print(f"Evaluation failed to start: {exc}", file=sys.stderr)
        return 127
    output = redact_text(result.stdout + result.stderr).strip()
    if output:
        print(output, file=sys.stderr if result.returncode != 0 else sys.stdout)
    if result.timed_out:
        print(
            f"Evaluation timed out after {subprocess_timeout} seconds.",
            file=sys.stderr,
        )
        if not result.cleanup_confirmed:
            print("Evaluation process cleanup after timeout could not be confirmed.", file=sys.stderr)
        return PROCESS_TIMEOUT_EXIT_CODE
    return result.returncode


def evaluation_improvement_allowed_paths(task_path: Path) -> list[str]:
    allowed: list[str] = []
    index_path = task_path / "index.json"
    if not index_path.exists():
        return allowed
    task_index = read_json(index_path)
    for phase in task_index.get("phases", []):
        phase_number = int(phase["phase"])
        try:
            phase_markdown = phase_file(task_path, phase_number).read_text(encoding="utf-8")
        except OSError:
            continue
        contract, errors = parse_phase_contract(phase_markdown)
        if errors or contract is None:
            continue
        for path in contract_allowed_paths(contract):
            if path not in allowed:
                allowed.append(path)
        for path in contract_required_repo_outputs(contract):
            if path not in allowed:
                allowed.append(path)
    return allowed


def evaluation_repair_handoff_path(task_path: Path, iteration: int) -> Path:
    return task_path / "context-pack" / "handoffs" / f"evaluation-repair{iteration}.md"


def evaluation_repair_result_path(task_path: Path, iteration: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"evaluation-repair{iteration}-result.json"


def build_evaluation_improvement_prompt(
    root: Path,
    task_path: Path,
    iteration: int,
    evaluation_final: dict[str, object],
    allowed_paths: list[str],
) -> str:
    task_index = read_json(task_path / "index.json")
    context = collect_files(root, [*common_doc_files(root, task_index), *task_doc_files(root, task_index)], 100_000)
    static_context = collect_files(root, static_context_files(task_path), 80_000)
    handoffs = collect_files(root, sorted((task_path / "context-pack" / "handoffs").glob("*.md")), 80_000)
    evaluation_output = collect_files(
        root,
        [
            task_path / "context-pack" / "runtime" / "evaluation-command-results.json",
            task_path / "context-pack" / "runtime" / "evaluation-last-message.json",
            task_path / "context-pack" / "runtime" / "evaluation-prompt.md",
        ],
        120_000,
    )
    handoff_rel = evaluation_repair_handoff_path(task_path, iteration).relative_to(root)
    allowed_lines = "\n".join(f"- `{path}`" for path in allowed_paths) or "- none"
    evaluation_json = json.dumps(evaluation_final, ensure_ascii=False, indent=2)
    return f"""# Harness Evaluation Improvement Contract

You are improving a generated task after fresh evaluation rejected it.

Task: `{task_index.get("task")}`
Iteration: `{iteration}`

## Goal

Fix only the concrete blockers and required follow-ups from the latest evaluation result, then stop.
This is the "review mode -> improve -> review mode" loop. The runner will re-run evaluation after your improvement.

## Evaluation Result

```json
{evaluation_json}
```

## Allowed Paths

{allowed_lines}

## Hard Invariants

- Edit only files covered by Allowed Paths.
- Do not edit task indexes.
- Do not edit runner-owned runtime proof files.
- Do not expand scope or add unapproved architecture, dependency, data model, API, or user-visible behavior.
- Do not spawn subagents.
- Write `{handoff_rel}` describing what changed and which evaluation blocker or follow-up it addresses.
- If the evaluation result is wrong and no code change is needed, write that rationale in the handoff and make no implementation changes.
- Return only the structured final output requested by the active output schema.

# Task Context

{context or "(none)"}

# Static Context

{static_context or "(none)"}

# Handoffs

{handoffs or "(none)"}

# Evaluation Artifacts

{evaluation_output or "(none)"}

# Repository Snapshot

{git_summary(root)}
"""


def run_evaluation_improvement(
    root: Path,
    task_path: Path,
    args: argparse.Namespace,
    iteration: int,
    evaluation_final: dict[str, object],
) -> int:
    allowed_paths = evaluation_improvement_allowed_paths(task_path)
    if not allowed_paths:
        print("Evaluation improvement is blocked: no allowed paths are available.", file=sys.stderr)
        return 1

    runtime_dir = task_path / "context-pack" / "runtime"
    prompt = build_evaluation_improvement_prompt(root, task_path, iteration, evaluation_final, allowed_paths)
    prompt_path = runtime_dir / f"evaluation-repair{iteration}-prompt.md"
    output_path = runtime_dir / f"evaluation-repair{iteration}-output.jsonl"
    stderr_path = runtime_dir / f"evaluation-repair{iteration}-stderr.txt"
    last_message_path = runtime_dir / f"evaluation-repair{iteration}-last-message.json"
    write_prompt_artifact(prompt_path, prompt)

    before = worktree_snapshot(root)
    command = [args.codex_bin, "exec", "--json", "--output-last-message", str(last_message_path)]
    add_output_schema(command, SCHEMA_DIR / "phase-final.schema.json")
    if args.yolo:
        command.append("--dangerously-bypass-approvals-and-sandbox")
    elif args.full_auto:
        command.append("--full-auto")
    command.append("-")
    returncode = run_codex_exec(
        command,
        cwd=root,
        prompt=prompt,
        output_path=output_path,
        stderr_path=stderr_path,
        idle_timeout=getattr(args, "codex_idle_timeout", 300),
        max_runtime=getattr(args, "codex_max_runtime", 1800),
        activity_paths=[root / path for path in allowed_paths] + [evaluation_repair_handoff_path(task_path, iteration)],
    )
    after = worktree_snapshot(root)
    changed_files = phase_changed_paths(task_path, before, after)
    ignored_paths = [str(evaluation_repair_handoff_path(task_path, iteration).relative_to(root))]
    traceable_files = [path for path in changed_files if not path_allowed(path, ignored_paths)]
    violations = scope_violations(traceable_files, allowed_paths, [])
    handoff_exists = evaluation_repair_handoff_path(task_path, iteration).exists()
    result = {
        "schema_version": 1,
        "runner_version": HARNESS_VERSION,
        "repair_scope": "evaluation_improvement",
        "iteration": iteration,
        "status": "completed" if returncode == 0 and not violations and handoff_exists else "failed",
        "codex_exit_code": returncode,
        "changed_files": changed_files,
        "repo_content": repo_content_attestation(root, changed_files, [], [], before, after),
        "policy_pack": runtime_policy_pack(),
        "harness_attestation": RUNTIME_HARNESS_ATTESTATION,
        "allowed_paths": allowed_paths,
        "scope_violations": violations,
        "handoff": str(evaluation_repair_handoff_path(task_path, iteration).relative_to(task_path)),
        "handoff_exists": handoff_exists,
        "artifacts": {
            "prompt": str(prompt_path.relative_to(task_path)),
            "stdout": str(output_path.relative_to(task_path)),
            "stderr": str(stderr_path.relative_to(task_path)),
            "last_message": str(last_message_path.relative_to(task_path)),
        },
        "artifact_refs": [
            artifact_ref(task_path, "prompt", prompt_path),
            artifact_ref(task_path, "stdout", output_path),
            artifact_ref(task_path, "stderr", stderr_path),
            artifact_ref(task_path, "last_message", last_message_path),
            artifact_ref(task_path, "handoff", evaluation_repair_handoff_path(task_path, iteration)),
        ],
    }
    write_json(evaluation_repair_result_path(task_path, iteration), result)
    if returncode != 0:
        print(f"Evaluation improvement failed. See {stderr_path}.", file=sys.stderr)
        return returncode
    if violations:
        print(
            "Evaluation improvement changed files outside allowed paths: "
            + ", ".join(violations),
            file=sys.stderr,
        )
        return 1
    if not handoff_exists:
        print(
            f"Evaluation improvement did not write required handoff: {evaluation_repair_handoff_path(task_path, iteration)}",
            file=sys.stderr,
        )
        return 1
    return 0


def run_evaluation_review_loop(root: Path, task_path: Path, args: argparse.Namespace) -> int:
    max_iterations = getattr(args, "review_iterations", 5)
    for iteration in range(0, max_iterations + 1):
        append_progress(task_path, f"evaluation review iteration {iteration}: started")
        eval_returncode = run_evaluation(root, task_path, args)
        evaluation_final = read_evaluation_final(task_path)
        if evaluation_final and evaluation_final.get("verdict") == "approved" and eval_returncode == 0:
            append_progress(task_path, f"evaluation review iteration {iteration}: approved")
            return 0
        if evaluation_final and evaluation_final.get("verdict") == "rejected" and iteration < max_iterations:
            append_progress(task_path, f"evaluation review iteration {iteration}: rejected; improvement started")
            improvement_returncode = run_evaluation_improvement(
                root,
                task_path,
                args,
                iteration + 1,
                evaluation_final,
            )
            if improvement_returncode != 0:
                args.failed = True
                return improvement_returncode
            continue
        if eval_returncode != 0:
            args.failed = True
            return eval_returncode
        if evaluation_final and evaluation_final.get("verdict") == "rejected":
            print(
                f"Evaluation still rejected after {max_iterations} improvement iteration(s).",
                file=sys.stderr,
            )
        else:
            print("Evaluation final output is missing or invalid.", file=sys.stderr)
        args.failed = True
        return 1
    args.failed = True
    return 1


def verify_task(
    root: Path,
    task_path: Path,
    require_evaluation: bool = False,
    require_design_approval: bool = True,
    strict_current_harness: bool = False,
    timeout: int = 1800,
) -> int:
    effective_timeout = timeout or None
    command = [
        sys.executable,
        str(SCRIPT_DIR / "verify-task.py"),
        task_path.name,
        "--root",
        str(root),
    ]
    if require_design_approval:
        command.append("--require-design-approval")
    if require_evaluation:
        command.append("--require-evaluation")
    if strict_current_harness:
        command.append("--strict-current-harness")
    try:
        result = run_process(
            command,
            cwd=root,
            env=sanitized_env(overrides={"PWD": str(root)}, allow_harness_policy_controls=True),
            timeout=effective_timeout,
        )
    except OSError as exc:
        print(f"Task verification failed to start: {exc}", file=sys.stderr)
        return 127
    output = redact_text(result.stdout + result.stderr).strip()
    if output:
        print(output, file=sys.stderr if result.returncode != 0 else sys.stdout)
    if result.timed_out:
        print(f"Task verification timed out after {timeout} seconds.", file=sys.stderr)
        if not result.cleanup_confirmed:
            print("Task verification process cleanup after timeout could not be confirmed.", file=sys.stderr)
        return PROCESS_TIMEOUT_EXIT_CODE
    return result.returncode


def finalize_completed_task(root: Path, task_path: Path, args: argparse.Namespace) -> int:
    generate_relationship_graph(root, task_path)
    if verify_task(
        root,
        task_path,
        strict_current_harness=getattr(args, "strict_current_harness", False),
        timeout=getattr(args, "subprocess_timeout", 1800),
    ) != 0:
        update_top_index(root, task_path.name, "error")
        args.failed = True
        return 1
    if args.evaluate:
        eval_returncode = run_evaluation_review_loop(root, task_path, args)
        if eval_returncode != 0:
            update_top_index(root, task_path.name, "error")
            args.failed = True
            return 1
        if verify_task(
            root,
            task_path,
            require_evaluation=True,
            strict_current_harness=getattr(args, "strict_current_harness", False),
            timeout=getattr(args, "subprocess_timeout", 1800),
        ) != 0:
            update_top_index(root, task_path.name, "error")
            args.failed = True
            return 1
    update_top_index(root, task_path.name, "completed")
    return 0


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
    reset_at = now()
    reset_results = reset_phase_statuses(task_index, from_phase, reset_at)
    print_reset_summary(from_phase, reset_results, dry_run)

    if dry_run:
        return task_index

    if reset_results:
        for item in reset_results:
            phase_number = int(item["phase"])
            write_phase_reset_marker(task_path, phase_number, reset_at, from_phase)
            phase_baseline_path(task_path, phase_number).unlink(missing_ok=True)
            clear_repair_packet(task_path, phase_number)
        write_json(index_path, task_index)
        update_top_index(root, task_path.name, "pending")
    return None


def earliest_repair_phase(task_path: Path, task_index: dict) -> int | None:
    candidates: list[int] = []
    runtime_dir = task_path / "context-pack" / "runtime"
    for phase in task_index.get("phases", []):
        phase_number = int(phase["phase"])
        if phase.get("status") in {"error", "repair_required"}:
            candidates.append(phase_number)
        if not (runtime_dir / f"phase{phase_number}-repair-packet.json").exists():
            continue
        commit = latest_valid_phase_attempt_commit(task_path, phase_number)
        commit_attempt = commit.get("attempt") if commit else None
        phase_attempt = phase.get("attempts")
        if phase.get("status") == "completed" and commit and commit_attempt == phase_attempt:
            continue
        candidates.append(phase_number)
    return min(candidates) if candidates else None


def apply_repair_resume(root: Path, task_path: Path, dry_run: bool) -> dict | None:
    index_path = task_path / "index.json"
    task_index = read_json(index_path)
    from_phase = earliest_repair_phase(task_path, task_index)
    if from_phase is None:
        print("No repair packet or failed phase found.")
        return task_index if dry_run else None
    reset_at = now()
    reset_results = reset_phase_statuses(task_index, from_phase, reset_at)
    print_reset_summary(from_phase, reset_results, dry_run)
    if dry_run:
        return task_index
    if reset_results:
        for item in reset_results:
            phase_number = int(item["phase"])
            write_phase_reset_marker(task_path, phase_number, reset_at, from_phase)
            phase_baseline_path(task_path, phase_number).unlink(missing_ok=True)
        write_json(index_path, task_index)
        update_top_index(root, task_path.name, "pending")
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
            if verify_task(
                root,
                task_path,
                strict_current_harness=getattr(args, "strict_current_harness", False),
                timeout=getattr(args, "subprocess_timeout", 1800),
            ) != 0:
                args.failed = True
                update_top_index(root, task_path.name, "error")
                return False
            update_top_index(root, task_path.name, "completed")
        print("No pending phases.")
        return False

    phase_number = int(phase["phase"])
    attempts = int(phase.get("attempts", 0) or 0)
    if not args.dry_run:
        append_progress(task_path, f"phase {phase_number}: preflight started")
    if attempts <= 0 and not args.dry_run and not getattr(args, "resume_repair", False):
        clear_repair_packet(task_path, phase_number)

    preflight_errors = []
    if verify_task(
        root,
        task_path,
        strict_current_harness=getattr(args, "strict_current_harness", False),
        timeout=getattr(args, "subprocess_timeout", 1800),
    ) != 0:
        preflight_errors.append("Task verification failed before phase execution.")
    preflight_errors.extend(current_policy_lineage_errors(task_path))
    preflight_errors.extend(nested_codex_preflight_errors(args))
    preflight_errors.extend(preflight_phase(root, task_path, task_index, phase))
    preflight_errors.extend(repair_context_integrity_errors(task_path, phase_number))
    if preflight_errors:
        message = "Preflight failed:\n" + "\n".join(f"- {error}" for error in preflight_errors)
        if not args.dry_run:
            write_last_error(task_path, phase_number, message)
            append_progress(task_path, f"phase {phase_number}: preflight failed")
        print(message, file=sys.stderr)
        args.failed = True
        return False

    try:
        initial_contract = phase_contract_from_markdown(phase_file(task_path, phase_number).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        initial_contract = None
    prompt = build_prompt(
        root,
        task_path,
        task_index,
        phase,
        include_repair_packet=attempts > 0 or phase_repair_packet_summary_path(task_path, phase_number).exists(),
        materialize_runtime_artifacts=False,
    )
    if args.dry_run:
        print(prompt)
        return False

    max_attempts, ac_timeout = contract_validation_budget(initial_contract, args)

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

    for attempt in range(attempts + 1, max_attempts + 1):
        append_progress(task_path, f"phase {phase_number}: attempt {attempt} started")
        prompt_path = phase_attempt_prompt_path(task_path, phase_number, attempt)
        contract_path = phase_attempt_contract_path(task_path, phase_number, attempt)
        checklist_path = phase_attempt_checklist_path(task_path, phase_number, attempt)
        output_path = task_path / "context-pack" / "runtime" / f"phase{phase_number}-output-attempt{attempt}.jsonl"
        stderr_path = task_path / "context-pack" / "runtime" / f"phase{phase_number}-stderr-attempt{attempt}.txt"
        task_index = read_json(index_path)
        set_phase_status(
            task_index,
            phase_number,
            "running",
            started_at=phase.get("started_at") or now(),
            attempts=attempt,
        )
        write_json(index_path, task_index)
        phase_baseline = load_or_create_phase_baseline(
            root,
            task_path,
            phase_number,
            contract_repo_outputs(initial_contract or {}),
        )
        phase_start_snapshot = baseline_snapshot(phase_baseline)
        phase_start_repo_outputs = baseline_required_repo_outputs(phase_baseline)

        clear_attempt_artifacts(task_path, phase_number)
        prompt = build_prompt(
            root,
            task_path,
            read_json(index_path),
            phase,
            include_repair_packet=attempts > 0
            or attempt > attempts + 1
            or phase_repair_packet_summary_path(task_path, phase_number).exists(),
            materialize_runtime_artifacts=True,
            contract_path=contract_path,
            checklist_path=checklist_path,
        )
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        write_prompt_artifact(prompt_path, prompt)
        write_prompt_artifact(task_path / "context-pack" / "runtime" / f"phase{phase_number}-prompt.md", prompt)
        append_attempt_manifest_record(
            task_path,
            phase_number,
            attempt,
            "attempt_started",
            status="running",
        )
        trusted_attempt_manifest_content = phase_attempt_manifest_path(task_path, phase_number).read_text(
            encoding="utf-8"
        )
        codex_runtime_snapshot = runtime_artifact_snapshot(task_path)

        install_errors = run_install_preflight(root, task_path, args)
        if install_errors:
            message = "\n".join(install_errors)
            write_last_error(task_path, phase_number, message)
            task_index = read_json(index_path)
            set_phase_status(task_index, phase_number, "error", failed_at=now(), error_message=message)
            write_json(index_path, task_index)
            update_top_index(root, task_path.name, "error")
            try:
                contract = runtime_phase_contract(task_path, phase_number, attempt)
                required_outputs = contract_outputs(phase, contract)
                required_repo_outputs = contract_repo_outputs(contract)
            except (FileNotFoundError, ValueError):
                contract = initial_contract
                required_outputs = contract_outputs(phase, contract) if contract else []
                required_repo_outputs = contract_repo_outputs(contract) if contract else []
            write_repair_packet(
                task_path,
                phase_number,
                build_repair_packet(
                    task_path,
                    phase_number,
                    phase,
                    attempt,
                    "install_preflight",
                    message,
                    retryable=attempt < max_attempts and install_preflight_failure_retryable(task_path),
                    contract=contract,
                    required_outputs=required_outputs,
                    required_repo_outputs=required_repo_outputs,
                ),
                attempt=attempt,
            )
            print(message, file=sys.stderr)
            args.failed = True
            return False

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
            getattr(args, "codex_max_runtime", 1800),
        )
        codex_runtime_allowed_paths = [
            task_relative(output_path, task_path),
            task_relative(stderr_path, task_path),
        ]
        runtime_ignored_paths = runtime_integrity_ignored_contract_paths(task_path, phase_number, attempt)
        settle_seconds = runtime_settle_seconds(args)
        settle_poll_seconds = runtime_settle_poll_seconds(args)
        codex_runtime_after_snapshot = runtime_artifact_stable_snapshot(
            task_path,
            settle_seconds=settle_seconds,
            poll_seconds=settle_poll_seconds,
        )
        runtime_integrity_changes = runtime_artifact_integrity_changes(
            codex_runtime_snapshot,
            codex_runtime_after_snapshot,
            allowed_paths=codex_runtime_allowed_paths,
            ignored_paths=runtime_ignored_paths,
        )
        if runtime_integrity_changes:
            message = (
                "Runner-owned runtime artifacts changed during phase Codex execution: "
                + ", ".join(runtime_integrity_changes)
            )
            append_progress(task_path, f"phase {phase_number}: attempt {attempt} runtime integrity failed")
            restore_attempt_manifest_content(task_path, phase_number, trusted_attempt_manifest_content)
            runtime_integrity_report_path = write_attempt_runtime_integrity_report(
                task_path,
                phase_number,
                attempt,
                failure_window="codex_execution",
                before=codex_runtime_snapshot,
                after=codex_runtime_after_snapshot,
                allowed_paths=codex_runtime_allowed_paths,
                ignored_paths=runtime_ignored_paths,
                settle_seconds=settle_seconds,
                poll_seconds=settle_poll_seconds,
            )
            try:
                contract = runtime_phase_contract(task_path, phase_number, attempt)
                required_outputs = contract_outputs(phase, contract)
                required_repo_outputs = contract_repo_outputs(contract)
            except (FileNotFoundError, ValueError, json.JSONDecodeError):
                contract = initial_contract
                required_outputs = contract_outputs(phase, contract) if contract else []
                required_repo_outputs = contract_repo_outputs(contract) if contract else []
            write_terminal_phase_failure(
                root,
                task_path,
                phase,
                phase_number,
                attempt,
                "runtime_integrity",
                message,
                contract=contract,
                retryable=False,
                codex_exit_code=returncode,
                stderr_path=stderr_path,
                required_outputs=required_outputs,
                required_repo_outputs=required_repo_outputs,
                contaminating_changes=runtime_integrity_changes,
                changed_files=runtime_integrity_changes,
                runtime_integrity_report_path=runtime_integrity_report_path,
            )
            print(message, file=sys.stderr)
            args.failed = True
            return False
        if returncode != 0:
            message = f"codex exec failed with exit code {returncode}. See {stderr_path}."
            append_progress(task_path, f"phase {phase_number}: attempt {attempt} codex failed")
            try:
                contract = runtime_phase_contract(task_path, phase_number, attempt)
                required_outputs = contract_outputs(phase, contract)
                required_repo_outputs = contract_repo_outputs(contract)
            except (FileNotFoundError, ValueError):
                contract = None
                required_outputs = []
                required_repo_outputs = []
            failed_snapshot = worktree_snapshot(root)
            changed_files = phase_changed_paths(task_path, phase_start_snapshot, failed_snapshot)
            contaminating_changes = attempt_scope_violations(
                contract,
                task_path,
                changed_files,
                required_outputs,
            )
            retryable = (
                attempt < max_attempts
                and not contaminating_changes
                and returncode not in {CODEX_STARTUP_EXIT_CODE, CODEX_CLEANUP_FAILED_EXIT_CODE}
            )
            if contaminating_changes:
                message += (
                    " Out-of-scope changes require cleanup before retry: "
                    + ", ".join(contaminating_changes)
                )
            if contract is not None:
                original_contract = initial_contract or contract
                contract_tamper_errors = [
                    *verify_phase_contract_unchanged(task_path, phase_number, original_contract),
                    *verify_runtime_contract_unchanged(task_path, phase_number, attempt, original_contract),
                ]
                if contract_tamper_errors:
                    message = "; ".join(contract_tamper_errors)
                    write_terminal_phase_failure(
                        root,
                        task_path,
                        phase,
                        phase_number,
                        attempt,
                        "contract_tamper",
                        message,
                        contract=contract,
                        retryable=False,
                        codex_exit_code=returncode,
                        stderr_path=stderr_path,
                        required_outputs=required_outputs,
                        required_repo_outputs=required_repo_outputs,
                        contaminating_changes=contaminating_changes,
                        changed_files=changed_files,
                    )
                    print(message, file=sys.stderr)
                    args.failed = True
                    return False
            write_last_error(task_path, phase_number, message)
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
                    retryable=retryable,
                    contract=contract,
                    codex_exit_code=returncode,
                    stderr_path=stderr_path,
                    required_outputs=required_outputs,
                    required_repo_outputs=required_repo_outputs,
                    contaminating_changes=contaminating_changes,
                    changed_files=changed_files,
                ),
                attempt=attempt,
            )
            if retryable:
                continue
            task_index = read_json(index_path)
            set_phase_status(task_index, phase_number, "error", failed_at=now(), error_message=message)
            write_json(index_path, task_index)
            update_top_index(root, task_path.name, "error")
            print(message, file=sys.stderr)
            args.failed = True
            return False

        try:
            contract = runtime_phase_contract(task_path, phase_number, attempt)
        except (FileNotFoundError, ValueError) as exc:
            message = str(exc)
            write_terminal_phase_failure(
                root,
                task_path,
                phase,
                phase_number,
                attempt,
                "runtime_contract",
                message,
                contract=initial_contract,
                retryable=False,
                required_outputs=contract_outputs(phase, initial_contract) if initial_contract else [],
                required_repo_outputs=contract_repo_outputs(initial_contract) if initial_contract else [],
            )
            print(message, file=sys.stderr)
            args.failed = True
            return False
        original_contract = initial_contract or contract
        contract_tamper_errors = [
            *verify_phase_contract_unchanged(task_path, phase_number, original_contract),
            *verify_runtime_contract_unchanged(task_path, phase_number, attempt, original_contract),
        ]
        if contract_tamper_errors:
            message = "; ".join(contract_tamper_errors)
            write_terminal_phase_failure(
                root,
                task_path,
                phase,
                phase_number,
                attempt,
                "contract_tamper",
                message,
                contract=contract,
                retryable=False,
                required_outputs=contract_outputs(phase, contract),
                required_repo_outputs=contract_repo_outputs(contract),
            )
            print(message, file=sys.stderr)
            args.failed = True
            return False
        required_outputs = contract_outputs(phase, contract)
        required_repo_outputs = contract_repo_outputs(contract)
        command_results: list[dict[str, object]] = []
        ac_runtime_snapshot = runtime_artifact_snapshot(task_path)
        for command in contract_ac_commands(phase, contract):
            ac_returncode, ac_output, ac_timed_out = run_shell(command, root, ac_timeout)
            command_results.append(
                {
                    "command": command,
                    "exit_code": ac_returncode,
                    "output": ac_output,
                    "timed_out": ac_timed_out,
                }
            )
            ac_runtime_after_snapshot = runtime_artifact_snapshot(task_path)
            runtime_integrity_changes = runtime_artifact_integrity_changes(
                ac_runtime_snapshot,
                ac_runtime_after_snapshot,
                ignored_paths=runtime_ignored_paths,
            )
            if runtime_integrity_changes:
                message = (
                    "Runner-owned runtime artifacts changed during acceptance command execution: "
                    + ", ".join(runtime_integrity_changes)
                )
                append_progress(task_path, f"phase {phase_number}: attempt {attempt} runtime integrity failed")
                restore_attempt_manifest_content(task_path, phase_number, trusted_attempt_manifest_content)
                runtime_integrity_report_path = write_attempt_runtime_integrity_report(
                    task_path,
                    phase_number,
                    attempt,
                    failure_window="acceptance_command_execution",
                    before=ac_runtime_snapshot,
                    after=ac_runtime_after_snapshot,
                    ignored_paths=runtime_ignored_paths,
                    settle_seconds=0.0,
                    poll_seconds=0.0,
                )
                write_terminal_phase_failure(
                    root,
                    task_path,
                    phase,
                    phase_number,
                    attempt,
                    "runtime_integrity",
                    message,
                    contract=contract,
                    retryable=False,
                    command_results=command_results,
                    required_outputs=required_outputs,
                    required_repo_outputs=required_repo_outputs,
                    contaminating_changes=runtime_integrity_changes,
                    changed_files=runtime_integrity_changes,
                    runtime_integrity_report_path=runtime_integrity_report_path,
                )
                print(message, file=sys.stderr)
                args.failed = True
                return False
            if ac_returncode != 0:
                message = f"AC command failed: {command}\n\n{ac_output}"
                append_progress(task_path, f"phase {phase_number}: attempt {attempt} acceptance command failed")
                write_ac_results(task_path, phase_number, attempt, command_results)
                failed_snapshot = worktree_snapshot(root)
                changed_files = phase_changed_paths(task_path, phase_start_snapshot, failed_snapshot)
                contaminating_changes = attempt_scope_violations(
                    contract,
                    task_path,
                    changed_files,
                    required_outputs,
                )
                retryable = attempt < max_attempts and not contaminating_changes
                if contaminating_changes:
                    message += (
                        "\n\nOut-of-scope changes require cleanup before retry: "
                        + ", ".join(contaminating_changes)
                    )
                write_last_error(task_path, phase_number, message)
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
                        retryable=retryable,
                        contract=contract,
                        command_results=command_results,
                        required_outputs=required_outputs,
                        required_repo_outputs=required_repo_outputs,
                        contaminating_changes=contaminating_changes,
                        changed_files=changed_files,
                    ),
                    attempt=attempt,
                )
                if retryable:
                    break
                task_index = read_json(index_path)
                set_phase_status(task_index, phase_number, "error", failed_at=now(), error_message=message)
                write_json(index_path, task_index)
                update_top_index(root, task_path.name, "error")
                print(message, file=sys.stderr)
                args.failed = True
                return False
        else:
            post_ac_settle_seconds = runtime_settle_seconds(args)
            post_ac_settle_poll_seconds = runtime_settle_poll_seconds(args)
            post_ac_runtime_after_snapshot = runtime_artifact_stable_snapshot(
                task_path,
                settle_seconds=post_ac_settle_seconds,
                poll_seconds=post_ac_settle_poll_seconds,
            )
            runtime_integrity_changes = runtime_artifact_integrity_changes(
                ac_runtime_snapshot,
                post_ac_runtime_after_snapshot,
                ignored_paths=runtime_ignored_paths,
            )
            if runtime_integrity_changes:
                message = (
                    "Runner-owned runtime artifacts changed after acceptance command execution: "
                    + ", ".join(runtime_integrity_changes)
                )
                append_progress(task_path, f"phase {phase_number}: attempt {attempt} runtime integrity failed")
                restore_attempt_manifest_content(task_path, phase_number, trusted_attempt_manifest_content)
                runtime_integrity_report_path = write_attempt_runtime_integrity_report(
                    task_path,
                    phase_number,
                    attempt,
                    failure_window="post_acceptance_settle",
                    before=ac_runtime_snapshot,
                    after=post_ac_runtime_after_snapshot,
                    ignored_paths=runtime_ignored_paths,
                    settle_seconds=post_ac_settle_seconds,
                    poll_seconds=post_ac_settle_poll_seconds,
                )
                write_terminal_phase_failure(
                    root,
                    task_path,
                    phase,
                    phase_number,
                    attempt,
                    "runtime_integrity",
                    message,
                    contract=contract,
                    retryable=False,
                    command_results=command_results,
                    required_outputs=required_outputs,
                    required_repo_outputs=required_repo_outputs,
                    contaminating_changes=runtime_integrity_changes,
                    changed_files=runtime_integrity_changes,
                    runtime_integrity_report_path=runtime_integrity_report_path,
                )
                print(message, file=sys.stderr)
                args.failed = True
                return False
            ac_results = write_ac_results(task_path, phase_number, attempt, command_results)
            missing_outputs = verify_required_outputs(task_path, required_outputs)
            if missing_outputs:
                message = "Missing required outputs: " + ", ".join(missing_outputs)
                append_progress(task_path, f"phase {phase_number}: attempt {attempt} required outputs missing")
                failed_snapshot = worktree_snapshot(root)
                changed_files = phase_changed_paths(task_path, phase_start_snapshot, failed_snapshot)
                contaminating_changes = attempt_scope_violations(
                    contract,
                    task_path,
                    changed_files,
                    required_outputs,
                )
                retryable = attempt < max_attempts and not contaminating_changes
                if contaminating_changes:
                    message += (
                        " Out-of-scope changes require cleanup before retry: "
                        + ", ".join(contaminating_changes)
                    )
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
                        retryable=retryable,
                        contract=contract,
                        command_results=command_results,
                        required_outputs=required_outputs,
                        required_repo_outputs=required_repo_outputs,
                        missing_outputs=missing_outputs,
                        contaminating_changes=contaminating_changes,
                        changed_files=changed_files,
                    ),
                    attempt=attempt,
                )
                if retryable:
                    continue
                task_index = read_json(index_path)
                set_phase_status(task_index, phase_number, "error", failed_at=now(), error_message=message)
                write_json(index_path, task_index)
                update_top_index(root, task_path.name, "error")
                print(message, file=sys.stderr)
                args.failed = True
                return False

            missing_repo_outputs = verify_required_repo_outputs(root, required_repo_outputs)
            if missing_repo_outputs:
                message = "Missing required repo outputs: " + ", ".join(missing_repo_outputs)
                append_progress(task_path, f"phase {phase_number}: attempt {attempt} required repo outputs missing")
                failed_snapshot = worktree_snapshot(root)
                changed_files = phase_changed_paths(task_path, phase_start_snapshot, failed_snapshot)
                contaminating_changes = attempt_scope_violations(
                    contract,
                    task_path,
                    changed_files,
                    required_outputs,
                )
                retryable = attempt < max_attempts and not contaminating_changes
                if contaminating_changes:
                    message += (
                        " Out-of-scope changes require cleanup before retry: "
                        + ", ".join(contaminating_changes)
                    )
                write_last_error(task_path, phase_number, message)
                write_repair_packet(
                    task_path,
                    phase_number,
                    build_repair_packet(
                        task_path,
                        phase_number,
                        phase,
                        attempt,
                        "required_repo_outputs",
                        message,
                        retryable=retryable,
                        contract=contract,
                        command_results=command_results,
                        required_outputs=required_outputs,
                        required_repo_outputs=required_repo_outputs,
                        missing_repo_outputs=missing_repo_outputs,
                        contaminating_changes=contaminating_changes,
                        changed_files=changed_files,
                    ),
                    attempt=attempt,
                )
                if retryable:
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
            quality_result = run_quality_checks(root, task_path, phase_number, changed_files)
            write_json(phase_attempt_quality_path(task_path, phase_number, attempt), quality_result)
            evidence = build_evidence(
                root,
                phase_number,
                attempt,
                changed_files,
                command_results,
                required_outputs,
                required_repo_outputs,
                task_path,
                quality_result,
            )
            handoff_reasons = handoff_blockers(task_path, phase_number)
            handoff_trace_errors = handoff_change_trace_blockers(
                task_path,
                phase_number,
                contract,
                changed_files,
                required_outputs,
            )
            gate = build_gate(
                root,
                task_path,
                phase_number,
                contract,
                changed_files,
                command_results,
                required_outputs,
                required_repo_outputs,
                handoff_reasons,
                handoff_trace_errors,
                quality_result,
            )
            reconciliation = write_runtime_review_artifacts(task_path, phase_number, attempt, contract, evidence, gate)
            if gate.get("status") != "passed":
                reasons = list(gate.get("blocking_reasons") or [])
                message = "Phase gate failed: " + "; ".join(reasons)
                contaminating_changes = gate_scope_violations(gate)
                retryable = attempt < max_attempts and not contaminating_changes
                if contaminating_changes:
                    message += (
                        " Cleanup required for out-of-scope changes: "
                        + ", ".join(contaminating_changes)
                    )
                append_progress(task_path, f"phase {phase_number}: attempt {attempt} gate failed")
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
                        retryable=retryable,
                        contract=contract,
                        command_results=command_results,
                        required_outputs=required_outputs,
                        required_repo_outputs=required_repo_outputs,
                        contaminating_changes=contaminating_changes,
                        changed_files=changed_files,
                        gate=gate,
                        reconciliation=reconciliation,
                    ),
                    attempt=attempt,
                )
                if retryable:
                    continue
                task_index = read_json(index_path)
                set_phase_status(task_index, phase_number, "error", failed_at=now(), error_message=message)
                write_json(index_path, task_index)
                update_top_index(root, task_path.name, "error")
                print(message, file=sys.stderr)
                args.failed = True
                return False

            result_path = write_phase_result(
                root=root,
                task_path=task_path,
                phase_number=phase_number,
                attempt=attempt,
                codex_exit_code=returncode,
                changed_files=changed_files,
                command_results=command_results,
                required_outputs=required_outputs,
                required_repo_outputs=required_repo_outputs,
                prompt_path=prompt_path,
                output_path=output_path,
                stderr_path=stderr_path,
                ac_results=ac_results,
                before_repo_outputs=phase_start_repo_outputs,
                before_snapshot=phase_start_snapshot,
                after_snapshot=final_snapshot,
                contract_path=contract_path,
                checklist_path=checklist_path,
                quality_path=phase_attempt_quality_path(task_path, phase_number, attempt),
                evidence_path=phase_attempt_evidence_path(task_path, phase_number, attempt),
                reconciliation_path=phase_attempt_reconciliation_path(task_path, phase_number, attempt),
                reconciliation_summary_path=phase_attempt_reconciliation_summary_path(task_path, phase_number, attempt),
                gate_path=phase_attempt_gate_path(task_path, phase_number, attempt),
            )
            commit_path = write_phase_attempt_commit(task_path, phase_number, attempt, result_path)
            clear_repair_packet(task_path, phase_number)
            append_attempt_manifest_record(
                task_path,
                phase_number,
                attempt,
                "attempt_committed",
                status="committed",
                result=artifact_ref(task_path, "result", result_path),
                attempt_commit=artifact_ref(task_path, "attempt_commit", commit_path),
            )
            append_progress(task_path, f"phase {phase_number}: attempt {attempt} completed")

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
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--ac-timeout", type=int, default=DEFAULT_AC_TIMEOUT)
    parser.add_argument(
        "--codex-idle-timeout",
        type=non_negative_int,
        default=300,
        help="Fail codex exec after this many seconds with no stdout/stderr/stdin or watched file activity. Use 0 to disable.",
    )
    parser.add_argument(
        "--codex-max-runtime",
        type=non_negative_int,
        default=1800,
        help="Fail codex exec after this many wall-clock seconds even if activity continues. Use 0 to disable.",
    )
    parser.add_argument(
        "--runtime-settle-seconds",
        type=non_negative_float,
        default=None,
        help=(
            "Require runner-owned runtime artifacts to stay stable for this many seconds after child commands. "
            "Defaults to 0 unless --strict-current-harness is set."
        ),
    )
    parser.add_argument(
        "--runtime-settle-poll-seconds",
        type=non_negative_float,
        default=DEFAULT_RUNTIME_SETTLE_POLL_SECONDS,
        help="Polling interval for --runtime-settle-seconds.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only build the next prompt.")
    parser.add_argument("--one", action="store_true", help="Run only one pending phase.")
    parser.add_argument(
        "--resume-repair",
        action="store_true",
        help="Reset from the earliest failed phase or repair packet and rerun with the packet in context.",
    )
    parser.add_argument(
        "--from",
        dest="from_phase",
        type=non_negative_int,
        help="Reset terminal phases from this phase number before running.",
    )
    parser.add_argument("--evaluate", action="store_true", help="Run fresh evaluation after all phases complete.")
    parser.add_argument("--eval-command", action="append", default=[], help="Evaluation command.")
    parser.add_argument(
        "--review-iterations",
        type=non_negative_int,
        default=5,
        help="Maximum evaluation improvement iterations when --evaluate returns rejected.",
    )
    parser.add_argument("--skip-install", action="store_true", help="Skip package-manager install preflight.")
    parser.add_argument("--install-timeout", type=non_negative_int, default=600)
    parser.add_argument(
        "--subprocess-timeout",
        type=non_negative_int,
        default=1920,
        help="Timeout for runner-owned verify/evaluate subprocesses. Use 0 to disable.",
    )
    parser.add_argument(
        "--repo-lock-timeout",
        type=non_negative_int,
        default=0,
        help="Wait up to this many seconds for another run-phases repo execution to finish.",
    )
    parser.add_argument("--full-auto", action="store_true", help="Pass --full-auto to codex exec.")
    parser.add_argument("--strict-current-harness", action="store_true", help="Require current harness runtime metadata.")
    parser.add_argument(
        "--doctor-runtime",
        action="store_true",
        help="Diagnose completed phase runtime proof without running phases.",
    )
    parser.add_argument(
        "--backfill-attempt-manifests",
        action="store_true",
        help="With --doctor-runtime, append missing completed-phase attempt_committed manifest records from valid attempt commits.",
    )
    parser.add_argument(
        "--yolo",
        action="store_true",
        help="Pass --dangerously-bypass-approvals-and-sandbox to codex exec.",
    )
    parser.add_argument(
        "--allow-inherited-yolo",
        action="store_true",
        help=(
            "Allow CODEX_HARNESS_CHILD_CODEX_YOLO=1 to enable --yolo. "
            "Prefer explicit --yolo from the launcher."
        ),
    )
    args = parser.parse_args()
    args.failed = False
    args.install_preflight_done = False
    apply_inherited_yolo(args)

    root = Path(args.root).resolve()
    install_errors = harness_install_errors(root)
    if install_errors:
        print("[ERROR] Invalid codex-harness installation:", file=sys.stderr)
        for error in install_errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    task_path = resolve_task_path(root, args.task)
    runner_lock: LockHandle | None = None
    repo_lock: LockHandle | None = None
    try:
        if args.from_phase is not None and args.resume_repair:
            print("--from and --resume-repair cannot be used together.", file=sys.stderr)
            return 1
        if args.backfill_attempt_manifests and not args.doctor_runtime:
            print("--backfill-attempt-manifests requires --doctor-runtime.", file=sys.stderr)
            return 1
        if args.doctor_runtime and not args.backfill_attempt_manifests:
            report = doctor_runtime_proof(root, task_path, apply_backfill=False)
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if report.get("status") == "ok" else 1
        if args.doctor_runtime and args.backfill_attempt_manifests:
            active_execution_check = active_repo_execution_doctor_check(root)
            if active_execution_check is not None:
                report = doctor_runtime_unstable_report(
                    root,
                    task_path,
                    apply_backfill=True,
                    check=active_execution_check,
                )
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
                return 1
        try:
            runner_lock = acquire_runner_lock(task_path, args.dry_run)
            if not args.doctor_runtime or args.backfill_attempt_manifests:
                repo_lock = acquire_repo_execution_lock(root, task_path, args)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        if args.doctor_runtime:
            report = doctor_runtime_proof(
                root,
                task_path,
                apply_backfill=args.backfill_attempt_manifests,
                repo_execution_lock_held=repo_lock is not None,
            )
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if report.get("status") == "ok" else 1
        task_index_override = (
            apply_repair_resume(root, task_path, args.dry_run)
            if args.resume_repair
            else apply_phase_reset(root, task_path, args.from_phase, args.dry_run)
        )
        reconciliation_changes = reconcile_before_execution(root, task_path, args)
        if (
            not args.dry_run
            and any(item.get("to_status") == "error" for item in reconciliation_changes)
        ):
            update_top_index(root, task_path.name, "error")
            args.failed = True
            return 1

        while True:
            progressed = execute_phase(root, task_path, args, task_index_override)
            task_index_override = None
            if args.dry_run or args.one or not progressed:
                break

        task_index = read_json(task_path / "index.json")
        if not args.dry_run and all(phase.get("status") == "completed" for phase in task_index.get("phases", [])):
            if finalize_completed_task(root, task_path, args) != 0:
                return 1
        return 1 if args.failed else 0
    finally:
        release_repo_execution_lock(repo_lock)
        release_runner_lock(runner_lock)


if __name__ == "__main__":
    raise SystemExit(main())
