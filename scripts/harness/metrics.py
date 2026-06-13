#!/usr/bin/env python3
"""Generate read-only diagnostic metrics from harness runtime artifacts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scope_policy import path_allowed
from task_paths import resolve_task_path


SCHEMA_VERSION = 1
UNKNOWN = "unknown"
PHASE_FILE_RE = re.compile(r"phase(?P<phase>\d+)\.md$")
PHASE_ARTIFACT_RE = re.compile(r"^phase(?P<phase>\d+)-")
ATTEMPT_ARTIFACT_RE = re.compile(r"^phase(?P<phase>\d+)-(?P<kind>[a-z-]+)-attempt(?P<attempt>\d+)")
RESULT_ATTEMPT_RE = re.compile(r"^phase(?P<phase>\d+)-result-attempt(?P<attempt>\d+)\.json$")
REPAIR_ATTEMPT_RE = re.compile(r"^phase(?P<phase>\d+)-repair-packet-attempt(?P<attempt>\d+)\.json$")
PROTECTED_PATH_PATTERNS = [
    "tasks/*/context-pack/runtime/**",
    "tasks/*/context-pack/static/**",
    "tasks/*/index.json",
    "tasks/index.json",
]
CONDITIONALLY_PROTECTED_PATH_PATTERNS = [
    "scripts/harness/run-phases.py",
    "scripts/harness/verify-task.py",
    "scripts/harness/start.py",
    "scripts/harness/evaluate-task.py",
]
PROTECTED_PATH_SUBSTRINGS = [
    "approval",
    "hash",
    "proof",
    "preflight",
    "verifier",
]


def read_json(path: Path, warnings: list[str]) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        warnings.append(f"invalid_json:{path}: {exc}")
        return None
    if not isinstance(value, dict):
        warnings.append(f"non_object_json:{path}")
        return None
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def runtime_dir(task_path: Path) -> Path:
    return task_path / "context-pack" / "runtime"


def phase_file(task_path: Path, phase_number: int) -> Path:
    return task_path / "phases" / f"phase{phase_number}.md"


def phase_result_path(task_path: Path, phase_number: int) -> Path:
    return runtime_dir(task_path) / f"phase{phase_number}-result.json"


def phase_attempt_result_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return runtime_dir(task_path) / f"phase{phase_number}-result-attempt{attempt}.json"


def phase_attempt_manifest_path(task_path: Path, phase_number: int) -> Path:
    return runtime_dir(task_path) / f"phase{phase_number}-attempt-manifest.jsonl"


def phase_gate_path(task_path: Path, phase_number: int) -> Path:
    return runtime_dir(task_path) / f"phase{phase_number}-gate.json"


def phase_attempt_gate_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return runtime_dir(task_path) / f"phase{phase_number}-gate-attempt{attempt}.json"


def phase_attempt_ac_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return runtime_dir(task_path) / f"phase{phase_number}-ac-attempt{attempt}.json"


def phase_evidence_path(task_path: Path, phase_number: int) -> Path:
    return runtime_dir(task_path) / f"phase{phase_number}-evidence.json"


def phase_attempt_evidence_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return runtime_dir(task_path) / f"phase{phase_number}-evidence-attempt{attempt}.json"


def phase_attempt_prompt_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return runtime_dir(task_path) / f"phase{phase_number}-prompt-attempt{attempt}.md"


def phase_attempt_output_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return runtime_dir(task_path) / f"phase{phase_number}-output-attempt{attempt}.jsonl"


def phase_attempt_stderr_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return runtime_dir(task_path) / f"phase{phase_number}-stderr-attempt{attempt}.txt"


def phase_contract_path(task_path: Path, phase_number: int) -> Path:
    return runtime_dir(task_path) / f"phase{phase_number}-contract.json"


def phase_attempt_contract_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return runtime_dir(task_path) / f"phase{phase_number}-contract-attempt{attempt}.json"


def safe_size(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    return path.stat().st_size


def runtime_size(task_path: Path) -> int:
    root = runtime_dir(task_path)
    if not root.exists():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def phase_artifact_size(task_path: Path, phase_number: int) -> int:
    root = runtime_dir(task_path)
    if not root.exists():
        return 0
    prefix = f"phase{phase_number}-"
    return sum(path.stat().st_size for path in root.iterdir() if path.is_file() and path.name.startswith(prefix))


def discover_phase_numbers(task_path: Path) -> list[int]:
    phase_numbers: set[int] = set()
    phases_dir = task_path / "phases"
    if phases_dir.exists():
        for path in phases_dir.iterdir():
            match = PHASE_FILE_RE.match(path.name)
            if match:
                phase_numbers.add(int(match.group("phase")))
    root = runtime_dir(task_path)
    if root.exists():
        for path in root.iterdir():
            match = PHASE_ARTIFACT_RE.match(path.name)
            if match:
                phase_numbers.add(int(match.group("phase")))
    return sorted(phase_numbers)


def parse_phase_name(task_path: Path, phase_number: int, warnings: list[str]) -> str | None:
    path = phase_file(task_path, phase_number)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        prefix = f"# Phase {phase_number}:"
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip() or None
        if stripped.startswith("# "):
            return stripped[2:].strip() or None
    contract = extract_phase_contract(text, warnings, path)
    if contract and isinstance(contract.get("name"), str):
        return contract["name"].strip() or None
    return None


def extract_phase_contract(text: str, warnings: list[str], path: Path) -> dict[str, Any] | None:
    marker = "```json"
    start = text.find(marker)
    if start < 0:
        return None
    start = text.find("\n", start)
    if start < 0:
        return None
    end = text.find("```", start + 1)
    if end < 0:
        return None
    raw = text[start:end].strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        warnings.append(f"invalid_phase_contract:{path}: {exc}")
        return None
    return value if isinstance(value, dict) else None


def read_attempt_manifest(task_path: Path, phase_number: int, warnings: list[str]) -> list[dict[str, Any]]:
    path = phase_attempt_manifest_path(task_path, phase_number)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            warnings.append(f"invalid_attempt_manifest:{path}:{line_number}: {exc}")
            continue
        if isinstance(value, dict):
            records.append(value)
        else:
            warnings.append(f"non_object_attempt_manifest:{path}:{line_number}")
    return records


def attempts_from_artifacts(task_path: Path, phase_number: int) -> set[int]:
    attempts: set[int] = set()
    root = runtime_dir(task_path)
    if not root.exists():
        return attempts
    for path in root.iterdir():
        for pattern in [ATTEMPT_ARTIFACT_RE, RESULT_ATTEMPT_RE, REPAIR_ATTEMPT_RE]:
            match = pattern.match(path.name)
            if match and int(match.group("phase")) == phase_number:
                attempts.add(int(match.group("attempt")))
    return attempts


def attempt_count(task_path: Path, phase_number: int, records: list[dict[str, Any]]) -> int:
    attempts = {item.get("attempt") for item in records if isinstance(item.get("attempt"), int)}
    attempts.update(attempts_from_artifacts(task_path, phase_number))
    return len(attempts)


def latest_attempt(task_path: Path, phase_number: int, records: list[dict[str, Any]], result: dict[str, Any] | None) -> int | None:
    if result and isinstance(result.get("attempt"), int):
        return result["attempt"]
    attempts = {item.get("attempt") for item in records if isinstance(item.get("attempt"), int)}
    attempts.update(attempts_from_artifacts(task_path, phase_number))
    return max(attempts) if attempts else None


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def duration_seconds(records: list[dict[str, Any]]) -> float | None:
    timestamps = [
        parsed
        for record in records
        for parsed in [parse_timestamp(record.get("recorded_at") or record.get("started_at") or record.get("created_at"))]
        if parsed is not None
    ]
    if len(timestamps) < 2:
        return None
    timestamps.sort()
    return round((timestamps[-1] - timestamps[0]).total_seconds(), 3)


def status_value(value: object) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return UNKNOWN


def check_status(gate: dict[str, Any] | None, name: str) -> str:
    if not gate:
        return UNKNOWN
    checks = gate.get("checks")
    if not isinstance(checks, list):
        return UNKNOWN
    statuses = [
        status_value(item.get("status"))
        for item in checks
        if isinstance(item, dict) and item.get("name") == name
    ]
    return statuses[0] if statuses else UNKNOWN


def ac_status(ac: dict[str, Any] | None) -> str:
    if not ac:
        return UNKNOWN
    if isinstance(ac.get("status"), str):
        return status_value(ac.get("status"))
    for key in ["commands", "command_results", "results"]:
        values = ac.get(key)
        if isinstance(values, list):
            commands = [item for item in values if isinstance(item, dict)]
            if not commands:
                return "passed"
            failed = [
                item
                for item in commands
                if item.get("exit_code") not in {0, None} or item.get("timed_out") is True
            ]
            return "failed" if failed else "passed"
    return UNKNOWN


def list_changed_files(result: dict[str, Any] | None, evidence: dict[str, Any] | None) -> list[str]:
    for source in [result, evidence]:
        if not source:
            continue
        direct = source.get("changed_files")
        if isinstance(direct, list):
            return sorted({item for item in direct if isinstance(item, str)})
        repo_content = source.get("repo_content")
        if isinstance(repo_content, dict) and isinstance(repo_content.get("changed_files"), list):
            paths = []
            for item in repo_content["changed_files"]:
                if isinstance(item, dict) and isinstance(item.get("path"), str):
                    paths.append(item["path"])
                elif isinstance(item, str):
                    paths.append(item)
            return sorted(set(paths))
    return []


def scope_violations(gate: dict[str, Any] | None, evidence: dict[str, Any] | None) -> list[str]:
    if gate and isinstance(gate.get("checks"), list):
        for item in gate["checks"]:
            if isinstance(item, dict) and item.get("name") == "scope":
                violations = item.get("violations")
                if isinstance(violations, list):
                    return sorted({value for value in violations if isinstance(value, str)})
    if evidence and isinstance(evidence.get("scope_violations"), list):
        return sorted({value for value in evidence["scope_violations"] if isinstance(value, str)})
    return []


def required_status(gate: dict[str, Any] | None, name: str, evidence: dict[str, Any] | None, evidence_key: str) -> str:
    gate_status = check_status(gate, name)
    if gate_status != UNKNOWN:
        return gate_status
    values = evidence.get(evidence_key) if evidence else None
    if isinstance(values, list):
        entries = [item for item in values if isinstance(item, dict)]
        if not entries:
            return "passed"
        return "passed" if all(item.get("exists") is True for item in entries) else "failed"
    return UNKNOWN


def allowed_paths_from_contract(task_path: Path, phase_number: int, latest: int | None, warnings: list[str]) -> list[str]:
    contract = None
    if latest is not None:
        contract = read_json(phase_attempt_contract_path(task_path, phase_number, latest), warnings)
    if contract is None:
        contract = read_json(phase_contract_path(task_path, phase_number), warnings)
    if contract is None:
        text_path = phase_file(task_path, phase_number)
        if text_path.exists():
            contract = extract_phase_contract(text_path.read_text(encoding="utf-8", errors="replace"), warnings, text_path)
    if not isinstance(contract, dict):
        return []
    scope = contract.get("scope")
    if isinstance(scope, dict) and isinstance(scope.get("allowed_paths"), list):
        return [item for item in scope["allowed_paths"] if isinstance(item, str) and item.strip()]
    if isinstance(contract.get("allowed_paths"), list):
        return [item for item in contract["allowed_paths"] if isinstance(item, str) and item.strip()]
    return []


def repair_packet_count(task_path: Path, phase_number: int) -> int:
    root = runtime_dir(task_path)
    if not root.exists():
        return 0
    return sum(
        1
        for path in root.iterdir()
        if path.is_file()
        and (match := REPAIR_ATTEMPT_RE.match(path.name))
        and int(match.group("phase")) == phase_number
    )


def infer_failure_class(task_path: Path, phase_number: int, result: dict[str, Any] | None) -> str | None:
    if result and isinstance(result.get("failure"), dict) and isinstance(result["failure"].get("type"), str):
        return result["failure"]["type"]
    if result and isinstance(result.get("failure_type"), str):
        return result["failure_type"]
    packet_paths = sorted(runtime_dir(task_path).glob(f"phase{phase_number}-repair-packet-attempt*.json"))
    if packet_paths:
        try:
            packet = json.loads(packet_paths[-1].read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            return UNKNOWN
        if isinstance(packet, dict):
            failure = packet.get("failure")
            if isinstance(failure, dict) and isinstance(failure.get("type"), str):
                return failure["type"]
    if (runtime_dir(task_path) / f"phase{phase_number}-last-error.md").exists():
        return UNKNOWN
    return None


def infer_execution_mode(
    task_path: Path,
    phase_number: int,
    latest: int | None,
    result: dict[str, Any] | None,
    warnings: list[str],
) -> str:
    for key in ["execution_mode", "mode"]:
        if result and isinstance(result.get(key), str) and result[key].strip():
            return result[key].strip()
    if result and isinstance(result.get("failure"), dict):
        failure_type = result["failure"].get("type")
        if failure_type == "codex_thread":
            return "codex_thread"
        if failure_type == "codex_exec":
            return "codex_exec"
    paths = []
    if latest is not None:
        paths.extend(
            [
                phase_attempt_output_path(task_path, phase_number, latest),
                phase_attempt_stderr_path(task_path, phase_number, latest),
            ]
        )
    paths.extend(sorted(runtime_dir(task_path).glob(f"phase{phase_number}-output-attempt*.jsonl")))
    paths.extend(sorted(runtime_dir(task_path).glob(f"phase{phase_number}-stderr-attempt*.txt")))
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")[:200_000]
        for path in paths
        if path.exists() and path.is_file()
    )
    lowered = text.lower()
    if "thread_final" in lowered or "codex_thread" in lowered or "app-server" in lowered:
        return "codex_thread"
    if "codex exec" in lowered or "codex_exec" in lowered:
        return "codex_exec"
    warnings.append(f"phase{phase_number}: execution_mode is unknown")
    return UNKNOWN


def is_protected_path(path: str, task_id: str, allowed_paths: list[str]) -> bool:
    normalized = path.strip().replace("\\", "/").lstrip("./")
    task_patterns = [
        pattern.replace("tasks/*/", f"tasks/{task_id}/")
        for pattern in PROTECTED_PATH_PATTERNS
    ]
    if path_allowed(normalized, task_patterns):
        return True
    conditional_patterns = [
        pattern.replace("tasks/*/", f"tasks/{task_id}/")
        for pattern in CONDITIONALLY_PROTECTED_PATH_PATTERNS
    ]
    if path_allowed(normalized, conditional_patterns) and not path_allowed(normalized, allowed_paths):
        return True
    basename = Path(normalized).name.lower()
    return any(token in basename for token in PROTECTED_PATH_SUBSTRINGS)


def safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def count_passed(values: list[str]) -> tuple[int, int]:
    known = [value for value in values if value != UNKNOWN]
    return sum(1 for value in known if value == "passed"), len(known)


def phase_row(task_path: Path, phase_number: int, warnings: list[str]) -> dict[str, Any]:
    records = read_attempt_manifest(task_path, phase_number, warnings)
    result = read_json(phase_result_path(task_path, phase_number), warnings)
    attempts = attempt_count(task_path, phase_number, records)
    latest = latest_attempt(task_path, phase_number, records, result)
    if result is None and latest is not None:
        result = read_json(phase_attempt_result_path(task_path, phase_number, latest), warnings)
    allowed_paths = allowed_paths_from_contract(task_path, phase_number, latest, warnings)
    gate = read_json(phase_gate_path(task_path, phase_number), warnings)
    if gate is None and latest is not None:
        gate = read_json(phase_attempt_gate_path(task_path, phase_number, latest), warnings)
    evidence = read_json(phase_evidence_path(task_path, phase_number), warnings)
    if evidence is None and latest is not None:
        evidence = read_json(phase_attempt_evidence_path(task_path, phase_number, latest), warnings)
    ac = read_json(phase_attempt_ac_path(task_path, phase_number, latest), warnings) if latest is not None else None
    changed_files = list_changed_files(result, evidence)
    scope = scope_violations(gate, evidence)
    protected_writes = [path for path in changed_files if is_protected_path(path, task_path.name, allowed_paths)]
    gate_status = status_value(gate.get("status")) if gate else UNKNOWN
    final_status = status_value(result.get("status")) if result else UNKNOWN
    if result is None:
        warnings.append(f"phase{phase_number}: result artifact is missing")
    if gate is None:
        warnings.append(f"phase{phase_number}: gate artifact is missing")
    authority_bypass: bool | str
    if final_status == "completed" and gate_status == "failed":
        authority_bypass = True
    elif final_status == "completed" and gate_status == UNKNOWN:
        authority_bypass = UNKNOWN
        warnings.append(f"phase{phase_number}: completed status has unknown gate status")
    else:
        authority_bypass = False
    thread_state_leakage: bool | str = UNKNOWN
    warnings.append(f"phase{phase_number}: thread_state_leakage is best-effort unknown")
    prompt_bytes = safe_size(phase_attempt_prompt_path(task_path, phase_number, latest)) if latest else 0
    output_bytes = safe_size(phase_attempt_output_path(task_path, phase_number, latest)) if latest else 0
    stderr_bytes = safe_size(phase_attempt_stderr_path(task_path, phase_number, latest)) if latest else 0
    return {
        "phase_id": phase_number,
        "phase_name": parse_phase_name(task_path, phase_number, warnings),
        "execution_mode": infer_execution_mode(task_path, phase_number, latest, result, warnings),
        "attempt_count": attempts,
        "final_status": final_status,
        "failure_class": infer_failure_class(task_path, phase_number, result),
        "duration_seconds": duration_seconds(records),
        "gate_status": gate_status,
        "acceptance_status": ac_status(ac),
        "verifier_status": UNKNOWN,
        "changed_file_count": len(changed_files),
        "changed_files": changed_files,
        "scope_violation_count": len(scope),
        "scope_violations": scope,
        "handoff_status": check_status(gate, "handoff_status"),
        "required_outputs_status": required_status(gate, "required_outputs", evidence, "required_outputs"),
        "required_repo_outputs_status": required_status(gate, "required_repo_outputs", evidence, "required_repo_outputs"),
        "repair_packet_count": repair_packet_count(task_path, phase_number),
        "prompt_bytes": prompt_bytes,
        "output_bytes": output_bytes,
        "stderr_bytes": stderr_bytes,
        "artifact_bytes": phase_artifact_size(task_path, phase_number),
        "protected_path_write": bool(protected_writes),
        "protected_path_writes": protected_writes,
        "authority_bypass_detected": authority_bypass,
        "thread_state_leakage": thread_state_leakage,
    }


def summary(task_path: Path, phases: list[dict[str, Any]]) -> dict[str, Any]:
    phase_count = len(phases)
    completed = sum(1 for row in phases if row.get("final_status") == "completed")
    failed = sum(1 for row in phases if row.get("final_status") in {"failed", "blocked", "interrupted"})
    total_attempts = sum(int(row.get("attempt_count") or 0) for row in phases)
    durations = [row["duration_seconds"] for row in phases if isinstance(row.get("duration_seconds"), (int, float))]
    gate_passed, gate_known = count_passed([str(row.get("gate_status") or UNKNOWN) for row in phases])
    ac_passed, ac_known = count_passed([str(row.get("acceptance_status") or UNKNOWN) for row in phases])
    verifier_passed, verifier_known = count_passed([str(row.get("verifier_status") or UNKNOWN) for row in phases])
    changed_union = sorted({path for row in phases for path in row.get("changed_files", []) if isinstance(path, str)})
    diagnostics = read_json(runtime_dir(task_path) / "completion-diagnostics.json", [])
    verify_clean: bool | str = UNKNOWN
    if diagnostics and diagnostics.get("status") in {"passed", "failed"}:
        verify_clean = diagnostics["status"] == "passed"
    return {
        "task_id": task_path.name,
        "phase_count": phase_count,
        "completed_phase_count": completed,
        "phase_completion_rate": safe_rate(completed, phase_count),
        "failed_phase_count": failed,
        "total_attempts": total_attempts,
        "retry_count": max(0, total_attempts - phase_count),
        "repair_packet_count": sum(int(row.get("repair_packet_count") or 0) for row in phases),
        "total_duration_seconds": round(sum(durations), 3) if durations else None,
        "avg_phase_duration_seconds": round(sum(durations) / len(durations), 3) if durations else None,
        "gate_pass_rate": safe_rate(gate_passed, gate_known),
        "acceptance_pass_rate": safe_rate(ac_passed, ac_known),
        "verifier_pass_rate": safe_rate(verifier_passed, verifier_known),
        "verify_clean": verify_clean,
        "changed_file_count_total": len(changed_union),
        "changed_files_total": changed_union,
        "scope_violation_count": sum(int(row.get("scope_violation_count") or 0) for row in phases),
        "protected_path_write_count": sum(1 for row in phases if row.get("protected_path_write") is True),
        "authority_bypass_count": sum(1 for row in phases if row.get("authority_bypass_detected") is True),
        "thread_state_leakage_count": sum(1 for row in phases if row.get("thread_state_leakage") is True),
        "runtime_artifact_bytes": runtime_size(task_path),
    }


def rollout_readiness(summary_data: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    for field in [
        "scope_violation_count",
        "protected_path_write_count",
        "authority_bypass_count",
        "thread_state_leakage_count",
    ]:
        if int(summary_data.get(field) or 0) > 0:
            blockers.append(field)
    level_1 = "fail" if blockers else ("unknown" if summary_data.get("phase_count") == 0 else "pass")
    return {
        "level_1_health": level_1,
        "level_2_candidate": "blocked" if blockers else "insufficient_evidence",
        "default_candidate": "blocked" if blockers else "insufficient_evidence",
        "blockers": blockers,
        "missing_evidence": [
            "real_task_count",
            "unique_phase_count",
            "cost_metrics",
            "operator_metrics",
        ],
    }


def generate_report(task_path: Path, source_root: Path) -> dict[str, Any]:
    warnings: list[str] = []
    phases = [phase_row(task_path, phase_number, warnings) for phase_number in discover_phase_numbers(task_path)]
    summary_data = summary(task_path, phases)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "task_id": task_path.name,
        "source_root": str(source_root.resolve()),
        "summary": summary_data,
        "phases": phases,
        "rollout_readiness": rollout_readiness(summary_data),
        "warnings": sorted(set(warnings)),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate diagnostic metrics from harness runtime artifacts.")
    parser.add_argument("task_dir", help="Task directory name, tasks/<task>, or absolute task path.")
    parser.add_argument("--out", help="Output JSON path. Defaults to the task runtime metrics-report.json.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = Path.cwd()
    try:
        task_path = resolve_task_path(root, args.task_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    report = generate_report(task_path, root)
    out_path = Path(args.out) if args.out else runtime_dir(task_path) / "metrics-report.json"
    write_json(out_path, report)
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
