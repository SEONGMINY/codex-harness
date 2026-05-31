#!/usr/bin/env python3
"""Verify harness task artifacts and runtime proof."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

HARNESS_VERSION = "0.1.5"

if (
    __name__ == "__main__"
    and Path(__file__).resolve().parent.name == "scripts"
    and Path(__file__).resolve().parent.parent.name == "harness"
    and Path(__file__).resolve().parent.parent.parent.name == ".codex"
):
    try:
        from install_preflight import validate_entrypoint_install_or_exit
    except Exception as exc:  # noqa: BLE001 - entrypoint preflight must fail closed before runtime imports.
        print(f"[ERROR] codex-harness install preflight is unavailable: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    validate_entrypoint_install_or_exit(sys.argv[1:], HARNESS_VERSION)

from decision_registry import (
    approved_decision_ids,
    architecture_ref_ids,
    load_decision_registry,
    validate_decision_files,
    validate_dependency_changes,
    validate_open_decisions,
)
from phase_contract import (
    DESIGN_REVIEW_DOC,
    DESIGN_REVIEW_WAIVER_DOC,
    IMPLEMENTATION_QUALITY_DOC,
    classify_handoff_text,
    contract_acceptance_commands,
    contract_allowed_paths,
    contract_required_outputs,
    contract_required_repo_outputs,
    handoff_change_trace_errors,
    path_allowed,
    parse_phase_contract,
    scope_violations,
    validate_phase_contract,
)
from phase_semantics import analyze_phase
from design_approval import design_approval_bundle_entries, design_approval_bundle_sha256
from design_contract import (
    DEFAULT_REVIEW_TAXONOMY_IDS,
    validate_design_contract,
    validate_review_coverage,
    validate_review_findings,
    validate_review_taxonomy,
    validate_traceability_matrix,
)
from harness_attestation import harness_attestation, attestation_fingerprint
from reference_resolver import ReferenceUniverse
from policy_pack import policy_pack_metadata
from policy_lineage import (
    allowed_policy_fingerprints,
    design_approval_scope_sha256,
    normalize_policy_pack_fingerprints,
    normalize_policy_pack_lineage_entries,
    policy_pack_fingerprint,
    policy_pack_lineage_sha256,
    sort_policy_pack_fingerprints,
    stable_json_sha256,
    validate_current_policy_lineage,
)
from scope_policy import required_output_repo_paths, traceable_changed_files
from task_paths import resolve_task_path
from runtime_protocol import (
    TERMINAL_ATTEMPT_RECORD_TYPES,
    attempt_manifest_semantic_errors,
    file_sha256,
    phase_attempt_manifest_path,
    read_attempt_manifest_records_with_errors,
    runtime_artifact_ref_errors,
)


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
    "design-contract.json",
    "review-taxonomy.json",
    "review-findings.json",
    "review-coverage.json",
    "traceability-matrix.json",
]
MANDATORY_TASK_DOCS = [
    "prd.md",
    "flow.md",
    "data-schema.md",
    "code-architecture.md",
    "adr.md",
]
DESIGN_REVIEW_REQUIRED_SECTIONS = [
    "Scope Summary",
    "Layer Plan",
    "Object/Module Dependency",
    "Public Interfaces",
    "API Contract",
    "DB/Storage Schema",
    "State And Lifecycle",
    "Transaction Boundaries",
    "Files To Add/Change",
    "Mermaid Diagrams",
    "Open Decisions",
    "Approval Checklist",
]
DESIGN_APPROVAL_FILE = "design-approval.json"
ALLOWED_MERMAID_DIAGRAMS = ("flowchart", "sequenceDiagram", "stateDiagram-v2")
MERMAID_BLOCK_RE = re.compile(r"```mermaid\s*\n(?P<body>.*?)```", re.DOTALL)
REPO_PATH_TOKEN_RE = re.compile(r"^[A-Za-z0-9._@{}<>*?\[\]/-]+$")
NON_PATH_TOKENS = {
    "none",
    "n/a",
    "na",
    "no",
    "not",
    "tbd",
    "todo",
    "unknown",
    "없음",
    "해당없음",
}
KNOWN_ROOT_PATH_TOKENS = {
    "app",
    "api",
    "assets",
    "client",
    "components",
    "config",
    "db",
    "docs",
    "dockerfile",
    "features",
    "hooks",
    "lib",
    "makefile",
    "pages",
    "prisma",
    "public",
    "readme",
    "scripts",
    "server",
    "src",
    "styles",
    "supabase",
    "tests",
    "types",
    "utils",
}
PLACEHOLDER_PATTERNS = [
    re.compile(r"^\s*TODO\b", re.MULTILINE),
    re.compile(r"\[TODO", re.IGNORECASE),
    re.compile(r"PLACEHOLDER", re.IGNORECASE),
    re.compile(r"Replace this", re.IGNORECASE),
    re.compile(r"Replace with", re.IGNORECASE),
]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def has_placeholder(text: str) -> bool:
    return any(pattern.search(text) for pattern in PLACEHOLDER_PATTERNS)


def rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def path_is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def safe_task_text(root: Path, path: Path, label: str) -> tuple[str | None, list[str]]:
    if not path.exists() and not path.is_symlink():
        return None, [f"Missing {label}: {rel(root, path)}"]
    if path.is_symlink():
        return None, [f"Unsafe {label} symlink: {rel(root, path)}"]
    resolved = path.resolve()
    if not path_is_relative_to(resolved, root.resolve()):
        return None, [f"Unsafe {label} outside repository: {rel(root, path)}"]
    if not path.is_file():
        return None, [f"Not a file: {rel(root, path)}"]
    return path.read_text(encoding="utf-8", errors="replace"), []


def require_file(
    root: Path,
    path: Path,
    label: str,
    check_placeholder: bool = True,
    allow_empty: bool = False,
) -> list[str]:
    text, errors = safe_task_text(root, path, label)
    if errors:
        return errors
    assert text is not None
    text = text.strip()
    errors = []
    if not text and not allow_empty:
        errors.append(f"Empty {label}: {rel(root, path)}")
    if check_placeholder and has_placeholder(text):
        errors.append(f"Placeholder remains in {label}: {rel(root, path)}")
    return errors


def has_unsafe_path_errors(errors: list[str]) -> bool:
    return any(error.startswith("Unsafe ") for error in errors)


def validate_mermaid_blocks(text: str) -> list[str]:
    blocks = [match.group("body").strip() for match in MERMAID_BLOCK_RE.finditer(text)]
    if not blocks:
        return ["Implementation design review must include at least one Mermaid block."]
    errors: list[str] = []
    valid_block_found = False
    for index, block in enumerate(blocks):
        first_line = next((line.strip() for line in block.splitlines() if line.strip()), "")
        if first_line.startswith(ALLOWED_MERMAID_DIAGRAMS):
            valid_block_found = True
        else:
            errors.append(
                "Mermaid block "
                f"{index + 1} must start with one of {ALLOWED_MERMAID_DIAGRAMS}: {first_line or '(empty)'}"
            )
    if not valid_block_found:
        errors.append("Implementation design review must include an allowed Mermaid diagram type.")
    return errors


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def current_policy_pack_fingerprint() -> dict[str, str]:
    fingerprint = policy_pack_fingerprint(policy_pack_metadata())
    if fingerprint is None:
        raise ValueError("Current policy pack metadata is invalid.")
    return fingerprint


def validate_runner_version(value: object, label: str, *, strict_current: bool = False) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return [f"{label} runner_version is missing."]
    if strict_current and value != HARNESS_VERSION:
        return [f"{label} runner_version must match current harness version {HARNESS_VERSION}: {value}"]
    return []


def validate_policy_pack_metadata(
    value: object,
    label: str,
    *,
    strict_current: bool = False,
    approved_fingerprints: list[dict[str, str]] | None = None,
) -> list[str]:
    fingerprint = policy_pack_fingerprint(value if isinstance(value, dict) else None)
    if fingerprint is None:
        return [f"{label} policy_pack must include id, schema_version, and sha256."]
    if strict_current and fingerprint != current_policy_pack_fingerprint():
        return [f"{label} policy_pack does not match current harness policy pack."]
    if approved_fingerprints is not None and fingerprint not in approved_fingerprints:
        return [f"{label} policy_pack is outside the design-approved policy pack lineage."]
    return []


def validate_harness_attestation_metadata(
    value: object,
    label: str,
    *,
    strict_current: bool = False,
) -> list[str]:
    fingerprint = attestation_fingerprint(value if isinstance(value, dict) else None)
    if fingerprint is None:
        return [f"{label} harness_attestation is invalid."]
    if strict_current and fingerprint != attestation_fingerprint(harness_attestation()):
        return [f"{label} harness_attestation does not match current harness script fingerprint."]
    return []


def approved_policy_pack_lineage(root: Path, task_path: Path) -> tuple[list[dict[str, str]], list[str]]:
    approval_path = task_path / "context-pack" / "static" / DESIGN_APPROVAL_FILE
    if not approval_path.exists():
        return [], []
    try:
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [], [f"Invalid design approval JSON: {rel(root, approval_path)}: {exc}"]
    if not isinstance(approval, dict):
        return [], [f"Design approval must be a JSON object: {rel(root, approval_path)}"]
    active = policy_pack_fingerprint(approval.get("active_policy_pack"))
    entries, errors = normalize_policy_pack_lineage_entries(
        approval.get("approved_policy_packs"),
        "Design approval approved_policy_packs",
        active,
    )
    return allowed_policy_fingerprints(entries), errors


COMMAND_IDENTITY_FIELDS = ("id", "command", "role", "target", "exit_code", "timed_out")


def command_result_identity(item: dict[str, object]) -> dict[str, object]:
    return {key: item.get(key) for key in COMMAND_IDENTITY_FIELDS if key in item}


def validate_ac_results_metadata(
    root: Path,
    task_path: Path,
    phase_number: int,
    attempt: int,
    artifacts: dict[str, object],
    expected_policy_pack: dict[str, str] | None = None,
    expected_commands_run: object = None,
    *,
    approved_policy_packs: list[dict[str, str]] | None = None,
    strict_current_harness: bool = False,
) -> list[str]:
    raw_path = artifacts.get("ac_results") if isinstance(artifacts, dict) else None
    if not isinstance(raw_path, str):
        return []
    path = task_path / raw_path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Invalid AC results metadata: {rel(root, path)}: {exc}"]
    if not isinstance(data, dict):
        return [f"AC results must be a metadata object: {rel(root, path)}"]
    errors: list[str] = []
    if strict_current_harness or "schema_version" in data:
        if data.get("schema_version") != 1:
            errors.append("AC results schema_version must be 1.")
    if data.get("phase") != phase_number:
        errors.append("AC results metadata phase does not match result phase.")
    if data.get("attempt") not in (None, attempt):
        errors.append("AC results metadata attempt does not match result attempt.")
    commands = data.get("commands") if isinstance(data.get("commands"), list) else []
    command_identities = [command_result_identity(item) for item in commands if isinstance(item, dict)]
    commands_digest = data.get("commands_digest")
    if commands_digest is not None and commands_digest != stable_json_sha256(command_identities):
        errors.append("AC results commands_digest does not match commands.")
    if isinstance(expected_commands_run, list):
        expected_identities = [
            command_result_identity(item)
            for item in expected_commands_run
            if isinstance(item, dict)
        ]
        if command_identities != expected_identities:
            errors.append("AC results commands do not match phase result commands_run.")
    policy = data.get("policy_pack")
    if expected_policy_pack is not None and policy is not None and policy != expected_policy_pack:
        errors.append("AC results metadata policy_pack does not match phase result policy_pack.")
    if strict_current_harness or policy is not None:
        errors.extend(
            validate_policy_pack_metadata(
                policy,
                "AC results",
                strict_current=strict_current_harness,
                approved_fingerprints=approved_policy_packs,
            )
        )
    if strict_current_harness or data.get("runner_version") is not None:
        errors.extend(
            validate_runner_version(
                data.get("runner_version"),
                "AC results",
                strict_current=strict_current_harness,
            )
        )
    if strict_current_harness or data.get("harness_attestation") is not None:
        errors.extend(
            validate_harness_attestation_metadata(
                data.get("harness_attestation"),
                "AC results",
                strict_current=strict_current_harness,
            )
        )
    return errors


def validate_evaluation_command_results(
    root: Path,
    task_path: Path,
    path: Path,
    *,
    approved_policy_packs: list[dict[str, str]] | None = None,
) -> list[str]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid evaluation command results JSON: {rel(root, path)}: {exc}"]
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        return [f"Evaluation command results must be a schema_version 1 metadata object: {rel(root, path)}"]
    errors = validate_policy_pack_metadata(
        data.get("policy_pack"),
        "Evaluation command results",
        approved_fingerprints=approved_policy_packs,
    )
    errors.extend(validate_harness_attestation_metadata(data.get("harness_attestation"), "Evaluation command results"))
    return errors


def validate_command_expectation_metadata(commands_run: object, contract: dict[str, object]) -> list[str]:
    commands = commands_run if isinstance(commands_run, list) else []
    expectations = contract.get("command_expectations")
    if not isinstance(expectations, list) or not expectations:
        return ["Contract.command_expectations is empty but runtime command metadata was provided."] if commands else []
    by_id = {item.get("id"): item for item in expectations if isinstance(item, dict) and isinstance(item.get("id"), str)}
    by_command = {
        item.get("command"): item
        for item in expectations
        if isinstance(item, dict) and isinstance(item.get("command"), str)
    }
    errors: list[str] = []
    for index, command in enumerate(commands):
        if not isinstance(command, dict):
            continue
        expectation = by_id.get(command.get("id")) or by_command.get(command.get("command"))
        if expectation is None:
            if command.get("role") is not None:
                errors.append(f"commands_run[{index}] runtime role is not declared in Contract.command_expectations.")
            continue
        for key in ["role", "target", "repo_scan"]:
            if key in command and key in expectation and command.get(key) != expectation.get(key):
                errors.append(f"commands_run[{index}].{key} does not match Contract.command_expectations.")
    return errors


def validate_runtime_risk_evidence(root: Path, task_path: Path, phase_number: int, contract: dict[str, object]) -> list[str]:
    required_ids: set[str] = set()
    for risk in contract.get("risk_ledger") or []:
        if not isinstance(risk, dict):
            continue
        for ref in risk.get("required_evidence") or []:
            if isinstance(ref, str):
                required_ids.add(ref)
    if not required_ids:
        return []
    result_path = task_path / "context-pack" / "runtime" / f"phase{phase_number}-result.json"
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [f"Phase {phase_number} risk required_evidence was not closed by passed runtime commands."]
    passed: set[str] = set()
    for command in result.get("commands_run") or []:
        if isinstance(command, dict) and command.get("exit_code") == 0 and isinstance(command.get("id"), str):
            passed.add(command["id"])
    missing = sorted(required_ids - passed)
    return [
        f"Phase {phase_number} risk required_evidence was not closed by passed runtime commands: {', '.join(missing)}"
    ] if missing else []


def design_doc_info(root: Path, task_path: Path) -> tuple[Path, str, str] | None:
    review_path = task_path / "docs" / DESIGN_REVIEW_DOC
    if review_path.exists():
        return review_path, rel(root, review_path), "review"
    waiver_path = task_path / "docs" / DESIGN_REVIEW_WAIVER_DOC
    if waiver_path.exists():
        return waiver_path, rel(root, waiver_path), "waiver"
    return None


def markdown_section(text: str, section: str) -> str:
    match = re.search(
        rf"(?ms)^##\s+{re.escape(section)}\s*$\n(?P<body>.*?)(?=^##\s+|\Z)",
        text,
    )
    return match.group("body").strip() if match else ""


def _normalize_repo_path_token(value: str) -> str | None:
    value = value.strip().strip("`").strip(".,;")
    lowered = value.lower()
    if lowered in NON_PATH_TOKENS:
        return None
    if not value or value.startswith("<") or value.endswith(">"):
        return None
    if "://" in value or any(char.isspace() for char in value):
        return None
    if not REPO_PATH_TOKEN_RE.match(value):
        return None
    if "/" not in value and "." not in value and not any(char in value for char in "*?["):
        if lowered not in KNOWN_ROOT_PATH_TOKENS:
            return None
    return value.strip("/")


def extract_design_repo_paths(text: str) -> list[str]:
    section = markdown_section(text, "Files To Add/Change")
    paths: set[str] = set()
    for value in re.findall(r"`([^`]+)`", section):
        normalized = _normalize_repo_path_token(value)
        if normalized:
            paths.add(normalized)
    for line in section.splitlines():
        stripped = re.sub(r"^\s*[-*+]\s+(?:\[[ xX]\]\s+)?", "", line).strip()
        candidate = re.split(r"\s+(?:-|--|:|=>)\s+|:", stripped, maxsplit=1)[0].strip().strip("`")
        normalized = _normalize_repo_path_token(candidate)
        if normalized:
            paths.add(normalized)
    return sorted(paths)


def validate_design_review(
    root: Path,
    task_path: Path,
    task_docs: list[Path],
) -> list[str]:
    docs_dir = task_path / "docs"
    review_path = docs_dir / DESIGN_REVIEW_DOC
    waiver_path = docs_dir / DESIGN_REVIEW_WAIVER_DOC
    errors: list[str] = []

    if review_path.exists():
        if review_path not in task_docs:
            errors.append(f"Task index docs must include {rel(root, review_path)}")
        errors.extend(require_file(root, review_path, "implementation design review"))
        text = review_path.read_text(encoding="utf-8", errors="replace")
        for section in DESIGN_REVIEW_REQUIRED_SECTIONS:
            if not re.search(rf"(?m)^##\s+{re.escape(section)}\s*$", text):
                errors.append(f"Implementation design review must include section: {section}")
        errors.extend(validate_mermaid_blocks(text))
        if not extract_design_repo_paths(text):
            errors.append(
                "Implementation design review must list approved repository paths "
                "in `Files To Add/Change`."
            )
        return errors

    if waiver_path.exists():
        if waiver_path not in task_docs:
            errors.append(f"Task index docs must include {rel(root, waiver_path)}")
        errors.extend(require_file(root, waiver_path, "design review waiver"))
        return errors

    errors.append(
        "Task docs must include implementation design review or design review waiver: "
        f"{rel(root, review_path)} or {rel(root, waiver_path)}"
    )
    return errors


def validate_design_approval(root: Path, task_path: Path, *, strict_current_harness: bool = False) -> list[str]:
    info = design_doc_info(root, task_path)
    if info is None:
        return []
    design_path, design_rel_path, _ = info
    approval_path = task_path / "context-pack" / "static" / DESIGN_APPROVAL_FILE
    errors = require_file(root, approval_path, "design approval", check_placeholder=False)
    if errors:
        return errors
    try:
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid design approval JSON: {rel(root, approval_path)}: {exc}"]
    if not isinstance(approval, dict):
        return [f"Design approval must be a JSON object: {rel(root, approval_path)}"]

    if approval.get("approved") is not True:
        errors.append("Design approval must set `approved` to true.")
    if approval.get("approved_doc") != design_rel_path:
        errors.append(f"Design approval `approved_doc` must be {design_rel_path}.")
    expected_hash = file_sha256(design_path)
    if approval.get("approved_doc_sha256") != expected_hash:
        errors.append("Design approval hash does not match the current design review document.")
    if not isinstance(approval.get("approved_at"), str) or not approval.get("approved_at", "").strip():
        errors.append("Design approval must include non-empty `approved_at`.")
    if not isinstance(approval.get("approval_source"), str) or not approval.get("approval_source", "").strip():
        errors.append("Design approval must include non-empty `approval_source`.")
    schema_version = approval.get("schema_version")
    if strict_current_harness and schema_version != 3:
        errors.append("Design approval `schema_version` 3 is required by current harness.")
    bundle = approval.get("approved_bundle")
    if schema_version == 3 or strict_current_harness or approval.get("approved") is True:
        if not isinstance(bundle, list) or not bundle:
            errors.append("Design approval must include non-empty `approved_bundle`.")
        elif schema_version == 3 or strict_current_harness:
            current_bundle, bundle_errors = design_approval_bundle_entries(root, task_path, design_rel_path)
            errors.extend(bundle_errors)
            if bundle != current_bundle or approval.get("approved_bundle_sha256") != design_approval_bundle_sha256(current_bundle):
                errors.append("Design approval approved static evidence bundle does not match current files.")
            for entry in bundle:
                raw_path = entry.get("path") if isinstance(entry, dict) else None
                if not isinstance(raw_path, str) or raw_path.startswith("../") or Path(raw_path).is_absolute():
                    errors.append("Design approval approved_bundle entries must use safe repo-relative paths.")
    if schema_version == 3 or strict_current_harness:
        active = policy_pack_fingerprint(approval.get("active_policy_pack"))
        fingerprints, fingerprint_errors = normalize_policy_pack_fingerprints(
            approval.get("approved_policy_packs"),
            "Design approval approved_policy_packs",
        )
        errors.extend(fingerprint_errors)
        if active is None:
            errors.append("Design approval active_policy_pack must include id, schema_version, and sha256.")
        elif active != current_policy_pack_fingerprint():
            errors.append("Design approval active_policy_pack does not match current policy pack.")
        if active is not None and fingerprints:
            entries, entry_errors = normalize_policy_pack_lineage_entries(
                approval.get("approved_policy_packs"),
                "Design approval approved_policy_packs",
                active,
            )
            errors.extend(entry_errors)
            if approval.get("approved_policy_packs_sha256") != policy_pack_lineage_sha256(fingerprints):
                errors.append("Design approval approved_policy_packs_sha256 does not match approved_policy_packs.")
            expected_scope = design_approval_scope_sha256(
                approval.get("approved_bundle") if isinstance(approval.get("approved_bundle"), list) else [],
                fingerprints,
                active,
                entries,
            )
            if approval.get("design_approval_scope_sha256") != expected_scope:
                errors.append("Design approval design_approval_scope_sha256 does not match approved scope.")
    return errors


def is_implementation_contract(contract: dict[str, object]) -> bool:
    return analyze_phase(contract).writes_product_code


def design_path_covers(raw_path: str, approved_paths: list[str]) -> bool:
    normalized = raw_path.strip("/")
    normalized_approved = [path.strip("/") for path in approved_paths]
    if any(char in normalized for char in "*?["):
        # Glob-to-glob containment is intentionally conservative. Use the exact
        # approved glob, or approve a directory prefix such as `scripts/harness/`.
        if normalized in normalized_approved:
            return True
        for approved in normalized_approved:
            if any(char in approved for char in "*?["):
                continue
            if normalized.startswith(approved.rstrip("/") + "/"):
                return True
        return False
    return path_allowed(normalized, approved_paths)


def validate_contract_against_design(
    root: Path,
    task_path: Path,
    phase_number: int,
    contract: dict[str, object],
    design_kind: str | None,
    approved_paths: list[str],
    design_refs: set[str] | None = None,
) -> list[str]:
    if not is_implementation_contract(contract):
        return []
    errors: list[str] = []
    if design_kind == "waiver":
        errors.append(
            f"Phase {phase_number} uses an implementation layer, so design-review-waiver.md is not allowed."
        )
        return errors
    if design_refs is not None:
        refs = {item for item in contract.get("design_refs") or [] if isinstance(item, str)}
        if not refs:
            errors.append(f"Phase {phase_number} implementation contract must include design_refs.")
        missing = sorted(refs - design_refs)
        if missing:
            errors.append(f"Phase {phase_number} design_refs are not covered by traceability-matrix.json: {missing}")
    if not approved_paths:
        errors.append(
            f"Phase {phase_number} requires approved repository paths in design review `Files To Add/Change`."
        )
        return errors
    for raw_path in contract_allowed_paths(contract):
        if not design_path_covers(raw_path, approved_paths):
            errors.append(
                f"Phase {phase_number} scope.allowed_paths entry is outside approved design files: {raw_path}"
            )
    for raw_path in contract_required_repo_outputs(contract):
        if not path_allowed(raw_path, approved_paths):
            errors.append(
                f"Phase {phase_number} required_repo_outputs entry is outside approved design files: {raw_path}"
            )
    return errors


def resolve_task_relative_path(
    root: Path,
    task_path: Path,
    raw_path: str,
    label: str,
) -> tuple[Path | None, list[str]]:
    path = Path(raw_path)
    if path.is_absolute():
        return None, [f"`{label}` must be relative to the task directory: {raw_path}"]

    target = (task_path / path).resolve()
    task_root = task_path.resolve()
    try:
        target.relative_to(task_root)
    except ValueError:
        return None, [f"`{label}` must not escape the task directory: {raw_path}"]
    return target, []


def resolve_repo_relative_path(root: Path, raw_path: str, label: str) -> tuple[Path | None, list[str]]:
    path = Path(raw_path)
    if path.is_absolute():
        return None, [f"`{label}` must be relative to the repository root: {raw_path}"]
    target = (root / path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None, [f"`{label}` must not escape the repository root: {raw_path}"]
    return target, []


def phase_ac_commands(markdown: str) -> list[str]:
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
            if stripped and not stripped.startswith("#") and stripped != "TODO":
                commands.append(stripped)
    return commands


def expected_ac_commands(phase: dict, markdown: str) -> list[str]:
    contract, _ = parse_phase_contract(markdown)
    if contract is not None:
        commands = contract_acceptance_commands(contract)
        if commands:
            return commands
    commands = list(phase.get("ac_commands") or [])
    commands.extend(phase_ac_commands(markdown))
    unique_commands = []
    seen = set()
    for command in commands:
        if not command or command == "TODO" or command in seen:
            continue
        seen.add(command)
        unique_commands.append(command)
    return unique_commands


def expected_required_outputs(phase: dict, markdown: str) -> list[str]:
    contract, _ = parse_phase_contract(markdown)
    if contract is not None:
        outputs = contract_required_outputs(contract)
        if outputs:
            return outputs
    return list(phase.get("required_outputs") or [])


def expected_required_repo_outputs(markdown: str) -> list[str]:
    contract, _ = parse_phase_contract(markdown)
    if contract is None:
        return []
    return contract_required_repo_outputs(contract)


def phase_attempts(phase: dict) -> list[int]:
    attempts = phase.get("attempts")
    if isinstance(attempts, int) and attempts > 0:
        return [attempts]
    return [1]


def require_string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        return [f"`{field}` must be a list."]
    if not all(isinstance(item, str) for item in value):
        return [f"`{field}` entries must be strings."]
    return []


def validate_commands_run(value: object, expected_commands: list[str]) -> list[str]:
    if not isinstance(value, list):
        return ["`commands_run` must be a list."]
    errors: list[str] = []
    if not value:
        errors.append("`commands_run` must not be empty.")
    actual_commands = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"`commands_run[{index}]` must be an object.")
            continue
        if not isinstance(item.get("command"), str) or not item.get("command", "").strip():
            errors.append(f"`commands_run[{index}].command` must be a non-empty string.")
        else:
            actual_commands.append(item["command"])
        if not isinstance(item.get("exit_code"), int):
            errors.append(f"`commands_run[{index}].exit_code` must be an integer.")
        elif item.get("exit_code") != 0:
            errors.append(f"`commands_run[{index}].exit_code` must be 0 for a completed phase.")
    if actual_commands != expected_commands:
        errors.append(
            "`commands_run` must match phase AC commands. "
            f"expected={expected_commands!r} actual={actual_commands!r}"
        )
    return errors


def validate_required_outputs(
    root: Path,
    task_path: Path,
    value: object,
    expected_outputs: list[str],
) -> list[str]:
    if not isinstance(value, list):
        return ["`required_outputs` must be a list."]
    errors: list[str] = []
    actual_outputs = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"`required_outputs[{index}]` must be an object.")
            continue
        if not isinstance(item.get("path"), str) or not item.get("path", "").strip():
            errors.append(f"`required_outputs[{index}].path` must be a non-empty string.")
            continue
        raw_path = item["path"]
        actual_outputs.append(raw_path)
        if item.get("exists") is not True:
            errors.append(f"`required_outputs[{index}].exists` must be true.")
        target, path_errors = resolve_task_relative_path(
            root,
            task_path,
            raw_path,
            f"required_outputs[{index}].path",
        )
        errors.extend(path_errors)
        if target is not None and not target.exists():
            errors.append(f"`required_outputs[{index}].path` does not exist: {rel(root, target)}")
    if actual_outputs != expected_outputs:
        errors.append(
            "`required_outputs` must match phase required_outputs. "
            f"expected={expected_outputs!r} actual={actual_outputs!r}"
        )
    return errors


def validate_required_repo_outputs(
    root: Path,
    value: object,
    expected_outputs: list[str],
) -> list[str]:
    if not isinstance(value, list):
        return ["`required_repo_outputs` must be a list."]
    errors: list[str] = []
    actual_outputs = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"`required_repo_outputs[{index}]` must be an object.")
            continue
        if not isinstance(item.get("path"), str) or not item.get("path", "").strip():
            errors.append(f"`required_repo_outputs[{index}].path` must be a non-empty string.")
            continue
        raw_path = item["path"]
        actual_outputs.append(raw_path)
        if item.get("exists") is not True:
            errors.append(f"`required_repo_outputs[{index}].exists` must be true.")
        target, path_errors = resolve_repo_relative_path(
            root,
            raw_path,
            f"required_repo_outputs[{index}].path",
        )
        errors.extend(path_errors)
        if target is not None and not target.exists():
            errors.append(f"`required_repo_outputs[{index}].path` does not exist: {rel(root, target)}")
    if actual_outputs != expected_outputs:
        errors.append(
            "`required_repo_outputs` must match phase required_repo_outputs. "
            f"expected={expected_outputs!r} actual={actual_outputs!r}"
        )
    return errors


def validate_artifacts(
    root: Path,
    task_path: Path,
    value: object,
    phase_number: int,
    attempt: int | None,
    strict_attempt_artifacts: bool = False,
) -> list[str]:
    if not isinstance(value, dict):
        return ["`artifacts` must be an object."]
    errors: list[str] = []
    expected_paths = {
        "contract": f"context-pack/runtime/phase{phase_number}-contract.json",
        "checklist": f"context-pack/runtime/phase{phase_number}-checklist.md",
        "prompt": f"context-pack/runtime/phase{phase_number}-prompt.md",
        "handoff": f"context-pack/handoffs/phase{phase_number}.md",
        "quality": f"context-pack/runtime/phase{phase_number}-quality.json",
    }
    if attempt is not None:
        expected_paths.update(
            {
                "contract": f"context-pack/runtime/phase{phase_number}-contract-attempt{attempt}.json",
                "checklist": f"context-pack/runtime/phase{phase_number}-checklist-attempt{attempt}.md",
                "prompt": f"context-pack/runtime/phase{phase_number}-prompt-attempt{attempt}.md",
                "stdout": f"context-pack/runtime/phase{phase_number}-output-attempt{attempt}.jsonl",
                "stderr": f"context-pack/runtime/phase{phase_number}-stderr-attempt{attempt}.txt",
                "ac_results": f"context-pack/runtime/phase{phase_number}-ac-attempt{attempt}.json",
                "quality": f"context-pack/runtime/phase{phase_number}-quality-attempt{attempt}.json",
                "handoff": f"context-pack/runtime/phase{phase_number}-handoff-attempt{attempt}.md",
                "evidence": f"context-pack/runtime/phase{phase_number}-evidence-attempt{attempt}.json",
                "reconciliation": f"context-pack/runtime/phase{phase_number}-reconciliation-attempt{attempt}.json",
                "reconciliation_summary": f"context-pack/runtime/phase{phase_number}-reconciliation-attempt{attempt}.md",
                "gate": f"context-pack/runtime/phase{phase_number}-gate-attempt{attempt}.json",
            }
        )
    legacy_paths = {
        "contract": f"context-pack/runtime/phase{phase_number}-contract.json",
        "checklist": f"context-pack/runtime/phase{phase_number}-checklist.md",
        "prompt": f"context-pack/runtime/phase{phase_number}-prompt.md",
    }
    required_artifact_keys = {
        "prompt",
        "stdout",
        "stderr",
        "ac_results",
        "quality",
        "handoff",
        "evidence",
        "reconciliation",
        "reconciliation_summary",
        "gate",
    }
    for key in [
        "contract",
        "checklist",
        "prompt",
        "stdout",
        "stderr",
        "ac_results",
        "quality",
        "handoff",
        "evidence",
        "reconciliation",
        "reconciliation_summary",
        "gate",
    ]:
        raw_path = value.get(key)
        if not isinstance(raw_path, str) or not raw_path.strip():
            if key in required_artifact_keys:
                errors.append(f"`artifacts.{key}` must be a non-empty string.")
            continue
        if (
            key in expected_paths
            and raw_path != expected_paths[key]
            and (strict_attempt_artifacts or raw_path != legacy_paths.get(key))
            and not (
                not strict_attempt_artifacts
                and
                key == "handoff"
                and raw_path == f"context-pack/handoffs/phase{phase_number}.md"
            )
        ):
            errors.append(f"`artifacts.{key}` must be {expected_paths[key]}.")
        target, path_errors = resolve_task_relative_path(root, task_path, raw_path, f"artifacts.{key}")
        errors.extend(path_errors)
        if target is None:
            continue
        allow_empty = key == "stderr"
        errors.extend(
            require_file(
                root,
                target,
                f"phase result artifact {key}",
                check_placeholder=False,
                allow_empty=allow_empty,
            )
        )
    return errors


def validate_phase_gate(root: Path, path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        gate = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid phase gate JSON: {rel(root, path)}: {exc}"]
    if not isinstance(gate, dict):
        return [f"Phase gate must be a JSON object: {rel(root, path)}"]
    if gate.get("status") != "passed":
        return [f'Phase gate status must be "passed": {rel(root, path)}']
    checks = gate.get("checks")
    if not isinstance(checks, list) or not checks:
        return [f"Phase gate must include checks: {rel(root, path)}"]
    return []


def validate_evaluation_final(root: Path, path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid evaluation final JSON: {rel(root, path)}: {exc}"]
    if not isinstance(data, dict):
        return [f"Evaluation final output must be a JSON object: {rel(root, path)}"]
    if data.get("verdict") != "approved":
        return [f'Evaluation verdict must be "approved": {rel(root, path)}']
    if data.get("required_followups"):
        return [f"Evaluation approved verdict must not include required_followups: {rel(root, path)}"]
    if data.get("blockers"):
        return [f"Evaluation approved verdict must not include blockers: {rel(root, path)}"]
    return []


def artifact_entries_by_name(value: object) -> dict[str, dict[str, Any]]:
    entries = value if isinstance(value, list) else []
    return {
        str(item.get("name")): item
        for item in entries
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }


def validate_commit_artifact_ref(
    root: Path,
    task_path: Path,
    entry: object,
    expected_name: str,
    expected_path: str,
    label: str,
) -> list[str]:
    if not isinstance(entry, dict):
        return [f"{label} must include artifact {expected_name}."]
    errors: list[str] = []
    if entry.get("name") != expected_name:
        errors.append(f"{label} {expected_name} name mismatch.")
    if entry.get("path") != expected_path:
        errors.append(f"{label} {expected_name} path must be {expected_path}.")
    if entry.get("exists") is not True:
        errors.append(f"{label} {expected_name} must exist.")
        return errors
    target, path_errors = resolve_task_relative_path(root, task_path, expected_path, f"{label}.{expected_name}.path")
    errors.extend(path_errors)
    if target is None:
        return errors
    if not target.exists() or not target.is_file():
        errors.append(f"{label} {expected_name} path does not exist: {rel(root, target)}")
    elif entry.get("sha256") != file_sha256(target):
        errors.append(f"{label} {expected_name} sha256 does not match current artifact.")
    return errors


def validate_runtime_artifact_ref(
    root: Path,
    task_path: Path,
    entry: object,
    label: str,
    *,
    expected_name: str | None = None,
    expected_path: str | None = None,
) -> list[str]:
    return runtime_artifact_ref_errors(
        task_path,
        entry,
        label,
        expected_name=expected_name,
        expected_path=expected_path,
    )


def validate_runtime_integrity_report(
    root: Path,
    task_path: Path,
    entry: object,
    phase_number: int,
    attempt: int,
    label: str,
) -> list[str]:
    errors = validate_runtime_artifact_ref(
        root,
        task_path,
        entry,
        label,
        expected_name="runtime_integrity_report",
    )
    if errors or not isinstance(entry, dict) or entry.get("exists") is not True:
        return errors
    raw_path = entry.get("path")
    if not isinstance(raw_path, str):
        return errors
    target, path_errors = resolve_task_relative_path(root, task_path, raw_path, f"{label}.path")
    errors.extend(path_errors)
    if target is None or not target.exists():
        return errors
    try:
        report = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [*errors, f"{label} must be valid JSON: {rel(root, target)}: {exc}"]
    if not isinstance(report, dict):
        return [*errors, f"{label} must be a JSON object: {rel(root, target)}"]
    if report.get("schema_version") != 1:
        errors.append(f"{label}.schema_version must be 1.")
    if report.get("artifact_kind") != "runtime_integrity_report":
        errors.append(f'{label}.artifact_kind must be "runtime_integrity_report".')
    if report.get("phase") != phase_number:
        errors.append(f"{label}.phase must be {phase_number}.")
    if report.get("attempt") != attempt:
        errors.append(f"{label}.attempt must be {attempt}.")
    if report.get("failure_window") not in {
        "codex_execution",
        "acceptance_command_execution",
        "post_acceptance_settle",
    }:
        errors.append(f"{label}.failure_window is invalid.")
    changed_count = report.get("changed_count")
    changed_paths = report.get("changed_paths")
    if not isinstance(changed_count, int) or changed_count < 0:
        errors.append(f"{label}.changed_count must be a non-negative integer.")
    if not isinstance(report.get("changed_paths_digest"), str) or len(report.get("changed_paths_digest", "")) != 64:
        errors.append(f"{label}.changed_paths_digest must be a SHA-256 hex string.")
    if not isinstance(report.get("changed_paths_truncated"), bool):
        errors.append(f"{label}.changed_paths_truncated must be boolean.")
    if not isinstance(report.get("changed_paths_limit"), int) or report.get("changed_paths_limit") <= 0:
        errors.append(f"{label}.changed_paths_limit must be a positive integer.")
    if not isinstance(changed_paths, list) or not all(isinstance(path, str) for path in changed_paths):
        errors.append(f"{label}.changed_paths must be a list of strings.")
        changed_paths = []
    elif changed_paths != sorted(changed_paths):
        errors.append(f"{label}.changed_paths must be sorted.")
    settle = report.get("settle")
    if not isinstance(settle, dict):
        errors.append(f"{label}.settle must be an object.")
    else:
        for key in ["settle_seconds", "poll_seconds"]:
            value = settle.get(key)
            if not isinstance(value, (int, float)) or value < 0:
                errors.append(f"{label}.settle.{key} must be a non-negative number.")
    fingerprints = report.get("fingerprints")
    if not isinstance(fingerprints, dict):
        errors.append(f"{label}.fingerprints must be an object.")
    else:
        for raw_path, fingerprint in fingerprints.items():
            if not isinstance(raw_path, str) or not isinstance(fingerprint, dict):
                errors.append(f"{label}.fingerprints entries must map path strings to objects.")
                continue
            if fingerprint.get("status") not in {"created", "modified", "deleted"}:
                errors.append(f"{label}.fingerprints[{raw_path}].status is invalid.")
            for key in ["before", "after"]:
                value = fingerprint.get(key)
                if value is not None and not isinstance(value, str):
                    errors.append(f"{label}.fingerprints[{raw_path}].{key} must be a string or null.")
                if isinstance(value, str) and value.startswith("symlink:"):
                    errors.append(f"{label}.fingerprints[{raw_path}].{key} must not include raw symlink targets.")
    return errors


def validate_evaluation_commit(
    root: Path,
    task_path: Path,
    path: Path,
    completed_phase_results: list[tuple[int, dict[str, Any]]],
    *,
    approved_policy_packs: list[dict[str, str]] | None = None,
    strict_current_harness: bool = False,
) -> list[str]:
    if not path.exists():
        return []
    try:
        commit = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid evaluation commit JSON: {rel(root, path)}: {exc}"]
    if not isinstance(commit, dict):
        return [f"Evaluation commit must be a JSON object: {rel(root, path)}"]

    errors: list[str] = []
    if commit.get("schema_version") != 1:
        errors.append("Evaluation commit schema_version must be 1.")
    if commit.get("commit_scope") != "evaluation_bundle":
        errors.append('Evaluation commit commit_scope must be "evaluation_bundle".')
    if commit.get("status") != "committed":
        errors.append('Evaluation commit status must be "committed".')
    if commit.get("verdict") != "approved":
        errors.append('Evaluation commit verdict must be "approved".')
    errors.extend(
        validate_policy_pack_metadata(
            commit.get("policy_pack"),
            "Evaluation commit",
            approved_fingerprints=approved_policy_packs,
        )
    )
    errors.extend(
        validate_harness_attestation_metadata(
            commit.get("harness_attestation"),
            "Evaluation commit",
            strict_current=strict_current_harness,
        )
    )
    errors.extend(
        validate_commit_artifact_ref(
            root,
            task_path,
            commit.get("task_index"),
            "task_index",
            "index.json",
            "Evaluation commit",
        )
    )

    expected_artifacts = {
        "command_results": "context-pack/runtime/evaluation-command-results.json",
        "prompt": "context-pack/runtime/evaluation-prompt.md",
        "output": "context-pack/runtime/evaluation-output.jsonl",
        "stderr": "context-pack/runtime/evaluation-stderr.txt",
        "last_message": "context-pack/runtime/evaluation-last-message.json",
    }
    artifacts = artifact_entries_by_name(commit.get("evaluation_artifacts"))
    for name, expected_path in expected_artifacts.items():
        errors.extend(
            validate_commit_artifact_ref(
                root,
                task_path,
                artifacts.get(name),
                name,
                expected_path,
                "Evaluation commit artifact",
            )
        )

    phase_proofs = commit.get("phase_proofs")
    if not isinstance(phase_proofs, list):
        errors.append("Evaluation commit phase_proofs must be a list.")
        phase_proofs = []
    by_phase = {
        item.get("phase"): item
        for item in phase_proofs
        if isinstance(item, dict) and isinstance(item.get("phase"), int)
    }
    expected_phases = {phase_number for phase_number, _result in completed_phase_results}
    actual_phases = {phase for phase in by_phase if isinstance(phase, int)}
    if actual_phases != expected_phases:
        errors.append(
            "Evaluation commit phase_proofs must match completed phases. "
            f"expected={sorted(expected_phases)!r} actual={sorted(actual_phases)!r}"
        )
    for phase_number, result in completed_phase_results:
        proof = by_phase.get(phase_number)
        if not isinstance(proof, dict):
            continue
        attempt = result.get("attempt")
        if not isinstance(attempt, int) or attempt <= 0:
            continue
        if proof.get("attempt") != attempt:
            errors.append(f"Evaluation commit phase {phase_number} attempt must be {attempt}.")
        commit_path = f"context-pack/runtime/phase{phase_number}-attempt{attempt}-commit.json"
        errors.extend(
            validate_commit_artifact_ref(
                root,
                task_path,
                proof.get("attempt_commit"),
                "attempt_commit",
                commit_path,
                f"Evaluation commit phase {phase_number}",
            )
        )
    repair_paths = sorted(
        (task_path / "context-pack" / "runtime").glob("evaluation-repair*-result.json"),
        key=lambda item: (
            evaluation_repair_result_iteration(item)
            if evaluation_repair_result_iteration(item) is not None
            else 10**9
        ),
    )
    repair_proofs = commit.get("repair_proofs")
    if repair_proofs is None and not repair_paths:
        repair_proofs = []
    elif not isinstance(repair_proofs, list):
        errors.append("Evaluation commit repair_proofs must be a list.")
        repair_proofs = []
    by_iteration: dict[int, dict[str, Any]] = {}
    duplicate_iterations: list[int] = []
    for index, item in enumerate(repair_proofs):
        if not isinstance(item, dict):
            errors.append(f"Evaluation commit repair_proofs[{index}] must be an object.")
            continue
        iteration = item.get("iteration")
        if not isinstance(iteration, int) or iteration <= 0:
            errors.append(f"Evaluation commit repair_proofs[{index}].iteration must be a positive integer.")
            continue
        if "result" not in item:
            errors.append(f"Evaluation commit repair_proofs[{index}] must include result.")
        if iteration in by_iteration:
            duplicate_iterations.append(iteration)
            continue
        by_iteration[iteration] = item
    for iteration in sorted(set(duplicate_iterations)):
        errors.append(f"Evaluation commit repair_proofs has duplicate iteration {iteration}.")
    expected_iterations = {
        iteration
        for path_item in repair_paths
        if (iteration := evaluation_repair_result_iteration(path_item)) is not None
    }
    actual_iterations = {iteration for iteration in by_iteration if isinstance(iteration, int)}
    if actual_iterations != expected_iterations:
        errors.append(
            "Evaluation commit repair_proofs must match evaluation repair results. "
            f"expected={sorted(expected_iterations)!r} actual={sorted(actual_iterations)!r}"
        )
    for repair_path in repair_paths:
        iteration = evaluation_repair_result_iteration(repair_path)
        if iteration is None:
            continue
        proof = by_iteration.get(iteration)
        if not isinstance(proof, dict):
            continue
        expected_path = f"context-pack/runtime/evaluation-repair{iteration}-result.json"
        errors.extend(
            validate_commit_artifact_ref(
                root,
                task_path,
                proof.get("result"),
                "result",
                expected_path,
                f"Evaluation commit repair {iteration}",
            )
        )
    return errors


def validate_phase_reconciliation(root: Path, path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        reconciliation = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid phase reconciliation JSON: {rel(root, path)}: {exc}"]
    if not isinstance(reconciliation, dict):
        return [f"Phase reconciliation must be a JSON object: {rel(root, path)}"]
    if reconciliation.get("status") != "satisfied":
        return [f'Phase reconciliation status must be "satisfied": {rel(root, path)}']
    if not isinstance(reconciliation.get("instruction_results"), list):
        return [f"Phase reconciliation must include instruction_results: {rel(root, path)}"]
    if any(item.get("status") == "unverified" for item in reconciliation.get("instruction_results") if isinstance(item, dict)):
        return [f"Phase reconciliation instruction_results must not be unverified: {rel(root, path)}"]
    return []


def phase_runtime_artifact_path(
    task_path: Path,
    phase_number: int,
    stem: str,
    suffix: str,
    expected_attempt: int | None = None,
) -> Path:
    runtime_dir = task_path / "context-pack" / "runtime"
    if isinstance(expected_attempt, int) and expected_attempt > 0:
        attempt_path = runtime_dir / f"phase{phase_number}-{stem}-attempt{expected_attempt}{suffix}"
        return attempt_path
    return runtime_dir / f"phase{phase_number}-{stem}{suffix}"


def validate_runtime_contract_bundle(
    root: Path,
    task_path: Path,
    phase_number: int,
    expected_commands: list[str],
    expected_outputs: list[str],
    expected_repo_outputs: list[str],
    expected_attempt: int | None = None,
) -> list[str]:
    runtime_dir = task_path / "context-pack" / "runtime"
    contract_path = phase_runtime_artifact_path(task_path, phase_number, "contract", ".json", expected_attempt)
    evidence_path = phase_runtime_artifact_path(task_path, phase_number, "evidence", ".json", expected_attempt)
    reconciliation_path = phase_runtime_artifact_path(task_path, phase_number, "reconciliation", ".json", expected_attempt)
    gate_path = phase_runtime_artifact_path(task_path, phase_number, "gate", ".json", expected_attempt)
    quality_path = phase_runtime_artifact_path(task_path, phase_number, "quality", ".json", expected_attempt)
    errors: list[str] = []

    try:
        contract = read_json(contract_path)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return [f"Cannot read phase runtime contract: {rel(root, contract_path)}: {exc}"]
    try:
        evidence = read_json(evidence_path)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return [f"Cannot read phase evidence: {rel(root, evidence_path)}: {exc}"]
    try:
        reconciliation = read_json(reconciliation_path)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return [f"Cannot read phase reconciliation: {rel(root, reconciliation_path)}: {exc}"]
    try:
        gate = read_json(gate_path)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return [f"Cannot read phase gate: {rel(root, gate_path)}: {exc}"]
    try:
        quality = read_json(quality_path)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return [f"Cannot read phase quality result: {rel(root, quality_path)}: {exc}"]
    if quality.get("status") != "passed":
        errors.append(f'Phase quality status must be "passed": {rel(root, quality_path)}')

    if contract_acceptance_commands(contract) != expected_commands:
        errors.append(
            "Runtime contract acceptance_commands must match phase contract. "
            f"expected={expected_commands!r} actual={contract_acceptance_commands(contract)!r}"
        )
    if contract_required_outputs(contract) != expected_outputs:
        errors.append(
            "Runtime contract required_outputs must match phase contract. "
            f"expected={expected_outputs!r} actual={contract_required_outputs(contract)!r}"
        )
    if contract_required_repo_outputs(contract) != expected_repo_outputs:
        errors.append(
            "Runtime contract required_repo_outputs must match phase contract. "
            f"expected={expected_repo_outputs!r} actual={contract_required_repo_outputs(contract)!r}"
        )

    commands = evidence.get("commands") if isinstance(evidence, dict) else None
    actual_commands = [
        item.get("command")
        for item in commands or []
        if isinstance(item, dict)
    ]
    if actual_commands != expected_commands:
        errors.append(
            "Evidence commands must match phase contract. "
            f"expected={expected_commands!r} actual={actual_commands!r}"
        )

    output_entries = evidence.get("required_outputs") if isinstance(evidence, dict) else None
    actual_outputs = [
        item.get("path")
        for item in output_entries or []
        if isinstance(item, dict)
    ]
    if actual_outputs != expected_outputs:
        errors.append(
            "Evidence required_outputs must match phase contract. "
            f"expected={expected_outputs!r} actual={actual_outputs!r}"
        )

    repo_output_entries = evidence.get("required_repo_outputs") if isinstance(evidence, dict) else None
    actual_repo_outputs = [
        item.get("path")
        for item in repo_output_entries or []
        if isinstance(item, dict)
    ]
    if actual_repo_outputs != expected_repo_outputs:
        errors.append(
            "Evidence required_repo_outputs must match phase contract. "
            f"expected={expected_repo_outputs!r} actual={actual_repo_outputs!r}"
        )

    changed_files = evidence.get("changed_files") if isinstance(evidence, dict) else []
    if not isinstance(changed_files, list) or not all(isinstance(item, str) for item in changed_files):
        errors.append("Evidence changed_files must be a string list.")
        changed_files = []
    violations = scope_violations(
        changed_files,
        contract_allowed_paths(contract),
        [
            *required_output_repo_paths(task_path, expected_outputs),
        ],
    )
    if violations:
        errors.append(f"Evidence changed_files include paths outside scope: {violations!r}")

    handoff_path = (
        runtime_dir / f"phase{phase_number}-handoff-attempt{expected_attempt}.md"
        if isinstance(expected_attempt, int)
        and expected_attempt > 0
        and (runtime_dir / f"phase{phase_number}-handoff-attempt{expected_attempt}.md").exists()
        else task_path / "context-pack" / "handoffs" / f"phase{phase_number}.md"
    )
    if handoff_path.exists():
        instruction_ids = [
            item.get("id")
            for item in contract.get("instructions") or []
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        trace_errors = handoff_change_trace_errors(
            handoff_path.read_text(encoding="utf-8", errors="replace"),
            traceable_changed_files(task_path, changed_files, expected_outputs),
            instruction_ids,
        )
        errors.extend(f"Phase {phase_number} handoff change trace: {error}" for error in trace_errors)

    contract_instruction_ids = [
        item.get("id")
        for item in contract.get("instructions", [])
        if isinstance(item, dict)
    ]
    reconciliation_items = reconciliation.get("instruction_results")
    actual_instruction_ids = [
        item.get("id")
        for item in reconciliation_items or []
        if isinstance(item, dict)
    ]
    if actual_instruction_ids != contract_instruction_ids:
        errors.append(
            "Reconciliation instruction ids must match contract instructions. "
            f"expected={contract_instruction_ids!r} actual={actual_instruction_ids!r}"
        )
    if any(item.get("status") == "blocked" for item in reconciliation_items or [] if isinstance(item, dict)):
        errors.append("Reconciliation instruction results must not be blocked for a completed phase.")
    if any(item.get("status") == "unverified" for item in reconciliation_items or [] if isinstance(item, dict)):
        errors.append("Reconciliation instruction_results must not be unverified for a completed phase.")

    gate_checks = gate.get("checks") if isinstance(gate, dict) else []
    if not isinstance(gate_checks, list) or not gate_checks:
        errors.append("Gate checks must be a non-empty list.")
    elif any(check.get("status") != "passed" for check in gate_checks if isinstance(check, dict)):
        errors.append("All gate checks must be passed for a completed phase.")

    return errors


def validate_phase_result(
    root: Path,
    task_path: Path,
    phase_number: int,
    expected_commands: list[str],
    expected_outputs: list[str],
    expected_repo_outputs: list[str],
    *,
    expected_attempt: int | None = None,
    strict_current_harness: bool = False,
) -> list[str]:
    runtime_dir = task_path / "context-pack" / "runtime"
    alias_result_path = runtime_dir / f"phase{phase_number}-result.json"
    canonical_result_path = (
        runtime_dir / f"phase{phase_number}-result-attempt{expected_attempt}.json"
        if isinstance(expected_attempt, int) and expected_attempt > 0
        else None
    )
    if canonical_result_path is not None and not canonical_result_path.exists():
        return [f"Missing phase result: {rel(root, canonical_result_path)}"]
    result_path = canonical_result_path if canonical_result_path is not None else alias_result_path
    if not result_path.exists():
        expected_path = canonical_result_path or alias_result_path
        return [f"Missing phase result: {rel(root, expected_path)}"]
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid phase result JSON: {rel(root, result_path)}: {exc}"]

    if not isinstance(result, dict):
        return [f"Phase result must be a JSON object: {rel(root, result_path)}"]

    errors: list[str] = []
    required_fields = {
        "phase",
        "status",
        "attempt",
        "codex_exit_code",
        "changed_files",
        "commands_run",
        "tests_passed",
        "required_outputs",
        "artifacts",
    }
    if expected_repo_outputs or "required_repo_outputs" in result:
        required_fields.add("required_repo_outputs")
    missing = sorted(required_fields - set(result))
    if missing:
        errors.append(f"Phase result missing fields: {', '.join(missing)}")
    if result.get("phase") != phase_number:
        errors.append(f"`phase` must be {phase_number}.")
    if result.get("status") != "completed":
        errors.append('`status` must be "completed".')
    attempt = result.get("attempt")
    if not isinstance(attempt, int) or attempt <= 0:
        errors.append("`attempt` must be a positive integer.")
        attempt = None
    elif isinstance(expected_attempt, int) and expected_attempt > 0 and attempt != expected_attempt:
        errors.append(f"`attempt` must match task index attempts ({expected_attempt}).")
    if result.get("codex_exit_code") != 0:
        errors.append("`codex_exit_code` must be 0 for a completed phase.")
    approved_policy_packs, lineage_errors = approved_policy_pack_lineage(root, task_path)
    errors.extend(lineage_errors)
    policy_pack = result.get("policy_pack")
    if strict_current_harness or policy_pack is not None:
        errors.extend(
            validate_policy_pack_metadata(
                policy_pack,
                f"Phase {phase_number} result",
                strict_current=strict_current_harness,
                approved_fingerprints=approved_policy_packs or None,
            )
        )
    if strict_current_harness or result.get("runner_version") is not None:
        errors.extend(
            validate_runner_version(
                result.get("runner_version"),
                f"Phase {phase_number} result",
                strict_current=strict_current_harness,
            )
        )
    if strict_current_harness or result.get("harness_attestation") is not None:
        errors.extend(
            validate_harness_attestation_metadata(
                result.get("harness_attestation"),
                f"Phase {phase_number} result",
                strict_current=strict_current_harness,
            )
        )
    errors.extend(require_string_list(result.get("changed_files"), "changed_files"))
    errors.extend(validate_commands_run(result.get("commands_run"), expected_commands))
    if result.get("tests_passed") is not True:
        errors.append("`tests_passed` must be true for a completed phase.")
    errors.extend(validate_required_outputs(root, task_path, result.get("required_outputs"), expected_outputs))
    if expected_repo_outputs or "required_repo_outputs" in result:
        errors.extend(validate_required_repo_outputs(root, result.get("required_repo_outputs"), expected_repo_outputs))
    errors.extend(
        validate_artifacts(
            root,
            task_path,
            result.get("artifacts"),
            phase_number,
            attempt,
            strict_attempt_artifacts=isinstance(expected_attempt, int) and expected_attempt > 0,
        )
    )
    artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), dict) else {}
    if isinstance(attempt, int) and (strict_current_harness or isinstance(policy_pack, dict)):
        errors.extend(
            validate_ac_results_metadata(
                root,
                task_path,
                phase_number,
                attempt,
                artifacts,
                policy_pack if isinstance(policy_pack, dict) else None,
                result.get("commands_run"),
                approved_policy_packs=approved_policy_packs or None,
                strict_current_harness=strict_current_harness,
            )
        )
    expected_handoff_paths = set()
    if isinstance(expected_attempt, int) and expected_attempt > 0:
        expected_handoff_paths.add(f"context-pack/runtime/phase{phase_number}-handoff-attempt{expected_attempt}.md")
    else:
        expected_handoff_paths.add(f"context-pack/handoffs/phase{phase_number}.md")
    if isinstance(attempt, int) and not (isinstance(expected_attempt, int) and expected_attempt > 0):
        expected_handoff_paths.add(f"context-pack/runtime/phase{phase_number}-handoff-attempt{attempt}.md")
    if artifacts.get("handoff") not in expected_handoff_paths:
        errors.append(
            f"`artifacts.handoff` must be one of {sorted(expected_handoff_paths)!r}."
        )
    if "attempt_commit" not in artifacts:
        errors.append("Phase result artifacts must include attempt_commit.")
    elif isinstance(attempt, int):
        errors.extend(
            validate_phase_attempt_commit(
                root,
                task_path,
                phase_number,
                attempt,
                result_path,
                result,
                artifacts,
                strict_current_harness=strict_current_harness,
            )
        )
    if isinstance(attempt, int):
        try:
            contract_path = None
            raw_contract_path = artifacts.get("contract")
            if isinstance(raw_contract_path, str):
                contract_path, contract_path_errors = resolve_task_relative_path(
                    root,
                    task_path,
                    raw_contract_path,
                    "artifacts.contract",
                )
                errors.extend(contract_path_errors)
            if contract_path is None:
                contract_path = task_path / "context-pack" / "runtime" / f"phase{phase_number}-contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            contract = {}
        if isinstance(contract, dict) and contract.get("closes_obligations"):
            if "obligation_closure" not in artifacts:
                errors.append("Phase result artifacts must include obligation_closure for closed design obligations.")
            else:
                errors.extend(
                    validate_obligation_closure_ledger(
                        root,
                        task_path,
                        phase_number,
                        attempt,
                        artifacts,
                        strict_current_harness=strict_current_harness,
                    )
                )
    return errors


def load_completed_phase_result(
    task_path: Path,
    phase_number: int,
    expected_attempt: int | None,
) -> dict[str, Any] | None:
    runtime_dir = task_path / "context-pack" / "runtime"
    result_path = (
        runtime_dir / f"phase{phase_number}-result-attempt{expected_attempt}.json"
        if isinstance(expected_attempt, int) and expected_attempt > 0
        else runtime_dir / f"phase{phase_number}-result.json"
    )
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return result if isinstance(result, dict) else None


def validate_phase_attempt_commit(
    root: Path,
    task_path: Path,
    phase_number: int,
    attempt: int,
    result_path: Path,
    result_data: dict[str, Any],
    artifacts: dict[str, Any],
    *,
    strict_current_harness: bool = False,
) -> list[str]:
    raw_path = artifacts.get("attempt_commit")
    if not isinstance(raw_path, str):
        return ["Phase result artifacts attempt_commit must be a path."]
    commit_path, path_errors = resolve_task_relative_path(root, task_path, raw_path, "artifacts.attempt_commit")
    if path_errors:
        return path_errors
    assert commit_path is not None
    try:
        commit = json.loads(commit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Invalid attempt_commit JSON: {rel(root, commit_path)}: {exc}"]
    errors: list[str] = []
    approved_policy_packs, lineage_errors = approved_policy_pack_lineage(root, task_path)
    errors.extend(lineage_errors)
    if strict_current_harness or "schema_version" in commit:
        if commit.get("schema_version") != 1:
            errors.append("attempt_commit schema_version must be 1.")
    if strict_current_harness or "commit_scope" in commit:
        if commit.get("commit_scope") != "runtime_attempt_bundle":
            errors.append('attempt_commit commit_scope must be "runtime_attempt_bundle".')
    if strict_current_harness or "status" in commit:
        if commit.get("status") != "committed":
            errors.append('attempt_commit status must be "committed".')
    commit_policy_pack = commit.get("policy_pack")
    result_policy_pack = result_data.get("policy_pack")
    if (
        isinstance(commit_policy_pack, dict)
        and isinstance(result_policy_pack, dict)
        and commit_policy_pack != result_policy_pack
    ):
        errors.append("attempt_commit policy_pack does not match phase result.")
    if strict_current_harness or commit_policy_pack is not None:
        errors.extend(
            validate_policy_pack_metadata(
                commit_policy_pack,
                "attempt_commit",
                strict_current=strict_current_harness,
                approved_fingerprints=approved_policy_packs or None,
            )
        )
    if strict_current_harness or commit.get("runner_version") is not None:
        errors.extend(
            validate_runner_version(
                commit.get("runner_version"),
                "attempt_commit",
                strict_current=strict_current_harness,
            )
        )
    result_attestation = result_data.get("harness_attestation")
    commit_attestation = commit.get("harness_attestation")
    if (
        isinstance(commit_attestation, dict)
        and isinstance(result_attestation, dict)
        and commit_attestation != result_attestation
    ):
        errors.append("attempt_commit harness_attestation does not match phase result.")
    if strict_current_harness or commit_attestation is not None:
        errors.extend(
            validate_harness_attestation_metadata(
                commit_attestation,
                "attempt_commit",
                strict_current=strict_current_harness,
            )
        )
    if commit.get("phase") != phase_number or commit.get("attempt") != attempt:
        errors.append("attempt_commit phase/attempt does not match phase result.")
    if "reset_generation" in commit or "reset_generation" in result_data:
        if commit.get("reset_generation") != result_data.get("reset_generation"):
            errors.append("attempt_commit reset_generation does not match phase result.")
    result_ref = commit.get("result") if isinstance(commit.get("result"), dict) else {}
    result_ref_path = result_ref.get("path")
    commit_result_path: Path | None = None
    if not isinstance(result_ref_path, str):
        errors.append("attempt_commit result path must be a path.")
    else:
        commit_result_path, path_errors = resolve_task_relative_path(
            root,
            task_path,
            result_ref_path,
            "attempt_commit.result.path",
        )
        errors.extend(path_errors)
        if commit_result_path is not None and commit_result_path != result_path.resolve():
            expected_attempt_result = (
                task_path / "context-pack" / "runtime" / f"phase{phase_number}-result-attempt{attempt}.json"
            ).resolve()
            if commit_result_path != expected_attempt_result:
                errors.append("attempt_commit result path does not match phase result.")
            else:
                try:
                    commit_result_data = json.loads(commit_result_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    errors.append(f"Invalid canonical phase result JSON: {rel(root, commit_result_path)}: {exc}")
                else:
                    if commit_result_data != result_data:
                        errors.append("attempt_commit canonical result does not match phase result alias.")
    result_hash_path = commit_result_path or result_path
    if not result_hash_path.exists() or not result_hash_path.is_file():
        errors.append(f"attempt_commit result path does not exist: {rel(root, result_hash_path)}")
    elif result_ref.get("sha256") != file_sha256(result_hash_path):
        errors.append("attempt_commit result sha256 does not match phase result.")
    artifact_entries = commit.get("artifacts") if isinstance(commit.get("artifacts"), list) else []
    by_name = {item.get("name"): item for item in artifact_entries if isinstance(item, dict)}
    for item in artifact_entries:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "unknown")
        entry_path = item.get("path")
        if isinstance(entry_path, str):
            _target, path_errors = resolve_task_relative_path(
                root,
                task_path,
                entry_path,
                f"attempt_commit.artifacts.{name}.path",
            )
            errors.extend(path_errors)
    for name, path_value in artifacts.items():
        if name == "attempt_commit" or not isinstance(path_value, str):
            continue
        artifact_path, path_errors = resolve_task_relative_path(root, task_path, path_value, f"artifacts.{name}")
        errors.extend(path_errors)
        if artifact_path is None:
            continue
        entry = by_name.get(name)
        if not isinstance(entry, dict):
            errors.append(f"{name} is missing from attempt_commit artifacts.")
            continue
        if entry.get("path") != path_value:
            errors.append(f"{name} path does not match attempt_commit.")
            continue
        if not artifact_path.exists() or not artifact_path.is_file():
            errors.append(f"{name} artifact path does not exist: {rel(root, artifact_path)}")
        elif entry.get("sha256") != file_sha256(artifact_path):
            errors.append(f"{name} sha256 does not match attempt_commit.")
    return errors


def validate_latest_repo_content_matches_current(root: Path, phase_results: list[tuple[int, dict[str, Any]]]) -> list[str]:
    latest: dict[str, tuple[int, str]] = {}
    for phase_number, result in phase_results:
        repo_content = result.get("repo_content") if isinstance(result, dict) else {}
        for section in ["changed_files", "required_repo_outputs"]:
            for item in repo_content.get(section) or [] if isinstance(repo_content, dict) else []:
                if not isinstance(item, dict):
                    continue
                path = item.get("path")
                digest = item.get("after_digest")
                if digest is None and isinstance(item.get("after"), dict):
                    digest = item["after"].get("sha256") if item["after"].get("exists") else "<deleted>"
                if isinstance(path, str) and isinstance(digest, str):
                    latest[path] = (phase_number, digest)
    errors: list[str] = []
    for raw_path, (_phase, digest) in latest.items():
        current = file_sha256(root / raw_path) if (root / raw_path).exists() and (root / raw_path).is_file() else "<deleted>"
        if current != digest:
            errors.append(f"Repo content attestation for {raw_path} does not match current file digest.")
    return errors


def validate_repo_content_attestation_shape(value: object, label: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} repo_content must be an object."]
    errors: list[str] = []
    changed_files = value.get("changed_files")
    required_repo_outputs = value.get("required_repo_outputs")
    if not isinstance(changed_files, list):
        errors.append(f"{label} repo_content.changed_files must be a list.")
        changed_files = []
    if not isinstance(required_repo_outputs, list):
        errors.append(f"{label} repo_content.required_repo_outputs must be a list.")
        required_repo_outputs = []
    if value.get("changed_files_digest") != stable_json_sha256(changed_files):
        errors.append(f"{label} repo_content.changed_files_digest does not match changed_files.")
    if value.get("required_repo_outputs_digest") != stable_json_sha256(required_repo_outputs):
        errors.append(f"{label} repo_content.required_repo_outputs_digest does not match required_repo_outputs.")
    content_without_digest = {key: item for key, item in value.items() if key != "digest"}
    if value.get("digest") != stable_json_sha256(content_without_digest):
        errors.append(f"{label} repo_content.digest does not match repo_content.")
    return errors


def repo_content_changed_paths(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    paths: list[str] = []
    for item in value.get("changed_files") or []:
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            paths.append(item["path"])
    return sorted(paths)


def evaluation_repair_result_iteration(path: Path) -> int | None:
    match = re.fullmatch(r"evaluation-repair(\d+)-result\.json", path.name)
    if not match:
        return None
    return int(match.group(1))


def validate_evaluation_repair_result(root: Path, task_path: Path, path: Path, data: dict[str, Any]) -> list[str]:
    label = f"Evaluation repair result {path.name}"
    errors: list[str] = []
    expected_iteration = evaluation_repair_result_iteration(path)
    if expected_iteration is None:
        errors.append(f"{label} filename must include a numeric repair iteration.")
    if data.get("iteration") != expected_iteration:
        errors.append(f"{label} iteration must match filename iteration {expected_iteration}.")
    if data.get("schema_version") != 1:
        errors.append(f"{label} schema_version must be 1.")
    if data.get("runner_version") != HARNESS_VERSION:
        errors.append(f"{label} runner_version must match current harness version {HARNESS_VERSION}.")
    if data.get("repair_scope") != "evaluation_improvement":
        errors.append(f'{label} repair_scope must be "evaluation_improvement".')
    if data.get("status") != "completed":
        errors.append(f'{label} status must be "completed".')
    if data.get("codex_exit_code") != 0:
        errors.append(f"{label} codex_exit_code must be 0.")
    if data.get("scope_violations") not in (None, []):
        errors.append(f"{label} scope_violations must be empty.")
    changed_files = data.get("changed_files")
    if not isinstance(changed_files, list) or not all(isinstance(item, str) for item in changed_files):
        errors.append(f"{label} changed_files must be a list of paths.")
        changed_files = []
    allowed_paths = data.get("allowed_paths")
    if not isinstance(allowed_paths, list) or not all(isinstance(item, str) for item in allowed_paths):
        errors.append(f"{label} allowed_paths must be a list of paths.")
        allowed_paths = []
    if data.get("handoff_exists") is not True:
        errors.append(f"{label} handoff_exists must be true.")
    handoff = data.get("handoff")
    ignored_paths: list[str] = []
    if not isinstance(handoff, str) or not handoff:
        errors.append(f"{label} handoff must be a path.")
    else:
        ignored_paths = [f"tasks/{task_path.name}/{handoff.strip('/')}"]
        handoff_path, path_errors = resolve_task_relative_path(root, task_path, handoff, f"{label}.handoff")
        errors.extend(path_errors)
        if handoff_path is not None and (not handoff_path.exists() or not handoff_path.is_file()):
            errors.append(f"{label} handoff path does not exist: {rel(root, handoff_path)}")
    recomputed_violations = scope_violations(
        [path for path in changed_files if not path_allowed(path, ignored_paths)],
        allowed_paths,
        [],
    )
    if data.get("scope_violations") != recomputed_violations:
        errors.append(f"{label} scope_violations do not match changed_files and allowed_paths.")
    repo_content = data.get("repo_content")
    errors.extend(validate_repo_content_attestation_shape(repo_content, label))
    if sorted(changed_files) != repo_content_changed_paths(repo_content):
        errors.append(f"{label} changed_files must match repo_content.changed_files.")
    errors.extend(
        validate_policy_pack_metadata(
            data.get("policy_pack"),
            label,
            strict_current=True,
        )
    )
    errors.extend(
        validate_harness_attestation_metadata(
            data.get("harness_attestation"),
            label,
            strict_current=True,
        )
    )
    artifacts = data.get("artifacts") if isinstance(data.get("artifacts"), dict) else {}
    for name in ["prompt", "stdout", "stderr", "last_message"]:
        raw_path = artifacts.get(name)
        if not isinstance(raw_path, str) or not raw_path:
            errors.append(f"{label} artifacts.{name} must be a path.")
            continue
        artifact_path, path_errors = resolve_task_relative_path(
            root,
            task_path,
            raw_path,
            f"{label}.artifacts.{name}",
        )
        errors.extend(path_errors)
        if artifact_path is not None and (not artifact_path.exists() or not artifact_path.is_file()):
            errors.append(f"{label} artifacts.{name} path does not exist: {rel(root, artifact_path)}")
    if isinstance(expected_iteration, int):
        expected_artifacts = {
            "prompt": f"context-pack/runtime/evaluation-repair{expected_iteration}-prompt.md",
            "stdout": f"context-pack/runtime/evaluation-repair{expected_iteration}-output.jsonl",
            "stderr": f"context-pack/runtime/evaluation-repair{expected_iteration}-stderr.txt",
            "last_message": f"context-pack/runtime/evaluation-repair{expected_iteration}-last-message.json",
            "handoff": f"context-pack/handoffs/evaluation-repair{expected_iteration}.md",
        }
        artifact_refs = artifact_entries_by_name(data.get("artifact_refs"))
        for name, expected_path in expected_artifacts.items():
            errors.extend(
                validate_commit_artifact_ref(
                    root,
                    task_path,
                    artifact_refs.get(name),
                    name,
                    expected_path,
                    f"{label} artifact_ref",
                )
            )
        last_message_path, path_errors = resolve_task_relative_path(
            root,
            task_path,
            expected_artifacts["last_message"],
            f"{label}.last_message",
        )
        errors.extend(path_errors)
        if last_message_path is not None and last_message_path.exists() and last_message_path.is_file():
            try:
                last_message = json.loads(last_message_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"{label} last_message is invalid JSON: {exc}")
            else:
                if not isinstance(last_message, dict):
                    errors.append(f"{label} last_message must be a JSON object.")
                elif last_message.get("status") != "completed":
                    errors.append(f'{label} last_message status must be "completed".')
    return errors


def validate_evaluation_repair_results(
    root: Path,
    task_path: Path,
    runtime_dir: Path,
    *,
    base_phase_results: list[tuple[int, dict[str, Any]]] | None = None,
) -> list[str]:
    phase_results: list[tuple[int, dict[str, Any]]] = list(base_phase_results or [])
    errors: list[str] = []
    repair_paths = sorted(
        runtime_dir.glob("evaluation-repair*-result.json"),
        key=lambda item: (
            evaluation_repair_result_iteration(item)
            if evaluation_repair_result_iteration(item) is not None
            else 10**9
        ),
    )
    for path in repair_paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [f"Invalid evaluation repair result JSON: {rel(root, path)}: {exc}"]
        if isinstance(data, dict):
            errors.extend(validate_evaluation_repair_result(root, task_path, path, data))
            iteration = data.get("iteration")
            order = 1_000_000 + (iteration if isinstance(iteration, int) else 0)
            phase_results.append((order, data))
        else:
            errors.append(f"Evaluation repair result must be a JSON object: {rel(root, path)}")
    errors.extend(validate_latest_repo_content_matches_current(root, phase_results))
    return errors


def validate_obligation_closure_ledger(
    root: Path,
    task_path: Path,
    phase_number: int,
    attempt: int,
    artifacts: dict[str, Any],
    *,
    strict_current_harness: bool = False,
) -> list[str]:
    raw_path = artifacts.get("obligation_closure") if isinstance(artifacts, dict) else None
    if not isinstance(raw_path, str):
        return []
    path = task_path / raw_path
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Invalid obligation closure ledger JSON: {rel(root, path)}: {exc}"]
    errors: list[str] = []
    if ledger.get("phase") != phase_number or ledger.get("attempt") != attempt:
        errors.append("obligation_closure phase/attempt does not match phase result.")
    approval_path = task_path / "context-pack" / "static" / "design-approval.json"
    approved_bundle_sha = None
    if approval_path.exists():
        try:
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            approved_bundle_sha = approval.get("approved_bundle_sha256") if isinstance(approval, dict) else None
        except json.JSONDecodeError:
            approved_bundle_sha = None
    if approved_bundle_sha and ledger.get("design_approval_bundle_sha256") not in {None, approved_bundle_sha}:
        errors.append("obligation_closure design_approval_bundle_sha256 does not match design approval.")
    ac_commands: dict[str, dict[str, Any]] = {}
    raw_ac = artifacts.get("ac_results") if isinstance(artifacts, dict) else None
    if isinstance(raw_ac, str):
        try:
            ac_results = json.loads((task_path / raw_ac).read_text(encoding="utf-8"))
            for command in ac_results.get("commands") or []:
                if isinstance(command, dict):
                    for key in ["id", "command"]:
                        value = command.get(key)
                        if isinstance(value, str):
                            ac_commands[value] = command
        except (OSError, json.JSONDecodeError):
            ac_commands = {}
    for assertion in ledger.get("assertions") or []:
        if not isinstance(assertion, dict):
            continue
        errors.extend(validate_runner_version(assertion.get("runner_version"), "obligation_closure assertion", strict_current=strict_current_harness))
        raw_contract = artifacts.get("contract") if isinstance(artifacts, dict) else None
        contract_path = (
            task_path / raw_contract
            if isinstance(raw_contract, str) and raw_contract
            else task_path / "context-pack" / "runtime" / f"phase{phase_number}-contract.json"
        )
        design_path = task_path / "context-pack" / "static" / "design-contract.json"
        if contract_path.exists() and assertion.get("phase_contract_sha256") != file_sha256(contract_path):
            errors.append("obligation_closure phase_contract_sha256 does not match phase result contract artifact.")
        if design_path.exists() and assertion.get("design_contract_sha256") != file_sha256(design_path):
            errors.append("obligation_closure design_contract_sha256 does not match current design contract.")
        if approved_bundle_sha and assertion.get("design_approval_bundle_sha256") not in {None, approved_bundle_sha}:
            errors.append("obligation_closure assertion design_approval_bundle_sha256 does not match design approval.")
        command_ref = assertion.get("command_ref")
        command = ac_commands.get(command_ref) if isinstance(command_ref, str) else None
        if command is not None and assertion.get("command_output_sha256"):
            expected = command.get("command_output_sha256")
            if not expected:
                output = command.get("output") if isinstance(command.get("output"), str) else str(command.get("output_tail") or "")
                expected = text_sha256(output)
            if assertion.get("command_output_sha256") != expected:
                errors.append("obligation_closure command_output_sha256 does not match AC command output digest.")
    return errors


def phase_repair_packet_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-repair-packet.json"


def phase_repair_packet_summary_path(task_path: Path, phase_number: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-repair-packet.md"


def phase_attempt_repair_packet_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-repair-packet-attempt{attempt}.json"


def phase_attempt_repair_packet_summary_path(task_path: Path, phase_number: int, attempt: int) -> Path:
    return task_path / "context-pack" / "runtime" / f"phase{phase_number}-repair-packet-attempt{attempt}.md"


def read_phase_attempt_manifest(
    root: Path,
    task_path: Path,
    phase_number: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    path = phase_attempt_manifest_path(task_path, phase_number)
    return read_attempt_manifest_records_with_errors(
        task_path,
        phase_number,
        invalid_json_prefix=f"Invalid attempt manifest JSON: {rel(root, path)}",
        non_object_prefix=f"Attempt manifest record must be a JSON object: {rel(root, path)}",
    )


def validate_repair_packet_file(
    root: Path,
    task_path: Path,
    path: Path,
    phase_number: int,
    *,
    expected_attempt: int | None = None,
    expected_failure: object = None,
    expected_artifacts: object = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        packet = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"Invalid repair packet JSON: {rel(root, path)}: {exc}"]
    if not isinstance(packet, dict):
        return None, [f"Repair packet must be a JSON object: {rel(root, path)}"]
    errors: list[str] = []
    if packet.get("phase") != phase_number:
        errors.append(f"Repair packet phase must be {phase_number}: {rel(root, path)}")
    attempt = packet.get("attempt")
    if expected_attempt is not None and attempt != expected_attempt:
        errors.append(f"Repair packet attempt must be {expected_attempt}: {rel(root, path)}")
    if packet.get("status") != "repair_required":
        errors.append(f'Repair packet status must be "repair_required": {rel(root, path)}')
    failure = packet.get("failure")
    if not isinstance(failure, dict):
        errors.append(f"Repair packet failure must be an object: {rel(root, path)}")
    else:
        if not isinstance(failure.get("type"), str) or not failure.get("type"):
            errors.append(f"Repair packet failure.type must be a non-empty string: {rel(root, path)}")
        if not isinstance(failure.get("message"), str) or not failure.get("message"):
            errors.append(f"Repair packet failure.message must be a non-empty string: {rel(root, path)}")
        if not isinstance(failure.get("retryable"), bool):
            errors.append(f"Repair packet failure.retryable must be boolean: {rel(root, path)}")
    if isinstance(expected_failure, dict) and failure != expected_failure:
        errors.append(f"Repair packet failure does not match attempt manifest: {rel(root, path)}")
    artifacts = packet.get("failed_attempt_artifacts")
    if artifacts is not None:
        if not isinstance(artifacts, list):
            errors.append(f"Repair packet failed_attempt_artifacts must be a list: {rel(root, path)}")
        else:
            for index, entry in enumerate(artifacts):
                errors.extend(
                    validate_runtime_artifact_ref(
                        root,
                        task_path,
                        entry,
                        f"Repair packet failed_attempt_artifacts[{index}]",
                    )
                )
    if isinstance(expected_artifacts, list) and artifacts != expected_artifacts:
        errors.append(f"Repair packet failed_attempt_artifacts do not match attempt manifest: {rel(root, path)}")
    runtime_integrity_report = packet.get("runtime_integrity_report")
    if runtime_integrity_report is not None:
        errors.extend(
            validate_runtime_integrity_report(
                root,
                task_path,
                runtime_integrity_report,
                phase_number,
                expected_attempt if expected_attempt is not None else int(attempt or 0),
                "Repair packet runtime_integrity_report",
            )
        )
    return packet, errors


def validate_phase_attempt_manifest(
    root: Path,
    task_path: Path,
    phase: dict[str, Any],
) -> list[str]:
    phase_number = int(phase["phase"])
    records, errors = read_phase_attempt_manifest(root, task_path, phase_number)
    errors.extend(
        attempt_manifest_semantic_errors(
            task_path,
            phase_number,
            records,
            label_prefix="Attempt manifest phase {phase} record {index}",
        )
    )
    terminal_by_attempt: dict[int, list[dict[str, Any]]] = {}
    for index, record in enumerate(records):
        label = f"Attempt manifest phase {phase_number} record {index + 1}"
        record_type = record.get("record_type")
        attempt = record.get("attempt")
        if not isinstance(attempt, int) or attempt <= 0:
            continue
        if isinstance(record_type, str) and record_type in TERMINAL_ATTEMPT_RECORD_TYPES:
            terminal_by_attempt.setdefault(attempt, []).append(record)
        errors.extend(validate_runner_version(record.get("runner_version"), label))
        policy = record.get("policy_pack")
        if policy is not None:
            errors.extend(validate_policy_pack_metadata(policy, label))
        attestation = record.get("harness_attestation")
        if attestation is not None:
            errors.extend(validate_harness_attestation_metadata(attestation, label))

    for attempt, terminals in terminal_by_attempt.items():
        if len(terminals) > 1:
            errors.append(f"Attempt manifest phase {phase_number} attempt {attempt} has multiple terminal records.")
        terminal = terminals[-1]
        record_type = terminal.get("record_type")
        if record_type in {"attempt_failed", "attempt_interrupted"}:
            packet_ref = terminal.get("repair_packet") if isinstance(terminal.get("repair_packet"), dict) else {}
            raw_packet_path = packet_ref.get("path")
            if isinstance(raw_packet_path, str):
                packet_path, path_errors = resolve_task_relative_path(
                    root,
                    task_path,
                    raw_packet_path,
                    f"Attempt manifest phase {phase_number} attempt {attempt}.repair_packet.path",
                )
                errors.extend(path_errors)
                if packet_path is not None:
                    _packet, packet_errors = validate_repair_packet_file(
                        root,
                        task_path,
                        packet_path,
                        phase_number,
                        expected_attempt=attempt,
                        expected_failure=terminal.get("failure"),
                        expected_artifacts=terminal.get("artifacts"),
                    )
                    errors.extend(packet_errors)

    expected_attempt = phase.get("attempts")
    if phase.get("status") == "completed":
        if isinstance(expected_attempt, int) and expected_attempt > 0:
            if not records:
                errors.append(f"Completed phase {phase_number} attempt {expected_attempt} is missing attempt manifest records.")
            else:
                committed = [
                    record
                    for record in terminal_by_attempt.get(expected_attempt, [])
                    if record.get("record_type") == "attempt_committed"
                ]
                if not committed:
                    errors.append(f"Completed phase {phase_number} attempt {expected_attempt} is missing attempt_committed manifest record.")
        if phase_repair_packet_path(task_path, phase_number).exists():
            errors.append(f"Completed phase {phase_number} must not retain active repair packet alias.")
        if phase_repair_packet_summary_path(task_path, phase_number).exists():
            errors.append(f"Completed phase {phase_number} must not retain active repair packet summary alias.")

    active_packet = phase_repair_packet_path(task_path, phase_number)
    if active_packet.exists() and phase.get("status") != "completed":
        _packet, packet_errors = validate_repair_packet_file(root, task_path, active_packet, phase_number)
        errors.extend(packet_errors)
        if not phase_repair_packet_summary_path(task_path, phase_number).exists():
            errors.append(f"Active repair packet summary is missing for phase {phase_number}.")
    return errors


def verify(
    root: Path,
    task_path: Path,
    require_evaluation: bool,
    require_design_approval: bool,
    strict_current_harness: bool = False,
) -> list[str]:
    errors: list[str] = []
    task_index_path = task_path / "index.json"
    errors.extend(require_file(root, task_index_path, "task index", check_placeholder=False))
    if errors:
        return errors

    task_index = read_json(task_index_path)
    task_dir = task_path.name
    decision_registry, registry_errors = load_decision_registry(task_path)
    errors.extend(registry_errors)
    if not registry_errors:
        errors.extend(validate_decision_files(decision_registry))
        errors.extend(validate_open_decisions(decision_registry))

    common_docs = [root / raw for raw in task_index.get("common_docs") or []]
    if not common_docs:
        errors.append("Task index must list common_docs.")
    if root / IMPLEMENTATION_QUALITY_DOC not in common_docs:
        errors.append(f"Task index common_docs must include {IMPLEMENTATION_QUALITY_DOC}")
    for path in common_docs:
        errors.extend(require_file(root, path, "common doc"))
    if has_unsafe_path_errors(errors):
        return errors

    task_docs = [root / raw for raw in task_index.get("docs") or []]
    expected_task_doc_dir = task_path / "docs"
    if len(task_docs) < len(MANDATORY_TASK_DOCS):
        errors.append("Task index must list mandatory task docs.")
    for filename in MANDATORY_TASK_DOCS:
        expected = expected_task_doc_dir / filename
        errors.extend(require_file(root, expected, "task doc"))
        if expected not in task_docs:
            errors.append(f"Task index docs must include {rel(root, expected)}")
    for path in task_docs:
        if not str(path).startswith(str(expected_task_doc_dir)):
            errors.append(f"Task-specific doc must live under {rel(root, expected_task_doc_dir)}: {rel(root, path)}")
        errors.extend(require_file(root, path, "task doc"))
    if has_unsafe_path_errors(errors):
        return errors
    errors.extend(validate_design_review(root, task_path, task_docs))

    static_dir = task_path / "context-pack" / "static"
    for filename in MANDATORY_STATIC_FILES:
        errors.extend(require_file(root, static_dir / filename, "static context"))
    if has_unsafe_path_errors(errors):
        return errors
    if require_design_approval:
        errors.extend(validate_design_approval(root, task_path, strict_current_harness=strict_current_harness))
    design_info = design_doc_info(root, task_path)
    design_kind = design_info[2] if design_info else None
    approved_design_paths: list[str] = []
    design_ref_ids: set[str] = set()
    if design_info and design_kind == "review":
        design_text, design_text_errors = safe_task_text(root, design_info[0], "design review")
        errors.extend(design_text_errors)
        if design_text is None:
            return errors
        approved_design_paths = extract_design_repo_paths(design_text)
        design_contract_path = static_dir / "design-contract.json"
        design_ref_ids, obligation_ids, design_contract_errors = validate_design_contract(
            root,
            design_contract_path,
            design_text,
            approved_design_paths,
        )
        errors.extend(design_contract_errors)
        try:
            design_contract = json.loads(design_contract_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            design_contract = {}
        artifact = design_contract.get("artifact_persistence") if isinstance(design_contract, dict) else None
        for item in artifact.get("required_paths") or [] if isinstance(artifact, dict) else []:
            raw_path = item.get("path") if isinstance(item, dict) else None
            if not isinstance(raw_path, str):
                continue
            result = subprocess.run(
                ["git", "check-ignore", "-q", "--", raw_path],
                cwd=root,
                check=False,
                text=True,
                capture_output=True,
            )
            if result.returncode == 0:
                errors.append(f"design-contract.json artifact_persistence path is ignored by git: {raw_path}")
        taxonomy_ids, taxonomy_errors = validate_review_taxonomy(root, static_dir / "review-taxonomy.json")
        errors.extend(taxonomy_errors)
        universe = ReferenceUniverse()
        for raw_path in approved_design_paths:
            universe.add_path(raw_path)
        for item in design_ref_ids:
            prefix = item.split(".", 1)[0] if "." in item else item
            source = {
                "txn": "transaction_boundaries",
                "transaction": "transaction_boundaries",
                "retry": "retry_triggers",
                "artifact": "artifact_persistence",
            }.get(prefix, prefix)
            universe.add("design", item, source=source)
        for item in obligation_ids:
            universe.add("obligation", item)
        for item in approved_decision_ids(decision_registry):
            universe.add("decision", item)
        for item in architecture_ref_ids(decision_registry):
            universe.add("architecture", item)
        errors.extend(validate_review_findings(root, static_dir / "review-findings.json", taxonomy_ids, universe))
        errors.extend(validate_review_coverage(root, static_dir / "review-coverage.json", taxonomy_ids, obligation_ids, universe))
    else:
        obligation_ids = set()

    phase_count = int(task_index.get("totalPhases") or len(task_index.get("phases") or []))
    phases = task_index.get("phases") or []
    if phase_count != len(phases):
        errors.append("totalPhases must match phases length.")

    runtime_dir = task_path / "context-pack" / "runtime"
    handoff_dir = task_path / "context-pack" / "handoffs"
    phase_design_refs: list[tuple[int, str]] = []
    phase_closes_obligations: set[str] = set()
    completed_phase_results: list[tuple[int, dict[str, Any]]] = []
    for phase in phases:
        phase_number = int(phase["phase"])
        phase_path = task_path / "phases" / f"phase{phase_number}.md"
        errors.extend(require_file(root, phase_path, "phase file"))
        expected_commands = list(phase.get("ac_commands") or [])
        expected_outputs = list(phase.get("required_outputs") or [])
        expected_repo_outputs: list[str] = []
        markdown, markdown_errors = safe_task_text(root, phase_path, "phase file")
        if markdown_errors:
            errors.extend(markdown_errors)
        if markdown is not None:
            contract, contract_errors = validate_phase_contract(
                root,
                task_path,
                phase_number,
                phase.get("name"),
                markdown,
                require_previous_outputs=phase.get("status") == "completed",
                decision_registry=decision_registry if not registry_errors else None,
            )
            errors.extend([f"Phase {phase_number} contract: {error}" for error in contract_errors])
            if contract is not None:
                phase_design_refs.extend(
                    (phase_number, item)
                    for item in contract.get("design_refs") or []
                    if isinstance(item, str)
                )
                phase_closes_obligations.update(
                    item for item in contract.get("closes_obligations") or [] if isinstance(item, str)
                )
                errors.extend(
                    validate_contract_against_design(
                        root,
                        task_path,
                        phase_number,
                        contract,
                        design_kind,
                        approved_design_paths,
                        design_ref_ids,
                    )
                )
            expected_commands = expected_ac_commands(phase, markdown)
            expected_outputs = expected_required_outputs(phase, markdown)
            expected_repo_outputs = expected_required_repo_outputs(markdown)
            if phase.get("ac_commands") and list(phase.get("ac_commands") or []) != expected_commands:
                errors.append(
                    f"Phase {phase_number} index ac_commands must match Contract.acceptance_commands."
                )
            if phase.get("required_outputs") and list(phase.get("required_outputs") or []) != expected_outputs:
                errors.append(
                    f"Phase {phase_number} index required_outputs must match Contract.required_outputs."
                )
            if not expected_commands:
                errors.append(f"Missing AC commands for phase {phase_number}.")
            if not expected_outputs:
                errors.append(f"Missing required outputs for phase {phase_number}.")

        errors.extend(validate_phase_attempt_manifest(root, task_path, phase))

        if phase.get("status") == "completed":
            expected_attempt = phase.get("attempts") if isinstance(phase.get("attempts"), int) else None
            handoff_path = handoff_dir / f"phase{phase_number}.md"
            errors.extend(require_file(root, handoff_path, "handoff"))
            handoff_text, handoff_text_errors = safe_task_text(root, handoff_path, "handoff")
            errors.extend(handoff_text_errors)
            if handoff_text is not None:
                handoff_state = classify_handoff_text(handoff_text)
                handoff_reasons = [
                    str(item)
                    for item in handoff_state.get("reasons", [])
                    if isinstance(item, str) and item.strip()
                ]
                if handoff_reasons:
                    errors.append(
                        f"Phase {phase_number} handoff reports blocked/partial status: {handoff_reasons!r}"
                    )
            errors.extend(
                validate_phase_result(
                    root,
                    task_path,
                    phase_number,
                    expected_commands,
                    expected_outputs,
                    expected_repo_outputs,
                    expected_attempt=expected_attempt,
                    strict_current_harness=strict_current_harness,
                )
            )
            result = load_completed_phase_result(task_path, phase_number, expected_attempt)
            if result is not None:
                completed_phase_results.append((phase_number, result))
            errors.extend(
                require_file(
                    root,
                    phase_runtime_artifact_path(task_path, phase_number, "prompt", ".md", expected_attempt),
                    "runtime prompt",
                )
            )
            errors.extend(
                require_file(
                    root,
                    phase_runtime_artifact_path(task_path, phase_number, "contract", ".json", expected_attempt),
                    "phase contract",
                )
            )
            errors.extend(
                require_file(
                    root,
                    phase_runtime_artifact_path(task_path, phase_number, "checklist", ".md", expected_attempt),
                    "phase checklist",
                )
            )
            errors.extend(
                require_file(
                    root,
                    phase_runtime_artifact_path(task_path, phase_number, "evidence", ".json", expected_attempt),
                    "phase evidence",
                )
            )
            reconciliation_path = phase_runtime_artifact_path(
                task_path, phase_number, "reconciliation", ".json", expected_attempt
            )
            errors.extend(
                require_file(root, reconciliation_path, "phase reconciliation")
            )
            errors.extend(validate_phase_reconciliation(root, reconciliation_path))
            errors.extend(
                require_file(
                    root,
                    phase_runtime_artifact_path(task_path, phase_number, "reconciliation", ".md", expected_attempt),
                    "phase reconciliation summary",
                )
            )
            gate_path = phase_runtime_artifact_path(task_path, phase_number, "gate", ".json", expected_attempt)
            errors.extend(require_file(root, gate_path, "phase gate"))
            errors.extend(validate_phase_gate(root, gate_path))
            errors.extend(
                validate_runtime_contract_bundle(
                    root,
                    task_path,
                    phase_number,
                    expected_commands,
                    expected_outputs,
                    expected_repo_outputs,
                    expected_attempt=expected_attempt,
                )
            )
            for attempt in phase_attempts(phase):
                errors.extend(
                    require_file(
                        root,
                        runtime_dir / f"phase{phase_number}-output-attempt{attempt}.jsonl",
                        "runtime output",
                        check_placeholder=False,
                    )
                )
                errors.extend(
                    require_file(
                        root,
                        runtime_dir / f"phase{phase_number}-stderr-attempt{attempt}.txt",
                        "runtime stderr",
                        check_placeholder=False,
                        allow_empty=True,
                    )
                )
            if phase_number == 0:
                errors.extend(require_file(root, runtime_dir / "docs-diff.md", "docs diff", check_placeholder=False))

    if not require_evaluation:
        errors.extend(validate_latest_repo_content_matches_current(root, completed_phase_results))

    if design_info and design_kind == "review":
        errors.extend(validate_traceability_matrix(root, static_dir / "traceability-matrix.json", design_ref_ids, phase_design_refs))
        missing_obligations = sorted(obligation_ids - phase_closes_obligations)
        if missing_obligations:
            errors.append(f"design-contract.json obligations must be closed by at least one phase: {missing_obligations}")
        unknown_closed = sorted(phase_closes_obligations - obligation_ids)
        if unknown_closed:
            errors.append(f"Phase closes_obligations entry is not in design-contract.json obligations: {unknown_closed}")

    if require_evaluation:
        evaluation_command_results = runtime_dir / "evaluation-command-results.json"
        errors.extend(require_file(root, evaluation_command_results, "evaluation command results", False))
        approved_evaluation_policy_packs = None
        if (static_dir / DESIGN_APPROVAL_FILE).exists():
            approved_evaluation_policy_packs, lineage_errors = approved_policy_pack_lineage(root, task_path)
            errors.extend(lineage_errors)
        errors.extend(
            validate_evaluation_command_results(
                root,
                task_path,
                evaluation_command_results,
                approved_policy_packs=approved_evaluation_policy_packs,
            )
        )
        errors.extend(require_file(root, runtime_dir / "evaluation-prompt.md", "evaluation prompt"))
        errors.extend(require_file(root, runtime_dir / "evaluation-output.jsonl", "evaluation output", False))
        evaluation_final = runtime_dir / "evaluation-last-message.json"
        errors.extend(require_file(root, evaluation_final, "evaluation final output", False))
        errors.extend(validate_evaluation_final(root, evaluation_final))
        evaluation_commit = runtime_dir / "evaluation-commit.json"
        errors.extend(require_file(root, evaluation_commit, "evaluation commit", False))
        errors.extend(
            validate_evaluation_commit(
                root,
                task_path,
                evaluation_commit,
                completed_phase_results,
                approved_policy_packs=approved_evaluation_policy_packs,
                strict_current_harness=strict_current_harness,
            )
        )
        errors.extend(
            validate_evaluation_repair_results(
                root,
                task_path,
                runtime_dir,
                base_phase_results=completed_phase_results,
            )
        )

    if not registry_errors:
        for phase in phases:
            phase_number = int(phase["phase"])
            evidence_path = runtime_dir / f"phase{phase_number}-evidence.json"
            contract_path = runtime_dir / f"phase{phase_number}-contract.json"
            if not evidence_path.exists() or not contract_path.exists():
                continue
            try:
                evidence = read_json(evidence_path)
                contract = read_json(contract_path)
            except (json.JSONDecodeError, OSError) as exc:
                errors.append(f"Cannot read runtime dependency validation inputs for phase {phase_number}: {exc}")
                continue
            changed_files = evidence.get("changed_files") if isinstance(evidence, dict) else []
            if isinstance(changed_files, list) and all(isinstance(item, str) for item in changed_files):
                errors.extend(
                    [
                        f"Phase {phase_number}: {error}"
                        for error in validate_dependency_changes(contract, changed_files, root)
                    ]
                )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", help="Task directory name or path.")
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument("--require-evaluation", action="store_true")
    parser.add_argument("--require-design-approval", action="store_true")
    parser.add_argument("--strict-current-harness", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    task_path = resolve_task_path(root, args.task)
    errors = verify(
        root,
        task_path,
        args.require_evaluation,
        args.require_design_approval,
        args.strict_current_harness,
    )
    if errors:
        print("Task verification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Task verification passed: {task_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
