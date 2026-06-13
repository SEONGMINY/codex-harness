"""Docs review runtime validation and bounded review/cleanup orchestration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from artifact_io import atomic_write_json, atomic_write_text
from codex_exec import run_codex_exec


STATUS_FILENAME = "docs-review-status.json"
MAX_REVIEW_ITERATIONS = 3
VALID_VERDICTS = {"clean", "blocked", "failed"}
VALID_FINDING_SEVERITIES = {"blocker", "warning"}
VALID_FINDING_STATUSES = {"open", "resolved", "rejected"}
FINDING_REQUIRED_FIELDS = {
    "id",
    "severity",
    "category",
    "evidence_file",
    "evidence_summary",
    "auto_fixable",
    "requires_user_decision",
    "status",
}
REQUIRED_DECISION_FIELDS = {
    "id",
    "question",
    "category",
    "evidence_file",
    "evidence_summary",
    "recommended_direction",
    "tradeoffs",
    "blocking_stage",
}
POST_REVIEW_STATIC_FILES = {"design-approval.json"}


def docs_review_status_path(task_path: Path) -> Path:
    return task_path / "context-pack" / "runtime" / STATUS_FILENAME


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_hex_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def _resolve_repo_path(root: Path, raw_path: object, label: str) -> tuple[Path | None, list[str]]:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None, [f"{label} must include a non-empty path."]
    path = Path(raw_path)
    if path.is_absolute():
        return None, [f"{label} path must be repository-relative: {raw_path}"]
    target = (root / path).resolve()
    root_resolved = root.resolve()
    if not _is_relative_to(target, root_resolved):
        return None, [f"{label} path must not escape repository root: {raw_path}"]
    return target, []


def _reviewable_file_errors(root: Path, task_path: Path, target: Path, label: str) -> list[str]:
    task_root = task_path.resolve()
    docs_dir = (task_path / "docs").resolve()
    static_dir = (task_path / "context-pack" / "static").resolve()
    errors: list[str] = []
    if not _is_relative_to(target, task_root):
        errors.append(f"{label} must be inside the task directory: {rel(root, target)}")
    if not (_is_relative_to(target, docs_dir) or _is_relative_to(target, static_dir)):
        errors.append(f"{label} must reference task docs or static context: {rel(root, target)}")
    if not target.exists() or not target.is_file():
        errors.append(f"{label} path does not exist: {rel(root, target)}")
    elif target.is_symlink():
        errors.append(f"{label} path must not be a symlink: {rel(root, target)}")
    return errors


def validate_finding(value: object, label: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} must be an object."]
    errors: list[str] = []
    missing = sorted(FINDING_REQUIRED_FIELDS - set(value))
    if missing:
        errors.append(f"{label} is missing fields: {missing}")
    for key in ["id", "category", "evidence_file", "evidence_summary"]:
        if key in value and (not isinstance(value.get(key), str) or not value.get(key, "").strip()):
            errors.append(f"{label}.{key} must be a non-empty string.")
    if value.get("severity") not in VALID_FINDING_SEVERITIES:
        errors.append(f"{label}.severity must be one of {sorted(VALID_FINDING_SEVERITIES)}.")
    if value.get("status") not in VALID_FINDING_STATUSES:
        errors.append(f"{label}.status must be one of {sorted(VALID_FINDING_STATUSES)}.")
    for key in ["auto_fixable", "requires_user_decision"]:
        if key in value and not isinstance(value.get(key), bool):
            errors.append(f"{label}.{key} must be boolean.")
    return errors


def validate_required_decision(value: object, label: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} must be an object."]
    errors: list[str] = []
    missing = sorted(REQUIRED_DECISION_FIELDS - set(value))
    if missing:
        errors.append(f"{label} is missing fields: {missing}")
    for key in REQUIRED_DECISION_FIELDS - {"tradeoffs"}:
        if key in value and (not isinstance(value.get(key), str) or not value.get(key, "").strip()):
            errors.append(f"{label}.{key} must be a non-empty string.")
    tradeoffs = value.get("tradeoffs")
    if "tradeoffs" in value and (
        not isinstance(tradeoffs, list)
        or not tradeoffs
        or any(not isinstance(item, str) or not item.strip() for item in tradeoffs)
    ):
        errors.append(f"{label}.tradeoffs must be a non-empty list of strings.")
    return errors


def _validate_reviewed_files(root: Path, task_path: Path, reviewed_files: object) -> list[str]:
    if not isinstance(reviewed_files, list) or not reviewed_files:
        return ["docs-review-status.json must include non-empty reviewed_files."]
    errors: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(reviewed_files):
        label = f"reviewed_files[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} must be an object.")
            continue
        raw_path = entry.get("path")
        target, path_errors = _resolve_repo_path(root, raw_path, label)
        errors.extend(path_errors)
        expected_sha = entry.get("sha256")
        if not _is_hex_sha256(expected_sha):
            errors.append(f"{label}.sha256 must be a lowercase sha256 hex digest.")
        if target is None:
            continue
        errors.extend(_reviewable_file_errors(root, task_path, target, label))
        if isinstance(raw_path, str):
            if raw_path in seen:
                errors.append(f"{label}.path is duplicated: {raw_path}")
            seen.add(raw_path)
        if target.exists() and target.is_file() and _is_hex_sha256(expected_sha):
            actual_sha = file_sha256(target)
            if actual_sha != expected_sha:
                errors.append(f"{label}.sha256 does not match current file: {rel(root, target)}")
    expected_paths = {rel(root, path) for path in _task_review_files(root, task_path)}
    missing_paths = sorted(expected_paths - seen)
    if missing_paths:
        errors.append(f"docs-review-status.json reviewed_files is missing current docs/static files: {missing_paths}")
    return errors


def _validate_artifact_refs(root: Path, task_path: Path, artifact_refs: object) -> list[str]:
    if artifact_refs is None:
        return []
    if not isinstance(artifact_refs, list):
        return ["artifact_refs must be a list."]
    errors: list[str] = []
    for index, entry in enumerate(artifact_refs):
        label = f"artifact_refs[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} must be an object.")
            continue
        if not isinstance(entry.get("name"), str) or not entry.get("name", "").strip():
            errors.append(f"{label}.name must be a non-empty string.")
        raw_path = entry.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            errors.append(f"{label}.path must be a non-empty task-relative path.")
            continue
        path = Path(raw_path)
        if path.is_absolute():
            errors.append(f"{label}.path must be task-relative: {raw_path}")
            continue
        target = (task_path / path).resolve()
        if not _is_relative_to(target, task_path.resolve()):
            errors.append(f"{label}.path must not escape task directory: {raw_path}")
            continue
        if not target.exists() or not target.is_file():
            errors.append(f"{label}.path does not exist: {raw_path}")
            continue
        if entry.get("sha256") is not None and not _is_hex_sha256(entry.get("sha256")):
            errors.append(f"{label}.sha256 must be a lowercase sha256 hex digest.")
        elif _is_hex_sha256(entry.get("sha256")) and entry.get("sha256") != file_sha256(target):
            errors.append(f"{label}.sha256 does not match current artifact: {raw_path}")
    return errors


def _artifact_ref_names(artifact_refs: object) -> set[str]:
    if not isinstance(artifact_refs, list):
        return set()
    return {
        item.get("name")
        for item in artifact_refs
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }


def _validate_clean_review_artifact_refs(status: dict[str, object]) -> list[str]:
    if status.get("verdict") != "clean":
        return []
    artifact_refs = status.get("artifact_refs")
    if not isinstance(artifact_refs, list) or not artifact_refs:
        return ["clean docs-review-status.json must include non-empty artifact_refs."]
    attempt = status.get("iterations_completed")
    if not isinstance(attempt, int) or attempt < 1 or attempt > MAX_REVIEW_ITERATIONS:
        return [
            "clean docs-review-status.json iterations_completed must identify a completed reviewer "
            f"attempt between 1 and {MAX_REVIEW_ITERATIONS}."
        ]
    required_refs = {
        f"docs-review-attempt{attempt}-prompt": f"context-pack/runtime/docs-review-attempt{attempt}-prompt.md",
        f"docs-review-attempt{attempt}-output": f"context-pack/runtime/docs-review-attempt{attempt}-output.jsonl",
        f"docs-review-attempt{attempt}-last-message": f"context-pack/runtime/docs-review-attempt{attempt}-last-message.json",
        f"docs-review-findings-attempt{attempt}": f"context-pack/runtime/docs-review-findings-attempt{attempt}.json",
    }
    names = _artifact_ref_names(artifact_refs)
    missing = sorted(set(required_refs) - names)
    errors: list[str] = []
    if missing:
        errors.append(f"clean docs-review-status.json artifact_refs missing reviewer proof artifacts: {missing}")
    by_name = {
        item.get("name"): item
        for item in artifact_refs
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    for name, expected_path in required_refs.items():
        entry = by_name.get(name)
        if not isinstance(entry, dict):
            continue
        if entry.get("path") != expected_path:
            errors.append(f"clean docs-review-status.json artifact_ref {name} must point to {expected_path}.")
        if entry.get("exists") is not True:
            errors.append(f"clean docs-review-status.json artifact_ref {name}.exists must be true.")
        if not _is_hex_sha256(entry.get("sha256")):
            errors.append(f"clean docs-review-status.json artifact_ref {name}.sha256 must be a lowercase sha256 hex digest.")
    return errors


def _finding_ids(findings: list[object]) -> set[str]:
    ids: set[str] = set()
    for item in findings:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.add(item["id"])
    return ids


def _validate_finding_consistency(status: dict[str, object]) -> list[str]:
    findings = status.get("findings")
    open_blockers = status.get("open_blockers")
    resolved_blockers = status.get("resolved_blockers")
    if not isinstance(findings, list) or not isinstance(open_blockers, list) or not isinstance(resolved_blockers, list):
        return []
    derived_open = [
        item
        for item in findings
        if isinstance(item, dict)
        and item.get("severity") == "blocker"
        and item.get("status") == "open"
    ]
    derived_open_ids = _finding_ids(derived_open)
    reported_open_ids = _finding_ids(open_blockers)
    errors: list[str] = []
    if derived_open_ids != reported_open_ids:
        errors.append(
            "docs-review-status.json open_blockers must match open blocker findings. "
            f"expected={sorted(derived_open_ids)} actual={sorted(reported_open_ids)}"
        )
    resolved_ids = _finding_ids(resolved_blockers)
    conflict_ids = sorted(derived_open_ids & resolved_ids)
    if conflict_ids:
        errors.append(f"docs-review-status.json blocker ids cannot be both open and resolved: {conflict_ids}")
    if status.get("verdict") == "clean" and derived_open:
        errors.append("clean docs-review-status.json must not include open blocker findings.")
    return errors


def validate_docs_review_status_object(
    root: Path,
    task_path: Path,
    status: object,
    *,
    require_clean: bool,
) -> list[str]:
    if not isinstance(status, dict):
        return ["docs-review-status.json must be a JSON object."]
    errors: list[str] = []
    required = {
        "schema_version",
        "verdict",
        "max_iterations",
        "iterations_completed",
        "reviewed_at",
        "reviewed_files",
        "findings",
        "resolved_blockers",
        "open_blockers",
        "required_decisions",
        "artifact_refs",
    }
    missing = sorted(required - set(status))
    if missing:
        errors.append(f"docs-review-status.json is missing fields: {missing}")
    if status.get("schema_version") != 1:
        errors.append("docs-review-status.json schema_version must be 1.")
    verdict = status.get("verdict")
    if verdict not in VALID_VERDICTS:
        errors.append(f"docs-review-status.json verdict must be one of {sorted(VALID_VERDICTS)}.")
    if require_clean and verdict != "clean":
        errors.append('docs-review-status.json verdict must be "clean".')
    if status.get("max_iterations") != MAX_REVIEW_ITERATIONS:
        errors.append(f"docs-review-status.json max_iterations must be {MAX_REVIEW_ITERATIONS}.")
    if not isinstance(status.get("iterations_completed"), int) or status.get("iterations_completed", 0) < 0:
        errors.append("docs-review-status.json iterations_completed must be a non-negative integer.")
    if not isinstance(status.get("reviewed_at"), str) or not status.get("reviewed_at", "").strip():
        errors.append("docs-review-status.json reviewed_at must be a non-empty string.")
    errors.extend(_validate_reviewed_files(root, task_path, status.get("reviewed_files")))
    for key in ["findings", "resolved_blockers", "open_blockers"]:
        value = status.get(key)
        if not isinstance(value, list):
            errors.append(f"docs-review-status.json {key} must be a list.")
            continue
        for index, item in enumerate(value):
            errors.extend(validate_finding(item, f"{key}[{index}]"))
    required_decisions = status.get("required_decisions")
    if not isinstance(required_decisions, list):
        errors.append("docs-review-status.json required_decisions must be a list.")
    else:
        for index, item in enumerate(required_decisions):
            errors.extend(validate_required_decision(item, f"required_decisions[{index}]"))
    errors.extend(_validate_finding_consistency(status))
    errors.extend(_validate_blocked_required_decisions(status))
    errors.extend(_validate_artifact_refs(root, task_path, status.get("artifact_refs")))
    errors.extend(_validate_clean_review_artifact_refs(status))
    if verdict == "clean":
        if status.get("open_blockers"):
            errors.append("clean docs-review-status.json must not include open_blockers.")
        if status.get("required_decisions"):
            errors.append("clean docs-review-status.json must not include required_decisions.")
    return errors


def validate_docs_review_status(root: Path, task_path: Path) -> list[str]:
    return validate_docs_review_status_file(root, task_path, require_clean=True)


def validate_docs_review_status_file(root: Path, task_path: Path, *, require_clean: bool) -> list[str]:
    path = docs_review_status_path(task_path)
    if not path.exists():
        return [f"Missing docs review status: {rel(root, path)}"]
    if path.is_symlink():
        return [f"Unsafe docs review status symlink: {rel(root, path)}"]
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid docs review status JSON: {rel(root, path)}: {exc}"]
    return validate_docs_review_status_object(root, task_path, status, require_clean=require_clean)


def _task_review_files(root: Path, task_path: Path) -> list[Path]:
    files: list[Path] = []
    for base in [task_path / "docs", task_path / "context-pack" / "static"]:
        if not base.exists():
            continue
        files.extend(
            path
            for path in sorted(base.rglob("*"))
            if path.is_file()
            and not path.is_symlink()
            and not (
                _is_relative_to(path.resolve(), (task_path / "context-pack" / "static").resolve())
                and path.name in POST_REVIEW_STATIC_FILES
            )
        )
    return files


def reviewed_file_entries(root: Path, task_path: Path) -> list[dict[str, str]]:
    return [{"path": rel(root, path), "sha256": file_sha256(path)} for path in _task_review_files(root, task_path)]


def artifact_ref(task_path: Path, path: Path, name: str) -> dict[str, object]:
    entry: dict[str, object] = {
        "name": name,
        "path": str(path.relative_to(task_path)),
        "exists": path.exists(),
    }
    if path.exists() and path.is_file():
        entry["sha256"] = file_sha256(path)
    return entry


def _write_status(task_path: Path, status: dict[str, object]) -> dict[str, object]:
    atomic_write_json(docs_review_status_path(task_path), status, boundary=task_path)
    return status


def _load_last_message(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _normalize_findings(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _open_blockers(findings: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        item
        for item in findings
        if item.get("severity") == "blocker" and item.get("status", "open") == "open"
    ]


def _required_decision_from_blocker(blocker: dict[str, object]) -> dict[str, object]:
    blocker_id = str(blocker.get("id") or "DR-BLOCKER")
    category = str(blocker.get("category") or "docs_review_blocker")
    evidence_file = str(blocker.get("evidence_file") or "")
    evidence_summary = str(blocker.get("evidence_summary") or "")
    return {
        "id": f"{blocker_id}-decision",
        "question": f"What approved decision resolves docs review blocker {blocker_id}?",
        "category": category,
        "evidence_file": evidence_file,
        "evidence_summary": evidence_summary,
        "recommended_direction": "Provide an explicit approved decision or revise the approved scope; do not let docs cleanup invent it.",
        "tradeoffs": [
            "Keeping the blocker unresolved prevents design approval and phase execution.",
            "Approving a concrete decision lets the next docs review attempt verify the updated artifact.",
        ],
        "blocking_stage": "docs_review",
    }


def concrete_required_decisions(status: dict[str, object]) -> list[dict[str, object]]:
    decisions: list[dict[str, object]] = []
    seen: set[str] = set()

    def add(value: object) -> bool:
        if isinstance(value, dict) and not validate_required_decision(value, "required_decision"):
            decision_id = str(value["id"])
            if decision_id not in seen:
                seen.add(decision_id)
                decisions.append(value)
            return True
        return False

    for item in status.get("required_decisions") or []:
        add(item)
    for blocker in status.get("open_blockers") or []:
        if not isinstance(blocker, dict):
            continue
        has_blocker_decision = add(blocker.get("required_decision"))
        for item in blocker.get("required_decisions") or []:
            has_blocker_decision = add(item) or has_blocker_decision
        if not has_blocker_decision:
            add(_required_decision_from_blocker(blocker))
    return decisions


def _validate_blocked_required_decisions(status: dict[str, object]) -> list[str]:
    if status.get("verdict") != "blocked":
        return []
    required_decisions = status.get("required_decisions")
    if not isinstance(required_decisions, list):
        return []
    recorded_ids = {
        str(item.get("id"))
        for item in required_decisions
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
    }
    missing_ids = [
        str(item.get("id"))
        for item in concrete_required_decisions(status)
        if isinstance(item.get("id"), str) and item.get("id") and str(item.get("id")) not in recorded_ids
    ]
    if missing_ids:
        return [
            "blocked docs-review-status.json required_decisions must include a concrete decision "
            f"for every open blocker; missing ids: {sorted(set(missing_ids))}"
        ]
    return []


def validate_required_decisions(value: object, label: str) -> list[str]:
    if not isinstance(value, list):
        return [f"{label} must be a list."]
    errors: list[str] = []
    for index, item in enumerate(value):
        errors.extend(validate_required_decision(item, f"{label}[{index}]"))
    return errors


def docs_blocked_payload(status: dict[str, object]) -> dict[str, object]:
    open_blockers = status.get("open_blockers") if isinstance(status.get("open_blockers"), list) else []
    return {
        "status": "docs_blocked",
        "verdict": status.get("verdict"),
        "required_decisions": concrete_required_decisions(status),
        "open_blockers": open_blockers,
    }


def _reviewer_prompt(root: Path, task_path: Path, attempt: int) -> str:
    docs = "\n".join(f"- {rel(root, path)}" for path in _task_review_files(root, task_path))
    return f"""# Docs Review Attempt {attempt}

