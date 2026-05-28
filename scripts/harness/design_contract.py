"""Design contract and review traceability validation helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reference_resolver import ReferenceUniverse, resolve_reference


DEFAULT_REVIEW_TAXONOMY_IDS = [
    "concurrency_atomicity",
    "lifecycle_trigger_completeness",
    "decision_approval_leakage",
    "artifact_persistence",
    "acceptance_validity",
    "implementation_traceability",
    "rollback_idempotency",
    "dependency_direction",
]
REVIEW_FINDING_STATUSES = {"pass", "fail", "na"}
REVIEW_COVERAGE_TAXONOMY_STATUSES = {"checked", "not_applicable", "blocked", "missing"}
REVIEW_COVERAGE_OBLIGATION_STATUSES = {"checked", "blocked", "missing"}
REVIEW_FINDING_REQUIRED_REF_KINDS = {
    "concurrency_atomicity": {"design", "obligation"},
    "lifecycle_trigger_completeness": {"design", "obligation"},
    "decision_approval_leakage": {"decision"},
    "artifact_persistence": {"design", "path"},
    "acceptance_validity": {"obligation"},
    "implementation_traceability": {"design", "obligation", "path"},
    "rollback_idempotency": {"design", "obligation"},
    "dependency_direction": {"architecture", "design"},
}
REVIEW_FINDING_ALLOWED_REF_METADATA = {
    "concurrency_atomicity": {"design": {"source": {"transaction_boundaries"}}},
    "lifecycle_trigger_completeness": {"design": {"source": {"retry_triggers", "state_transitions"}}},
    "rollback_idempotency": {"design": {"source": {"retry_triggers", "transaction_boundaries"}}},
}


def rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def load_json_object(root: Path, path: Path, label: str) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, [f"Missing {label}: {rel(root, path)}"]
    except json.JSONDecodeError as exc:
        return None, [f"Invalid {label} JSON: {rel(root, path)}: {exc}"]
    if not isinstance(data, dict):
        return None, [f"{label} must be a JSON object: {rel(root, path)}"]
    return data, []


def _string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str) and item.strip()] if isinstance(value, list) else []


def _require_string_list(value: Any, label: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        return [f"`{label}` must be a list."]
    values = _string_list(value)
    if not allow_empty and not values:
        return [f"`{label}` must be a non-empty list."]
    if len(values) != len(value):
        return [f"`{label}` entries must be non-empty strings."]
    return []


def design_obligation_ids(contract: dict[str, Any]) -> set[str]:
    return {
        item["id"].strip()
        for item in contract.get("obligations") or []
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
    }


def design_item_ids(contract: dict[str, Any]) -> set[str]:
    ids = set(design_obligation_ids(contract))
    for field in ["state_transitions", "transaction_boundaries", "retry_triggers", "external_environment_mappings"]:
        for item in contract.get(field) or []:
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip():
                ids.add(item["id"].strip())
    artifact = contract.get("artifact_persistence")
    if isinstance(artifact, dict):
        for item in artifact.get("required_paths") or []:
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip():
                ids.add(item["id"].strip())
    return ids


def validate_review_taxonomy(root: Path, path: Path) -> tuple[set[str], list[str]]:
    taxonomy, errors = load_json_object(root, path, "review taxonomy")
    if taxonomy is None:
        return set(), errors
    checks = taxonomy.get("checks")
    if not isinstance(checks, list) or not checks:
        return set(), ["`review-taxonomy.json.checks` must be a non-empty list."]
    ids: set[str] = set()
    for index, item in enumerate(checks):
        if not isinstance(item, dict):
            errors.append(f"`review-taxonomy.json.checks[{index}]` must be an object.")
            continue
        check_id = item.get("id")
        if not isinstance(check_id, str) or not check_id.strip():
            errors.append(f"`review-taxonomy.json.checks[{index}].id` must be a non-empty string.")
            continue
        ids.add(check_id)
        for field in ["title", "review_prompt"]:
            if not isinstance(item.get(field), str) or not item.get(field, "").strip():
                errors.append(f"`review-taxonomy.json.checks[{index}].{field}` must be a non-empty string.")
    missing = sorted(set(DEFAULT_REVIEW_TAXONOMY_IDS) - ids)
    if missing:
        errors.append(f"review-taxonomy.json is missing required review checks: {missing!r}")
    return ids, errors


def _resolve_refs(refs: list[str], universe: ReferenceUniverse | set[str]) -> tuple[list[Any], list[str]]:
    resolved = []
    errors = []
    for index, ref in enumerate(refs):
        item, error = resolve_reference(ref, universe)
        if error or item is None:
            if "unknown reference" in str(error):
                errors.append(f"unknown evidence ref: {ref}")
            else:
                errors.append(str(error))
        else:
            resolved.append(item)
    return resolved, errors


def _review_finding_policy_error(taxonomy_id: str, refs: list[Any]) -> str | None:
    required = REVIEW_FINDING_REQUIRED_REF_KINDS.get(taxonomy_id)
    if not required:
        return None
    matching = [ref for ref in refs if ref.kind in required]
    if not matching:
        return f"`review-findings.json` pass finding for {taxonomy_id!r} must cite at least one static evidence ref with kind {sorted(required)!r}."
    metadata_policy = REVIEW_FINDING_ALLOWED_REF_METADATA.get(taxonomy_id)
    if metadata_policy:
        for ref in matching:
            policy = metadata_policy.get(ref.kind)
            if not policy:
                continue
            if all(ref.metadata.get(field) in allowed for field, allowed in policy.items()):
                return None
        return f"`review-findings.json` pass finding for {taxonomy_id!r} cites the right ref kind but not an eligible design source/class for that taxonomy."
    return None


def validate_review_findings(
    root: Path,
    path: Path,
    required_ids: set[str],
    evidence_ref_universe: ReferenceUniverse | set[str] | None = None,
) -> list[str]:
    findings_doc, errors = load_json_object(root, path, "review findings")
    if findings_doc is None:
        return errors
    findings = findings_doc.get("findings")
    if not isinstance(findings, list) or not findings:
        return ["`review-findings.json.findings` must be a non-empty list."]
    seen: set[str] = set()
    for index, item in enumerate(findings):
        if not isinstance(item, dict):
            errors.append(f"`review-findings.json.findings[{index}]` must be an object.")
            continue
        taxonomy_id = item.get("taxonomy_id")
        if not isinstance(taxonomy_id, str) or not taxonomy_id.strip():
            errors.append(f"`review-findings.json.findings[{index}].taxonomy_id` must be a non-empty string.")
            continue
        seen.add(taxonomy_id)
        status = item.get("status")
        if status not in REVIEW_FINDING_STATUSES:
            errors.append(f"`review-findings.json.findings[{index}].status` must be one of {sorted(REVIEW_FINDING_STATUSES)!r}.")
        elif status == "fail":
            errors.append(f"Review finding must be resolved before Plan: {taxonomy_id}")
        if not isinstance(item.get("evidence"), str) or not item.get("evidence", "").strip():
            errors.append(f"`review-findings.json.findings[{index}].evidence` must be a non-empty string.")
        evidence_refs = item.get("evidence_refs")
        if status == "pass":
            if not isinstance(evidence_refs, list) or not evidence_refs:
                errors.append(f"`review-findings.json.findings[{index}].evidence_refs` must be a non-empty list for pass findings.")
            elif evidence_ref_universe is not None:
                refs, ref_errors = _resolve_refs(evidence_refs, evidence_ref_universe)
                errors.extend(ref_errors)
                policy_error = _review_finding_policy_error(taxonomy_id, refs)
                if policy_error:
                    errors.append(policy_error)
        elif status == "na" and (not isinstance(item.get("rationale"), str) or not item["rationale"].strip()):
            errors.append(f"`review-findings.json.findings[{index}].rationale` is required for status na.")
    missing = sorted(required_ids - seen)
    if missing:
        errors.append(f"review-findings.json must cover every review taxonomy check: {missing!r}")
    return errors


def validate_review_coverage(
    root: Path,
    path: Path,
    required_taxonomy_ids: set[str],
    obligation_ids: set[str],
    evidence_ref_universe: ReferenceUniverse | set[str] | None = None,
) -> list[str]:
    coverage_doc, errors = load_json_object(root, path, "review coverage")
    if coverage_doc is None:
        return errors
    if not isinstance(coverage_doc.get("schema_version"), str) or not coverage_doc.get("schema_version", "").strip():
        errors.append("`review-coverage.json.schema_version` must be a non-empty string.")
    taxonomy_coverage = coverage_doc.get("taxonomy_coverage")
    if not isinstance(taxonomy_coverage, list) or not taxonomy_coverage:
        errors.append("`review-coverage.json.taxonomy_coverage` must be a non-empty list.")
        taxonomy_coverage = []
    seen_taxonomy: set[str] = set()
    for index, item in enumerate(taxonomy_coverage):
        if not isinstance(item, dict):
            errors.append(f"`review-coverage.json.taxonomy_coverage[{index}]` must be an object.")
            continue
        taxonomy_id = item.get("taxonomy_id")
        if isinstance(taxonomy_id, str):
            seen_taxonomy.add(taxonomy_id)
        status = item.get("status")
        if status in {"blocked", "missing"}:
            errors.append(f"Review coverage must be resolved before Plan: taxonomy {taxonomy_id} is {status}.")
        if status == "checked" and not item.get("evidence_refs"):
            errors.append(f"`review-coverage.json.taxonomy_coverage[{index}].evidence_refs` must be a non-empty list.")
    missing_taxonomy = sorted(required_taxonomy_ids - seen_taxonomy)
    if missing_taxonomy:
        errors.append(f"review-coverage.json must cover every review taxonomy check: {missing_taxonomy!r}")
    obligation_coverage = coverage_doc.get("obligation_coverage")
    if not isinstance(obligation_coverage, list):
        errors.append("`review-coverage.json.obligation_coverage` must be a list.")
        obligation_coverage = []
    seen_obligations: set[str] = set()
    for index, item in enumerate(obligation_coverage):
        if not isinstance(item, dict):
            errors.append(f"`review-coverage.json.obligation_coverage[{index}]` must be an object.")
            continue
        obligation_id = item.get("obligation_id")
        if isinstance(obligation_id, str):
            seen_obligations.add(obligation_id)
        status = item.get("status")
        if status in {"blocked", "missing"}:
            errors.append(f"Review coverage must be resolved before Plan: obligation {obligation_id} is {status}.")
        refs = item.get("evidence_refs")
        if status == "checked":
            if not isinstance(refs, list) or not refs:
                errors.append(f"`review-coverage.json.obligation_coverage[{index}].evidence_refs` must be a non-empty list.")
            elif evidence_ref_universe is not None and f"obligation:{obligation_id}" not in refs:
                errors.append(f"`review-coverage.json.obligation_coverage[{index}].evidence_refs` must cite at least one obligation:{obligation_id} reference.")
    missing_obligations = sorted(obligation_ids - seen_obligations)
    if missing_obligations:
        errors.append(f"review-coverage.json must cover every design obligation: {missing_obligations!r}")
    for field in ["assumptions", "residual_risks"]:
        errors.extend(_require_string_list(coverage_doc.get(field, []), f"review-coverage.json.{field}", allow_empty=True))
    return errors


def validate_design_contract(root: Path, path: Path, design_text: str, approved_paths: list[str]) -> tuple[set[str], set[str], list[str]]:
    contract, errors = load_json_object(root, path, "design contract")
    if contract is None:
        return set(), set(), errors
    lowered_design = design_text.lower()
    if ("remove successful" in lowered_design or "userdefaults" in lowered_design) and not contract.get("transaction_boundaries"):
        errors.append("design-contract.json transaction_boundaries is empty while design review claims state mutation.")
    if ("retry" in lowered_design or "foreground" in lowered_design) and not contract.get("retry_triggers"):
        errors.append("design-contract.json retry_triggers is empty while design review claims lifecycle retry behavior.")
    if "approval" in lowered_design and not _string_list(contract.get("decision_refs")) and not _string_list(contract.get("open_decision_refs")):
        errors.append("design-contract.json decision_refs/open_decision_refs are required when design review uses approval language.")

    obligations = contract.get("obligations")
    if isinstance(obligations, list):
        for index, obligation in enumerate(obligations):
            if not isinstance(obligation, dict):
                errors.append(f"design-contract.json obligations[{index}] must be an object.")
                continue
            obligation_id = obligation.get("id") if isinstance(obligation.get("id"), str) else f"[{index}]"
            refs = _string_list(obligation.get("closure_command_refs"))
            if obligation.get("required_command_roles") and not refs:
                errors.append(f"design-contract.json obligation {obligation_id} closure_command_refs must be non-empty.")
            contains = _string_list(obligation.get("closure_output_contains"))
            if contains and not refs:
                errors.append(f"design-contract.json obligation {obligation_id} closure_output_contains requires closure_command_refs.")
            assertions = obligation.get("closure_output_assertions")
            if isinstance(assertions, list):
                for assertion_index, assertion in enumerate(assertions):
                    if not isinstance(assertion, dict):
                        errors.append(
                            f"design-contract.json obligation {obligation_id} closure_output_assertions[{assertion_index}] must be an object."
                        )
                        continue
                    if assertion.get("type") not in {"contains", "exact_line"}:
                        errors.append(
                            f"design-contract.json obligation {obligation_id} closure_output_assertions[{assertion_index}].type must be contains or exact_line."
                        )
                    value = assertion.get("value")
                    if not isinstance(value, str) or not value.strip():
                        errors.append(
                            f"design-contract.json obligation {obligation_id} closure_output_assertions[{assertion_index}].value must be non-empty."
                        )
                    command_ref = assertion.get("command_ref")
                    if command_ref is not None and command_ref not in refs:
                        errors.append(
                            f"design-contract.json obligation {obligation_id} closure_output_assertions[{assertion_index}].command_ref must be listed in closure_command_refs."
                        )
                if assertions and not refs:
                    errors.append(f"design-contract.json obligation {obligation_id} closure_output_assertions requires closure_command_refs.")
            sensitive_values = [*contains]
            if isinstance(assertions, list):
                sensitive_values.extend(
                    str(item.get("value"))
                    for item in assertions
                    if isinstance(item, dict) and item.get("value") is not None
                )
            if any(any(marker in value.lower() for marker in ["token", "secret", "password", "key"]) for value in sensitive_values):
                errors.append(f"design-contract.json obligation {obligation_id} contains sensitive-looking text in closure output matcher.")
            if obligation.get("class") in {"secret_sdk_boundary", "auth_boundary", "credential_boundary"}:
                if contains:
                    errors.append(f"design-contract.json obligation {obligation_id} closure_output_contains is not allowed for security-sensitive obligations.")
                for assertion in assertions or []:
                    if isinstance(assertion, dict) and assertion.get("type") == "contains":
                        errors.append(f"design-contract.json obligation {obligation_id} closure_output_assertions must not be contains for security-sensitive obligations.")
    return design_item_ids(contract), design_obligation_ids(contract), errors


def validate_traceability_matrix(
    root: Path,
    path: Path,
    design_ids: set[str],
    phase_design_refs: list[tuple[int, str]],
) -> list[str]:
    matrix, errors = load_json_object(root, path, "traceability matrix")
    if matrix is None:
        return errors
    entries = matrix.get("entries")
    if not isinstance(entries, list):
        return ["`traceability-matrix.json.entries` must be a list."]
    covered: set[tuple[int, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        phase = entry.get("phase")
        refs = entry.get("design_refs") or entry.get("refs") or []
        if isinstance(refs, str):
            refs = [refs]
        for ref in refs:
            if isinstance(phase, int) and isinstance(ref, str):
                covered.add((phase, ref))
    for phase, ref in phase_design_refs:
        if ref not in design_ids:
            errors.append(f"traceability-matrix.json is missing design id: {ref}")
        if entries and (phase, ref) not in covered:
            errors.append(f"traceability-matrix.json is missing phase {phase} design ref: {ref}")
        if not entries:
            errors.append(f"traceability-matrix.json is missing phase {phase} design ref: {ref}")
    return errors
