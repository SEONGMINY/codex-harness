"""Shared runtime artifact and attempt-manifest protocol helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


TERMINAL_ATTEMPT_RECORD_TYPES = {"attempt_committed", "attempt_failed", "attempt_interrupted"}


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def phase_attempt_manifest_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-attempt-manifest.jsonl"


def resolve_task_artifact_path(task_path: Path, raw_path: object) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path:
        return None
    path = Path(raw_path)
    if path.is_absolute():
        return None
    target = (task_path / path).resolve()
    try:
        target.relative_to(task_path.resolve())
    except ValueError:
        return None
    return target


def task_relative(path: Path, task_path: Path) -> str:
    return str(path.relative_to(task_path))


def artifact_ref(task_path: Path, name: str, path: Path) -> dict[str, object]:
    entry: dict[str, object] = {
        "name": name,
        "path": task_relative(path, task_path),
        "exists": path.exists(),
    }
    if path.exists() and path.is_file():
        entry["sha256"] = file_sha256(path)
    return entry


def read_attempt_manifest_records_with_errors(
    task_path: Path,
    phase_number: int,
    *,
    invalid_json_prefix: str | None = None,
    non_object_prefix: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    path = phase_attempt_manifest_path(task_path, phase_number)
    if not path.exists():
        return [], []
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            if invalid_json_prefix:
                errors.append(f"{invalid_json_prefix}:{line_number}: {exc}")
            else:
                errors.append(f"Invalid phase {phase_number} attempt manifest JSON at line {line_number}.")
            continue
        if isinstance(record, dict):
            records.append(record)
        elif non_object_prefix:
            errors.append(f"{non_object_prefix}:{line_number}")
        else:
            errors.append(f"Phase {phase_number} attempt manifest record at line {line_number} must be a JSON object.")
    return records, errors


def runtime_artifact_ref_errors(
    task_path: Path,
    ref: object,
    label: str,
    *,
    expected_name: str | None = None,
    expected_path: str | None = None,
) -> list[str]:
    if not isinstance(ref, dict):
        return [f"{label} must be an artifact reference."]
    errors: list[str] = []
    if expected_name is not None and ref.get("name") != expected_name:
        errors.append(f"{label} name must be {expected_name}.")
    raw_path = ref.get("path")
    if expected_path is not None and raw_path != expected_path:
        errors.append(f"{label} path must be {expected_path}.")
    if not isinstance(raw_path, str) or not raw_path:
        errors.append(f"{label} path must be a non-empty string.")
        return errors
    target = resolve_task_artifact_path(task_path, raw_path)
    if target is None:
        errors.append(f"{label}.path must stay inside the task directory.")
        return errors
    exists = ref.get("exists")
    if exists is True:
        if not target.exists() or not target.is_file():
            errors.append(f"{label} path does not exist: {target}")
        elif ref.get("sha256") != file_sha256(target):
            errors.append(f"{label} sha256 does not match current artifact.")
    elif exists is False:
        if target.exists():
            errors.append(f"{label} exists is false but path exists: {target}")
    else:
        errors.append(f"{label} exists must be true or false.")
    return errors


def attempt_manifest_semantic_errors(
    task_path: Path,
    phase_number: int,
    records: list[dict[str, Any]],
    *,
    label_prefix: str | None = None,
) -> list[str]:
    errors: list[str] = []
    terminal_by_attempt: dict[int, list[str]] = {}
    for index, record in enumerate(records):
        label = label_prefix.format(phase=phase_number, index=index + 1) if label_prefix else f"Phase {phase_number} attempt manifest record {index + 1}"
        if record.get("schema_version") != 1:
            errors.append(f"{label} schema_version must be 1.")
        if record.get("artifact_kind") != "phase_attempt_manifest_record":
            errors.append(f'{label} artifact_kind must be "phase_attempt_manifest_record".')
        record_type = record.get("record_type")
        if record_type not in {"attempt_started", *TERMINAL_ATTEMPT_RECORD_TYPES}:
            errors.append(f"{label} record_type is invalid: {record_type!r}.")
        if record.get("phase") != phase_number:
            errors.append(f"{label} phase must be {phase_number}.")
        attempt = record.get("attempt")
        if not isinstance(attempt, int) or attempt <= 0:
            errors.append(f"{label} attempt must be a positive integer.")
            continue
        if isinstance(record_type, str) and record_type in TERMINAL_ATTEMPT_RECORD_TYPES:
            terminal_by_attempt.setdefault(attempt, []).append(record_type)
        if record_type == "attempt_committed":
            for artifact_key in ["result", "attempt_commit"]:
                if artifact_key not in record:
                    errors.append(f"{label}.{artifact_key} is required for attempt_committed records.")
        elif record_type in {"attempt_failed", "attempt_interrupted"}:
            for artifact_key in ["repair_packet", "repair_packet_summary"]:
                if artifact_key not in record:
                    errors.append(f"{label}.{artifact_key} is required for {record_type} records.")
        for artifact_key in ["result", "attempt_commit", "repair_packet", "repair_packet_summary"]:
            if artifact_key in record:
                errors.extend(
                    runtime_artifact_ref_errors(
                        task_path,
                        record.get(artifact_key),
                        f"{label}.{artifact_key}",
                        expected_name=artifact_key,
                    )
                )
        artifacts = record.get("artifacts")
        if isinstance(artifacts, list):
            for artifact_index, artifact in enumerate(artifacts):
                errors.extend(
                    runtime_artifact_ref_errors(
                        task_path,
                        artifact,
                        f"{label}.artifacts[{artifact_index}]",
                    )
                )
        elif "artifacts" in record:
            errors.append(f"{label}.artifacts must be a list.")
    for attempt, terminal_types in terminal_by_attempt.items():
        if len(terminal_types) > 1:
            errors.append(
                f"Phase {phase_number} attempt {attempt} has multiple terminal manifest records: "
                + ", ".join(terminal_types)
            )
    return errors