Review the task docs and static context from a fresh context.

Task: {rel(root, task_path)}

Files to review:
{docs}

Return only JSON with:
- verdict: clean, blocked, or failed
- findings: array of finding objects with id, severity, category, evidence_file, evidence_summary, auto_fixable, requires_user_decision, status
- required_decisions: array of concrete decision request objects when a blocker requires user input

Do not invent product, API, schema, storage, dependency, or UX decisions.
"""


def _docs_cleanup_prompt(
    root: Path,
    task_path: Path,
    attempt: int,
    blockers: list[dict[str, object]],
) -> str:
    blockers_json = json.dumps(blockers, ensure_ascii=False, indent=2)
    return f"""# Docs Cleanup Attempt {attempt}

Clean up only the task docs/static context for task {rel(root, task_path)}.

Allowed changes are limited to expression cleanup, approved-decision clarification, and self-contradiction removal.
Do not introduce new product, API, schema, storage, dependency, UX, module-boundary, or lifecycle decisions.

Open auto-fixable blockers:
{blockers_json}

Return only JSON with:
- status: completed or failed
- resolved_finding_ids: array of finding ids
- changed_files: array of repository-relative paths
- notes: string
"""


def _codex_command(args: argparse.Namespace, last_message_path: Path) -> list[str]:
    command = [getattr(args, "codex_bin", None) or "codex", "exec", "--json", "--output-last-message", str(last_message_path)]
    model = getattr(args, "model", None)
    if model:
        command.extend(["--model", str(model)])
    reasoning_effort = getattr(args, "reasoning_effort", None)
    if reasoning_effort:
        command.extend(["--reasoning-effort", str(reasoning_effort)])
    if getattr(args, "full_auto", False):
        command.append("--full-auto")
    if getattr(args, "yolo", False):
        command.append("--dangerously-bypass-approvals-and-sandbox")
    return command


def _run_codex_json(
    root: Path,
    task_path: Path,
    args: argparse.Namespace,
    *,
    prompt: str,
    prompt_path: Path,
    output_path: Path,
    stderr_path: Path,
    last_message_path: Path,
) -> tuple[int, dict[str, object] | None]:
    atomic_write_text(prompt_path, prompt, boundary=task_path)
    returncode = run_codex_exec(
        _codex_command(args, last_message_path),
        cwd=root,
        prompt=prompt,
        output_path=output_path,
        stderr_path=stderr_path,
        idle_timeout=int(getattr(args, "codex_idle_timeout", 300)),
        max_runtime=int(getattr(args, "codex_max_runtime", 1800)),
        activity_paths=[task_path / "docs", task_path / "context-pack" / "static"],
    )
    return returncode, _load_last_message(last_message_path)


def _valid_cleanup_scope(root: Path, task_path: Path, changed_files: object) -> list[str]:
    if not isinstance(changed_files, list):
        return ["docs cleanup changed_files must be a list."]
    errors: list[str] = []
    docs_dir = (task_path / "docs").resolve()
    static_dir = (task_path / "context-pack" / "static").resolve()
    for index, raw_path in enumerate(changed_files):
        target, path_errors = _resolve_repo_path(root, raw_path, f"changed_files[{index}]")
        errors.extend(path_errors)
        if target is None:
            continue
        if not (_is_relative_to(target, docs_dir) or _is_relative_to(target, static_dir)):
            errors.append(f"docs cleanup changed file is outside task docs/static context: {raw_path}")
    return errors


def _repo_file_snapshot(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    root = root.resolve()
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            path = Path(entry.path)
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue
            if entry.is_dir(follow_symlinks=False):
                if entry.name == ".git":
                    continue
                stack.append(path)
                continue
            if entry.is_symlink():
                try:
                    snapshot[relative] = f"symlink:{os.readlink(path)}"
                except OSError:
                    snapshot[relative] = "symlink:<unreadable>"
            elif entry.is_file(follow_symlinks=False):
                try:
                    snapshot[relative] = file_sha256(path)
                except OSError:
                    snapshot[relative] = "<unreadable>"
    return snapshot


def _changed_snapshot_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    paths = set(before) | set(after)
    return sorted(path for path in paths if before.get(path) != after.get(path))


def _valid_actual_cleanup_scope(
    root: Path,
    task_path: Path,
    changed_paths: list[str],
    *,
    runner_owned_paths: set[str],
) -> list[str]:
    errors: list[str] = []
    docs_dir = (task_path / "docs").resolve()
    static_dir = (task_path / "context-pack" / "static").resolve()
    for raw_path in changed_paths:
        if raw_path in runner_owned_paths:
            continue
        target, path_errors = _resolve_repo_path(root, raw_path, f"actual_changed_files[{raw_path}]")
        errors.extend(path_errors)
        if target is None:
            continue
        if not (_is_relative_to(target, docs_dir) or _is_relative_to(target, static_dir)):
            errors.append(f"docs cleanup changed file is outside task docs/static context: {raw_path}")
    return errors


def _valid_actual_reviewer_scope(changed_paths: list[str], *, runner_owned_paths: set[str]) -> list[str]:
    errors: list[str] = []
    for raw_path in changed_paths:
        if raw_path in runner_owned_paths:
            continue
        errors.append(f"reviewer changed file during read-only review: {raw_path}")
    return errors


def _make_status(
    root: Path,
    task_path: Path,
    *,
    verdict: str,
    iterations_completed: int,
    findings: list[dict[str, object]],
    open_blockers: list[dict[str, object]],
    required_decisions: list[dict[str, object]],
    artifact_refs: list[dict[str, object]],
    resolved_blockers: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    resolved = resolved_blockers if resolved_blockers is not None else [
        item
        for item in findings
        if item.get("severity") == "blocker" and item.get("status") == "resolved"
    ]
    return {
        "schema_version": 1,
        "verdict": verdict,
        "max_iterations": MAX_REVIEW_ITERATIONS,
        "iterations_completed": iterations_completed,
        "reviewed_at": now_iso(),
        "reviewed_files": reviewed_file_entries(root, task_path),
        "findings": findings,
        "resolved_blockers": resolved,
        "open_blockers": open_blockers,
        "required_decisions": required_decisions,
        "artifact_refs": artifact_refs,
    }


def _review_failure_status(
    root: Path,
    task_path: Path,
    *,
    attempt: int,
    reason: str,
    artifact_refs: list[dict[str, object]],
) -> dict[str, object]:
    finding = {
        "id": f"DR-RUNTIME-{attempt:03d}",
        "severity": "blocker",
        "category": "review_process_failure",
        "evidence_file": rel(root, task_path / "context-pack" / "runtime"),
        "evidence_summary": reason,
        "auto_fixable": False,
        "requires_user_decision": False,
        "status": "open",
    }
    return _make_status(
        root,
        task_path,
        verdict="failed",
        iterations_completed=attempt,
        findings=[finding],
        open_blockers=[finding],
        required_decisions=[],
        artifact_refs=artifact_refs,
    )


def _can_auto_cleanup(blockers: list[dict[str, object]]) -> bool:
    return all(
        blocker.get("auto_fixable") is True
        and blocker.get("requires_user_decision") is False
        for blocker in blockers
    )


def _merge_findings_by_id(*groups: list[dict[str, object]]) -> list[dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    anonymous: list[dict[str, object]] = []
    for group in groups:
        for item in group:
            item_id = item.get("id")
            if isinstance(item_id, str) and item_id.strip():
                merged[item_id] = item
            else:
                anonymous.append(item)
    return [*merged.values(), *anonymous]


def run_docs_review_loop(root: Path, task_path: Path, args: argparse.Namespace) -> dict[str, object]:
    runtime_dir = task_path / "context-pack" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    artifact_refs: list[dict[str, object]] = []
    last_findings: list[dict[str, object]] = []
    last_open_blockers: list[dict[str, object]] = []
    resolved_blocker_history: list[dict[str, object]] = []
    max_iterations = min(
        MAX_REVIEW_ITERATIONS,
        max(1, int(getattr(args, "docs_review_max_iterations", MAX_REVIEW_ITERATIONS))),
    )

    for attempt in range(1, max_iterations + 1):
        prompt_path = runtime_dir / f"docs-review-attempt{attempt}-prompt.md"
        output_path = runtime_dir / f"docs-review-attempt{attempt}-output.jsonl"
        stderr_path = runtime_dir / f"docs-review-attempt{attempt}-stderr.txt"
        last_message_path = runtime_dir / f"docs-review-attempt{attempt}-last-message.json"
        runner_owned_review_paths = {
            rel(root, prompt_path),
            rel(root, output_path),
            rel(root, stderr_path),
            rel(root, last_message_path),
        }
        before_review_snapshot = _repo_file_snapshot(root)
        returncode, review = _run_codex_json(
            root,
            task_path,
            args,
            prompt=_reviewer_prompt(root, task_path, attempt),
            prompt_path=prompt_path,
            output_path=output_path,
            stderr_path=stderr_path,
            last_message_path=last_message_path,
        )
        after_review_snapshot = _repo_file_snapshot(root)
        actual_review_changed_files = _changed_snapshot_paths(before_review_snapshot, after_review_snapshot)
        review_scope_errors = _valid_actual_reviewer_scope(
            actual_review_changed_files,
            runner_owned_paths=runner_owned_review_paths,
        )
        artifact_refs.extend(
            [
                artifact_ref(task_path, prompt_path, f"docs-review-attempt{attempt}-prompt"),
                artifact_ref(task_path, output_path, f"docs-review-attempt{attempt}-output"),
                artifact_ref(task_path, last_message_path, f"docs-review-attempt{attempt}-last-message"),
            ]
        )
        findings_path = runtime_dir / f"docs-review-findings-attempt{attempt}.json"
        if review_scope_errors:
            reason = "reviewer attempted file changes during read-only review: " + "; ".join(review_scope_errors)
            atomic_write_json(
                findings_path,
                {
                    "status": "failed",
                    "reason": reason,
                    "actual_changed_files": actual_review_changed_files,
                    "scope_errors": review_scope_errors,
                },
                boundary=task_path,
            )
            artifact_refs.append(artifact_ref(task_path, findings_path, f"docs-review-findings-attempt{attempt}"))
            return _write_status(
                task_path,
                _review_failure_status(
                    root,
                    task_path,
                    attempt=attempt,
                    reason=reason,
                    artifact_refs=artifact_refs,
                ),
            )
        if returncode != 0 or review is None:
            reason = f"reviewer attempt {attempt} failed or returned invalid JSON"
            atomic_write_json(findings_path, {"status": "failed", "reason": reason}, boundary=task_path)
            artifact_refs.append(artifact_ref(task_path, findings_path, f"docs-review-findings-attempt{attempt}"))
            return _write_status(
                task_path,
                _review_failure_status(
                    root,
                    task_path,
                    attempt=attempt,
                    reason=reason,
                    artifact_refs=artifact_refs,
                ),
            )
        reviewer_verdict = review.get("verdict")
        if reviewer_verdict not in VALID_VERDICTS:
            atomic_write_json(findings_path, review, boundary=task_path)
            artifact_refs.append(artifact_ref(task_path, findings_path, f"docs-review-findings-attempt{attempt}"))
            return _write_status(
                task_path,
                _review_failure_status(
                    root,
                    task_path,
                    attempt=attempt,
                    reason=f"reviewer output verdict must be one of {sorted(VALID_VERDICTS)}",
                    artifact_refs=artifact_refs,
                ),
            )
        raw_findings = review.get("findings")
        if not isinstance(raw_findings, list):
            atomic_write_json(findings_path, review, boundary=task_path)
            artifact_refs.append(artifact_ref(task_path, findings_path, f"docs-review-findings-attempt{attempt}"))
            return _write_status(
                task_path,
                _review_failure_status(
                    root,
                    task_path,
                    attempt=attempt,
                    reason="reviewer output findings must be a list",
                    artifact_refs=artifact_refs,
                ),
            )
        findings = _normalize_findings(raw_findings)
        findings_errors: list[str] = []
        if len(findings) != len(raw_findings):
            findings_errors.append("all findings must be objects")
        for index, finding in enumerate(findings):
            findings_errors.extend(validate_finding(finding, f"findings[{index}]"))
        atomic_write_json(findings_path, review, boundary=task_path)
        artifact_refs.append(artifact_ref(task_path, findings_path, f"docs-review-findings-attempt{attempt}"))
        if findings_errors:
            return _write_status(
                task_path,
                _review_failure_status(
                    root,
                    task_path,
                    attempt=attempt,
                    reason="reviewer output failed finding schema validation: " + "; ".join(findings_errors),
                    artifact_refs=artifact_refs,
                ),
            )
        last_findings = findings
        last_open_blockers = _open_blockers(findings)
        if reviewer_verdict == "failed":
            return _write_status(
                task_path,
                _review_failure_status(
                    root,
                    task_path,
                    attempt=attempt,
                    reason="reviewer returned failed verdict",
                    artifact_refs=artifact_refs,
                ),
            )
        if reviewer_verdict == "blocked" and not last_open_blockers:
            return _write_status(
                task_path,
                _review_failure_status(
                    root,
                    task_path,
                    attempt=attempt,
                    reason="reviewer returned blocked verdict without open blockers",
                    artifact_refs=artifact_refs,
                ),
            )
        raw_required_decisions = review.get("required_decisions", [])
        required_decision_errors = validate_required_decisions(
            raw_required_decisions,
            "required_decisions",
        )
        if required_decision_errors:
            return _write_status(
                task_path,
                _review_failure_status(
                    root,
                    task_path,
                    attempt=attempt,
                    reason="reviewer output failed required_decisions schema validation: "
                    + "; ".join(required_decision_errors),
                    artifact_refs=artifact_refs,
                ),
            )
        reviewer_required_decisions = [item for item in raw_required_decisions if isinstance(item, dict)]
        if not last_open_blockers:
            reviewer_resolved_blockers = [
                item
                for item in findings
                if item.get("severity") == "blocker" and item.get("status") == "resolved"
            ]
            status = _make_status(
                root,
                task_path,
                verdict="clean",
                iterations_completed=attempt,
                findings=findings,
                open_blockers=[],
                required_decisions=[],
                artifact_refs=artifact_refs,
                resolved_blockers=_merge_findings_by_id(resolved_blocker_history, reviewer_resolved_blockers),
            )
            return _write_status(task_path, status)
        blocked_candidate = _make_status(
            root,
            task_path,
            verdict="blocked",
            iterations_completed=attempt,
            findings=findings,
            open_blockers=last_open_blockers,
            required_decisions=reviewer_required_decisions,
            artifact_refs=artifact_refs,
        )
        if reviewer_required_decisions or not _can_auto_cleanup(last_open_blockers) or attempt >= max_iterations:
            blocked_candidate["required_decisions"] = concrete_required_decisions(blocked_candidate)
            return _write_status(task_path, blocked_candidate)

        cleanup_prompt_path = runtime_dir / f"docs-improve-attempt{attempt}-prompt.md"
        cleanup_output_path = runtime_dir / f"docs-improve-attempt{attempt}-output.jsonl"
        cleanup_stderr_path = runtime_dir / f"docs-improve-attempt{attempt}-stderr.txt"
        cleanup_last_message_path = runtime_dir / f"docs-improve-attempt{attempt}-last-message.json"
        runner_owned_paths = {
            rel(root, cleanup_prompt_path),
            rel(root, cleanup_output_path),
            rel(root, cleanup_stderr_path),
            rel(root, cleanup_last_message_path),
        }
        before_cleanup_snapshot = _repo_file_snapshot(root)
        cleanup_returncode, cleanup = _run_codex_json(
            root,
            task_path,
            args,
            prompt=_docs_cleanup_prompt(root, task_path, attempt, last_open_blockers),
            prompt_path=cleanup_prompt_path,
            output_path=cleanup_output_path,
            stderr_path=cleanup_stderr_path,
            last_message_path=cleanup_last_message_path,
        )
        after_cleanup_snapshot = _repo_file_snapshot(root)
        actual_changed_files = _changed_snapshot_paths(before_cleanup_snapshot, after_cleanup_snapshot)
        cleanup_result_path = runtime_dir / f"docs-improvement-attempt{attempt}.json"
        artifact_refs.extend(
            [
                artifact_ref(task_path, cleanup_prompt_path, f"docs-improve-attempt{attempt}-prompt"),
                artifact_ref(task_path, cleanup_output_path, f"docs-improve-attempt{attempt}-output"),
                artifact_ref(task_path, cleanup_last_message_path, f"docs-improve-attempt{attempt}-last-message"),
            ]
        )
        if cleanup_returncode != 0 or not isinstance(cleanup, dict):
            reason = f"docs cleanup attempt {attempt} failed or returned invalid JSON"
            atomic_write_json(cleanup_result_path, {"status": "failed", "reason": reason}, boundary=task_path)
            artifact_refs.append(artifact_ref(task_path, cleanup_result_path, f"docs-improvement-attempt{attempt}"))
            return _write_status(
                task_path,
                _review_failure_status(
                    root,
                    task_path,
                    attempt=attempt,
                    reason=reason,
                    artifact_refs=artifact_refs,
                ),
            )
        scope_errors = _valid_cleanup_scope(root, task_path, cleanup.get("changed_files"))
        scope_errors.extend(
            _valid_actual_cleanup_scope(
                root,
                task_path,
                actual_changed_files,
                runner_owned_paths=runner_owned_paths,
            )
        )
        cleanup_record = dict(cleanup)
        cleanup_record["actual_changed_files"] = actual_changed_files
        if scope_errors:
            cleanup_record["scope_errors"] = scope_errors
        atomic_write_json(cleanup_result_path, cleanup_record, boundary=task_path)
        artifact_refs.append(artifact_ref(task_path, cleanup_result_path, f"docs-improvement-attempt{attempt}"))
        if scope_errors or cleanup.get("status") != "completed":
            reason = "docs cleanup attempt failed"
            if scope_errors:
                reason = "docs cleanup attempted out-of-scope changes: " + "; ".join(scope_errors)
            return _write_status(
                task_path,
                _review_failure_status(
                    root,
                    task_path,
                    attempt=attempt,
                    reason=reason,
                    artifact_refs=artifact_refs,
                ),
            )
        resolved_ids = cleanup.get("resolved_finding_ids")
        if isinstance(resolved_ids, list):
            resolved_id_set = {item for item in resolved_ids if isinstance(item, str)}
            resolved_blocker_history = _merge_findings_by_id(
                resolved_blocker_history,
                [
                    {**blocker, "status": "resolved"}
                    for blocker in last_open_blockers
                    if blocker.get("id") in resolved_id_set
                ],
            )

    blocked_status = _make_status(
        root,
        task_path,
        verdict="blocked",
        iterations_completed=max_iterations,
        findings=last_findings,
        open_blockers=last_open_blockers,
        required_decisions=[],
        artifact_refs=artifact_refs,
        resolved_blockers=resolved_blocker_history,
    )
    blocked_status["required_decisions"] = concrete_required_decisions(blocked_status)
    return _write_status(task_path, blocked_status)
