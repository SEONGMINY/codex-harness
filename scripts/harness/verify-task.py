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


HARNESS_VERSION = "0.1.5"
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


def require_file(
    root: Path,
    path: Path,
    label: str,
    check_placeholder: bool = True,
    allow_empty: bool = False,
) -> list[str]:
    if not path.exists():
        return [f"Missing {label}: {rel(root, path)}"]
    if not path.is_file():
        return [f"Not a file: {rel(root, path)}"]
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    errors = []
    if not text and not allow_empty:
        errors.append(f"Empty {label}: {rel(root, path)}")
    if check_placeholder and has_placeholder(text):
        errors.append(f"Placeholder remains in {label}: {rel(root, path)}")
    return errors


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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def validate_ac_results_metadata(
    root: Path,
    task_path: Path,
    phase_number: int,
    attempt: int,
    artifacts: dict[str, object],
    expected_policy_pack: dict[str, str] | None = None,
    *,
    approved_policy_packs: list[dict[str, str]] | None = None,
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
    if data.get("phase") != phase_number:
        errors.append("AC results metadata phase does not match result phase.")
    if data.get("attempt") not in (None, attempt):
        errors.append("AC results metadata attempt does not match result attempt.")
    policy = data.get("policy_pack")
    if expected_policy_pack is not None and policy != expected_policy_pack:
        errors.append("AC results metadata policy_pack does not match phase result policy_pack.")
    errors.extend(
        validate_policy_pack_metadata(
            policy,
            "AC results",
            approved_fingerprints=approved_policy_packs,
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
        errors.extend(validate_phase_attempt_commit(root, task_path, phase_number, attempt, result_path, result, artifacts))
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


def validate_evaluation_repair_results(root: Path, task_path: Path, runtime_dir: Path) -> list[str]:
    phase_results: list[tuple[int, dict[str, Any]]] = []
    for path in sorted(runtime_dir.glob("evaluation-repair*-result.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [f"Invalid evaluation repair result JSON: {rel(root, path)}: {exc}"]
        if isinstance(data, dict):
            phase_results.append((int(data.get("iteration") or 0), data))
    return validate_latest_repo_content_matches_current(root, phase_results)


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
    errors.extend(validate_design_review(root, task_path, task_docs))

    static_dir = task_path / "context-pack" / "static"
    for filename in MANDATORY_STATIC_FILES:
        errors.extend(require_file(root, static_dir / filename, "static context"))
    if require_design_approval:
        errors.extend(validate_design_approval(root, task_path, strict_current_harness=strict_current_harness))
    design_info = design_doc_info(root, task_path)
    design_kind = design_info[2] if design_info else None
    approved_design_paths: list[str] = []
    design_ref_ids: set[str] = set()
    if design_info and design_kind == "review":
        design_text = design_info[0].read_text(encoding="utf-8", errors="replace")
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
        if phase_path.exists():
            markdown = phase_path.read_text(encoding="utf-8", errors="replace")
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

        if phase.get("status") == "completed":
            expected_attempt = phase.get("attempts") if isinstance(phase.get("attempts"), int) else None
            handoff_path = handoff_dir / f"phase{phase_number}.md"
            errors.extend(require_file(root, handoff_path, "handoff"))
            if handoff_path.exists():
                handoff_reasons = handoff_block_reasons(
                    handoff_path.read_text(encoding="utf-8", errors="replace")
                )
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
        errors.extend(validate_evaluation_repair_results(root, task_path, runtime_dir))

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
