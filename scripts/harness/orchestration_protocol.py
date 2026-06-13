"""Validation helpers for main-session orchestration artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime_protocol import runtime_artifact_ref_errors


VALID_JOURNAL_RECORD_TYPES = {
    "assumption_stated",
    "sub_thread_opened",
    "sub_thread_output_collected",
    "artifact_updated",
    "verifier_run",
    "approval_requested",
    "status_decided",
}

VALID_FAILURE_STATUSES = {"blocked", "failed", "interrupted"}
FORBIDDEN_INQUIRY_TYPES = {
    "planner",
    "architect",
    "reviewer",
    "improver",
    "refactorer",
    "qa",
    "verifier",
    "project_manager",
    "memory_keeper",
}


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_artifact_refs(task_path: Path, value: object, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return [f"{label} must be a list."]
    errors: list[str] = []
    for index, item in enumerate(value):
        errors.extend(runtime_artifact_ref_errors(task_path, item, f"{label}[{index}]"))
    return errors


def orchestration_journal_record_errors(
    task_path: Path,
    record: object,
    *,
    label: str = "orchestration journal record",
) -> list[str]:
    if not isinstance(record, dict):
        return [f"{label} must be a JSON object."]

    errors: list[str] = []
    if record.get("schema_version") != 1:
        errors.append(f"{label} schema_version must be 1.")
    if record.get("artifact_kind") != "orchestration_journal_record":
        errors.append(f'{label} artifact_kind must be "orchestration_journal_record".')

    record_type = record.get("record_type")
    if record_type not in VALID_JOURNAL_RECORD_TYPES:
        errors.append(f"{label} record_type is invalid: {record_type!r}.")

    if record.get("actor") != "main_session":
        errors.append(f'{label} actor must be "main_session".')
    if not _non_empty_string(record.get("timestamp")):
        errors.append(f"{label} timestamp must be a non-empty string.")
    if not _non_empty_string(record.get("summary")):
        errors.append(f"{label} summary must be a non-empty string.")

    if record_type in {"sub_thread_opened", "sub_thread_output_collected"}:
        if not _non_empty_string(record.get("thread_id")):
            errors.append(f"{label} thread_id is required for {record_type}.")
        inquiry_type = record.get("inquiry_type")
        if not _non_empty_string(inquiry_type):
            errors.append(f"{label} inquiry_type is required for {record_type}.")
        elif str(inquiry_type).strip().lower() in FORBIDDEN_INQUIRY_TYPES:
            errors.append(f"{label} inquiry_type must describe a bounded inquiry, not a persistent role.")
        for key in ["bounded_question", "scope_summary", "main_decision_ref"]:
            if not _non_empty_string(record.get(key)):
                errors.append(f"{label} {key} is required for {record_type}.")

    errors.extend(_validate_artifact_refs(task_path, record.get("input_artifacts"), f"{label}.input_artifacts"))
    errors.extend(_validate_artifact_refs(task_path, record.get("output_artifacts"), f"{label}.output_artifacts"))
    return errors


def failure_state_record_errors(
    task_path: Path,
    record: object,
    *,
    label: str = "failure state record",
) -> list[str]:
    if not isinstance(record, dict):
        return [f"{label} must be a JSON object."]

    errors: list[str] = []
    if record.get("schema_version") != 1:
        errors.append(f"{label} schema_version must be 1.")
    if record.get("artifact_kind") != "orchestration_failure_state":
        errors.append(f'{label} artifact_kind must be "orchestration_failure_state".')

    status = record.get("status")
    if status not in VALID_FAILURE_STATUSES:
        errors.append(f"{label} status is invalid: {status!r}.")

    for key in ["observed_by", "reason", "affected_scope", "next_required_action"]:
        if not _non_empty_string(record.get(key)):
            errors.append(f"{label} {key} must be a non-empty string.")

    if status == "interrupted" and record.get("partial_output_promoted_to_proof") is not False:
        errors.append(f"{label} interrupted records must set partial_output_promoted_to_proof to false.")

    phase = record.get("phase")
    if phase is not None and (not isinstance(phase, int) or phase < 0):
        errors.append(f"{label} phase must be a non-negative integer when present.")

    thread_id = record.get("thread_id")
    if thread_id is not None and not _non_empty_string(thread_id):
        errors.append(f"{label} thread_id must be a non-empty string when present.")

    errors.extend(_validate_artifact_refs(task_path, record.get("input_artifacts"), f"{label}.input_artifacts"))
    errors.extend(_validate_artifact_refs(task_path, record.get("output_artifacts"), f"{label}.output_artifacts"))
    return errors


def read_orchestration_journal_records_with_errors(
    task_path: Path,
    path: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.exists():
        return [], []

    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        label = f"orchestration journal record at line {line_number}"
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"Invalid orchestration journal JSON at line {line_number}: {exc}")
            continue
        if isinstance(record, dict):
            records.append(record)
            errors.extend(orchestration_journal_record_errors(task_path, record, label=label))
        else:
            errors.append(f"{label} must be a JSON object.")
    return records, errors
