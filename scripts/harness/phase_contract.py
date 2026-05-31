"""Phase contract parsing and validation helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from command_policy import parse_command
from decision_registry import validate_contract_refs
from phase_semantics import (
    NON_IMPLEMENTATION_LAYERS as _NON_IMPLEMENTATION_LAYERS,
    analyze_phase,
    contract_needs_verification_evidence,
)
from scope_policy import contract_allowed_paths, path_allowed, scope_violations


CONTRACT_BLOCK_RE = re.compile(
    r"## Contract\s*```json\s*(?P<json>.*?)```",
    flags=re.DOTALL,
)
FORBIDDEN_REFERENCE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"이전\s*대화",
        r"앞서\s*논의",
        r"논의한\s*바",
        r"위에서\s*말한",
        r"as\s+discussed",
        r"previous\s+conversation",
        r"earlier\s+discussion",
    ]
]
GENERIC_FORBIDDEN_RULE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"조심",
        r"주의",
        r"careful",
        r"be\s+careful",
    ]
]
HANDOFF_BLOCK_RULES = [
    {
        "id": "explicit_status_field",
        "pattern": re.compile(r"(?im)^\s*(?:status|state)\s*:\s*(blocked|partial|skipped|failed|workaround)\b"),
    },
    {
        "id": "explicit_status_heading",
        "pattern": re.compile(r"(?im)^\s*##\s*(?:status|state)\s*\n+\s*(blocked|partial|skipped|failed|workaround)\b"),
    },
    {
        "id": "english_incomplete_phrase",
        "pattern": re.compile(
            r"(?i)\b("
            r"blocked by|could not implement|unable to implement|not implemented|"
            r"partial implementation|skipped|workaround|rejected paths?"
            r")\b"
        ),
    },
    {
        "id": "korean_incomplete_phrase",
        "pattern": re.compile(r"(막힘|막혔|차단|우회|구현하지 못|부분 구현|일부 구현)"),
    },
]
HANDOFF_BLOCK_PATTERNS = [item["pattern"] for item in HANDOFF_BLOCK_RULES]
CHANGE_TRACE_SECTION_RE = re.compile(
    r"(?ms)^##\s+Change Trace\s*$\n(?P<body>.*?)(?=^##\s+|\Z)"
)
CHANGE_TRACE_LINE_RE = re.compile(
    r"^\s*[-*]\s+`(?P<path>[^`]+)`\s*:\s*(?P<ids>.+?)\s*$"
)
INSTRUCTION_ID_RE = re.compile(r"`([^`]+)`|([A-Za-z][A-Za-z0-9_-]*-\d+)")
IMPLEMENTATION_QUALITY_DOC = "docs/harness/implementation-quality.md"
DESIGN_REVIEW_DOC = "implementation-design-review.md"
DESIGN_REVIEW_WAIVER_DOC = "design-review-waiver.md"
COMMAND_EXPECTATION_ROLES = {"reproduction", "acceptance", "fixture", "build", "meta"}
# Re-export for scripts or tests that imported this constant from phase_contract.
NON_IMPLEMENTATION_LAYERS = _NON_IMPLEMENTATION_LAYERS


def parse_phase_contract(markdown: str) -> tuple[dict[str, Any] | None, list[str]]:
    match = CONTRACT_BLOCK_RE.search(markdown)
    if not match:
        return None, ["Missing `## Contract` JSON block."]
    try:
        contract = json.loads(match.group("json"))
    except json.JSONDecodeError as exc:
        return None, [f"Invalid phase contract JSON: {exc}"]
    if not isinstance(contract, dict):
        return None, ["Phase contract must be a JSON object."]
    return contract, []


def forbidden_reference_errors(markdown: str) -> list[str]:
    errors = []
    for pattern in FORBIDDEN_REFERENCE_PATTERNS:
        if pattern.search(markdown):
            errors.append(
                "Phase file must not reference prior chat context. "
                f"Matched forbidden phrase pattern: {pattern.pattern}"
            )
    return errors


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _validate_non_empty_string_list(value: Any, label: str) -> list[str]:
    errors = []
    if not isinstance(value, list) or not value:
        return [f"`{label}` must be a non-empty list."]
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"`{label}[{index}]` must be a non-empty string.")
        elif item.strip() == "TODO" or "TODO:" in item:
            errors.append(f"`{label}[{index}]` must not contain TODO.")
    return errors


def _validate_fallback_behavior(value: Any) -> list[str]:
    errors = []
    if not isinstance(value, dict):
        return ["`fallback_behavior` must be an object."]
    for field in ["if_blocked", "if_tests_fail"]:
        if not isinstance(value.get(field), str) or not value.get(field, "").strip():
            errors.append(f"`fallback_behavior.{field}` must be a non-empty string.")
        elif value[field].strip() == "TODO" or "TODO:" in value[field]:
            errors.append(f"`fallback_behavior.{field}` must not contain TODO.")
    return errors


def _validate_validation_budget(value: Any) -> list[str]:
    errors = []
    if not isinstance(value, dict):
        return ["`validation_budget` must be an object."]
    max_attempts = value.get("max_attempts")
    command_timeout = value.get("command_timeout_seconds")
    if not isinstance(max_attempts, int) or max_attempts < 1:
        errors.append("`validation_budget.max_attempts` must be a positive integer.")
    if not isinstance(command_timeout, int) or command_timeout < 1:
        errors.append("`validation_budget.command_timeout_seconds` must be a positive integer.")
    return errors


def _validate_command_expectations(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return ["`command_expectations` must be a list when present."]
    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_commands: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"`command_expectations[{index}]` must be an object.")
            continue
        command = item.get("command")
        if not isinstance(command, str) or not command.strip():
            errors.append(f"`command_expectations[{index}].command` must be a non-empty string.")
        elif command in seen_commands:
            errors.append(f"Duplicate command_expectations command: {command}")
        elif isinstance(command, str):
            seen_commands.add(command)
        expectation_id = item.get("id")
        if not isinstance(expectation_id, str) or not expectation_id.strip():
            errors.append(f"`command_expectations[{index}].id` must be a non-empty string.")
        elif expectation_id in seen_ids:
            errors.append(f"Duplicate command_expectations id: {expectation_id}")
        else:
            seen_ids.add(expectation_id)
        role = item.get("role")
        if role not in COMMAND_EXPECTATION_ROLES:
            errors.append(
                f"`command_expectations[{index}].role` must be one of "
                + ", ".join(sorted(COMMAND_EXPECTATION_ROLES))
                + "."
            )
        target = item.get("target")
        if target is not None and (not isinstance(target, str) or not target.strip()):
            errors.append(f"`command_expectations[{index}].target` must be a non-empty string when present.")
        repo_scan = item.get("repo_scan")
        if repo_scan is not None and not isinstance(repo_scan, bool):
            errors.append(f"`command_expectations[{index}].repo_scan` must be boolean when present.")
    return errors


def _validate_command_expectation_sources(contract: dict[str, Any]) -> list[str]:
    expectations = contract.get("command_expectations")
    if not isinstance(expectations, list):
        return []
    acceptance = set(contract_acceptance_commands(contract))
    verification = contract.get("verification_evidence") if isinstance(contract.get("verification_evidence"), dict) else {}
    reproduction = set(string_list(verification.get("reproduction") if isinstance(verification, dict) else []))
    alternative = set(string_list(verification.get("alternative_evidence") if isinstance(verification, dict) else []))
    errors: list[str] = []
    for index, item in enumerate(expectations):
        if not isinstance(item, dict) or not isinstance(item.get("command"), str):
            continue
        command = item["command"]
        role = item.get("role")
        if role in {"acceptance", "fixture", "build", "meta"} and command not in acceptance:
            errors.append(f"`command_expectations[{index}].command` must appear in acceptance_commands for role {role}.")
        if role == "reproduction" and command not in reproduction and command not in alternative:
            errors.append(f"`command_expectations[{index}].command` must appear in verification_evidence.reproduction or alternative_evidence.")
    return errors


def _validate_expected_evidence_items(instructions: Any) -> list[str]:
    errors: list[str] = []
    allowed_types = {"required_output", "required_repo_output", "command", "path", "changed_file"}
    for instruction_index, instruction in enumerate(instructions or []):
        if not isinstance(instruction, dict):
            continue
        for evidence_index, evidence in enumerate(instruction.get("expected_evidence") or []):
            if not isinstance(evidence, dict):
                continue
            allowed_keys = {"type", "ref"}
            extra = sorted(set(evidence) - allowed_keys)
            if extra:
                errors.append(
                    f"`instructions[{instruction_index}].expected_evidence[{evidence_index}]` has unsupported keys: {extra!r}"
                )
            if evidence.get("type") not in allowed_types:
                errors.append(f"`instructions[{instruction_index}].expected_evidence[{evidence_index}].type` is invalid.")
            if not isinstance(evidence.get("ref"), str) or not evidence.get("ref", "").strip():
                errors.append(f"`instructions[{instruction_index}].expected_evidence[{evidence_index}].ref` must be a non-empty string.")
    return errors


def _validate_command_policy(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for index, command in enumerate(contract_acceptance_commands(contract)):
        _argv, command_errors = parse_command(command)
        for error in command_errors:
            errors.append(f"`acceptance_commands[{index}]` violates command policy: {error}")
    return errors


def _contract_expected_evidence(contract: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for instruction in contract.get("instructions") or []:
        if isinstance(instruction, dict):
            values.extend(string_list(instruction.get("expected_evidence")))
    return values


def _validate_verification_evidence(value: Any, contract: dict[str, Any]) -> list[str]:
    if not isinstance(value, dict):
        return [
            "`verification_evidence` must be an object for bugfix or validation phases."
        ]
    reproduction = string_list(value.get("reproduction"))
    fallback_reason = value.get("fallback_reason")
    alternative = string_list(value.get("alternative_evidence"))
    evidence_refs = set(contract_acceptance_commands(contract))
    selected_evidence = reproduction or alternative
    if reproduction:
        return []
    if (
        isinstance(fallback_reason, str)
        and fallback_reason.strip()
        and alternative
    ):
        evidence_refs.update(_contract_expected_evidence(contract))
        missing_refs = [item for item in selected_evidence if item not in evidence_refs]
        if missing_refs:
            return [
                "`verification_evidence.alternative_evidence` entries must also appear in "
                f"`acceptance_commands` or `instructions[*].expected_evidence`: {missing_refs!r}"
            ]
        return []
    return [
        "`verification_evidence` must include `reproduction`, or both "
        "`fallback_reason` and `alternative_evidence`, for bugfix or validation phases."
    ]


def _validate_decision_policy_shape(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ["decision_refs", "architecture_refs"]:
        value = contract.get(field)
        if not isinstance(value, list) or not value:
            errors.append(f"`{field}` must be a non-empty list.")
        elif not all(isinstance(item, str) and item.strip() for item in value):
            errors.append(f"`{field}` entries must be non-empty strings.")
    policy = contract.get("dependency_policy")
    if not isinstance(policy, dict):
        errors.append("`dependency_policy` must be an object.")
    else:
        if policy.get("new_dependencies") not in {"forbidden", "approved_only", "allowed"}:
            errors.append("`dependency_policy.new_dependencies` must be forbidden, approved_only, or allowed.")
        approved = policy.get("approved_new_dependencies", [])
        if not isinstance(approved, list) or not all(isinstance(item, str) for item in approved):
            errors.append("`dependency_policy.approved_new_dependencies` must be a string list.")
        approved_manifests = policy.get("approved_dependency_manifest_changes", [])
        if not isinstance(approved_manifests, list) or not all(isinstance(item, str) for item in approved_manifests):
            errors.append("`dependency_policy.approved_dependency_manifest_changes` must be a string list.")
    return errors


def contract_acceptance_commands(contract: dict[str, Any] | None) -> list[str]:
    if not contract:
        return []
    return string_list(contract.get("acceptance_commands"))


def contract_required_outputs(contract: dict[str, Any] | None) -> list[str]:
    if not contract:
        return []
    return string_list(contract.get("required_outputs"))


def contract_required_repo_outputs(contract: dict[str, Any] | None) -> list[str]:
    if not contract:
        return []
    return string_list(contract.get("required_repo_outputs"))


def task_design_doc_paths(task_path: Path) -> set[str]:
    task_dir = task_path.name
    return {
        f"tasks/{task_dir}/docs/{DESIGN_REVIEW_DOC}",
        f"tasks/{task_dir}/docs/{DESIGN_REVIEW_WAIVER_DOC}",
    }


def repo_or_task_path(root: Path, task_path: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise ValueError(f"Path must be relative: {raw_path}")
    if ".." in candidate.parts:
        raise ValueError(f"Path must not contain parent traversal: {raw_path}")
    root_candidate = (root / candidate).resolve()
    if root_candidate.exists():
        return root_candidate
    return (task_path / candidate).resolve()


def repo_relative_path(root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise ValueError(f"Path must be repository-relative: {raw_path}")
    if ".." in candidate.parts:
        raise ValueError(f"Path must not contain parent traversal: {raw_path}")
    return (root / candidate).resolve()


def task_relative_path(task_path: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise ValueError(f"Path must be task-relative: {raw_path}")
    if ".." in candidate.parts:
        raise ValueError(f"Path must not contain parent traversal: {raw_path}")
    return (task_path / candidate).resolve()


def _validate_path_list(
    root: Path,
    task_path: Path,
    values: Any,
    label: str,
    check_exists: bool,
    task_relative: bool = False,
) -> list[str]:
    errors = []
    if not isinstance(values, list) or not values:
        return [f"`{label}` must be a non-empty list."]
    for index, raw_path in enumerate(values):
        if not isinstance(raw_path, str) or not raw_path.strip():
            errors.append(f"`{label}[{index}]` must be a non-empty string.")
            continue
        try:
            path = task_relative_path(task_path, raw_path) if task_relative else repo_or_task_path(root, task_path, raw_path)
        except ValueError as exc:
            errors.append(f"`{label}[{index}]`: {exc}")
            continue
        if check_exists and not path.exists():
            errors.append(f"`{label}[{index}]` does not exist: {raw_path}")
    return errors


def _validate_repo_relative_path_list(root: Path, values: Any, label: str) -> list[str]:
    errors = []
    if not isinstance(values, list) or not values:
        return [f"`{label}` must be a non-empty list."]
    for index, raw_path in enumerate(values):
        if not isinstance(raw_path, str) or not raw_path.strip():
            errors.append(f"`{label}[{index}]` must be a non-empty string.")
            continue
        try:
            repo_relative_path(root, raw_path)
        except ValueError as exc:
            errors.append(f"`{label}[{index}]`: {exc}")
    return errors


def validate_phase_contract(
    root: Path,
    task_path: Path,
    phase_number: int,
    phase_name: str | None,
    markdown: str,
    require_previous_outputs: bool,
    decision_registry: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    contract, errors = parse_phase_contract(markdown)
    errors.extend(forbidden_reference_errors(markdown))
    if contract is None:
        return None, errors

    if contract.get("phase") != phase_number:
        errors.append(f"`phase` must be {phase_number}.")
    if phase_name and contract.get("name") != phase_name:
        errors.append(f"`name` must be {phase_name!r}.")

    errors.extend(_validate_non_empty_string_list(contract.get("success_criteria"), "success_criteria"))
    errors.extend(_validate_non_empty_string_list(contract.get("stop_rules"), "stop_rules"))
    errors.extend(_validate_fallback_behavior(contract.get("fallback_behavior")))
    errors.extend(_validate_validation_budget(contract.get("validation_budget")))
    errors.extend(_validate_command_expectations(contract.get("command_expectations")))
    errors.extend(_validate_command_expectation_sources(contract))
    errors.extend(_validate_command_policy(contract))
    errors.extend(_validate_decision_policy_shape(contract))
    if contract.get("phase_kind") == "validation" and analyze_phase(contract, phase_name).writes_product_code:
        errors.append("`phase_kind` validation cannot include product implementation paths.")
    if contract_needs_verification_evidence(contract, phase_name):
        errors.extend(_validate_verification_evidence(contract.get("verification_evidence"), contract))
    if decision_registry is not None:
        errors.extend(validate_contract_refs(contract, decision_registry))
    missing_evidence = contract.get("missing_evidence_behavior")
    if not isinstance(missing_evidence, str) or not missing_evidence.strip():
        errors.append("`missing_evidence_behavior` must be a non-empty string.")
    elif missing_evidence.strip() == "TODO" or "TODO:" in missing_evidence:
        errors.append("`missing_evidence_behavior` must not contain TODO.")

    read_first = contract.get("read_first")
    if not isinstance(read_first, dict):
        errors.append("`read_first` must be an object.")
    else:
        errors.extend(_validate_path_list(root, task_path, read_first.get("docs"), "read_first.docs", True))
        previous_outputs = read_first.get("previous_outputs")
        if phase_number == 0:
            if previous_outputs not in ([], None):
                errors.append("`read_first.previous_outputs` must be empty for phase 0.")
        elif not isinstance(previous_outputs, list) or not previous_outputs:
            errors.append("`read_first.previous_outputs` must list previous phase outputs.")
        else:
            errors.extend(
                _validate_path_list(
                    root,
                    task_path,
                    previous_outputs,
                    "read_first.previous_outputs",
                    require_previous_outputs,
                )
            )

    scope = contract.get("scope")
    if not isinstance(scope, dict):
        errors.append("`scope` must be an object.")
    else:
        if not isinstance(scope.get("layer"), str) or not scope.get("layer", "").strip():
            errors.append("`scope.layer` must be a non-empty string.")
        allowed_paths = scope.get("allowed_paths")
        errors.extend(_validate_repo_relative_path_list(root, allowed_paths, "scope.allowed_paths"))

    interfaces = contract.get("interfaces")
    if not isinstance(interfaces, list):
        errors.append("`interfaces` must be a list.")
    else:
        if analyze_phase(contract, phase_name).writes_product_code and not interfaces:
            errors.append("`interfaces` must describe target signatures for non-documentation phases.")
        structured_interface_mode = any(
            isinstance(item, dict) and any(key in item for key in ["visibility", "kind", "exposes"])
            for item in interfaces
        )
        for index, item in enumerate(interfaces):
            if not isinstance(item, dict):
                errors.append(f"`interfaces[{index}]` must be an object.")
                continue
            for field in ["path", "symbol", "signature"]:
                if not isinstance(item.get(field), str) or not item.get(field, "").strip():
                    errors.append(f"`interfaces[{index}].{field}` must be a non-empty string.")
            if structured_interface_mode:
                visibility = item.get("visibility")
                if visibility not in {"public", "internal", "private"}:
                    errors.append(f"`interfaces[{index}].visibility` must be public, internal, or private.")
                kind = item.get("kind")
                if kind not in {"function", "method", "property", "type", "protocol", "class", "struct", "enum", "doc", "module"}:
                    errors.append(f"`interfaces[{index}].kind` must be valid structured interface metadata.")
                exposes = item.get("exposes")
                if exposes is not None and (not isinstance(exposes, list) or not all(isinstance(entry, str) and entry.strip() for entry in exposes)):
                    errors.append(f"`interfaces[{index}].exposes` must be a list of non-empty strings when present.")
                if visibility == "public" and "exposes" not in item:
                    errors.append(f"`interfaces[{index}].exposes` is required for public interfaces.")
            business_rules = item.get("business_rules")
            if not isinstance(business_rules, list) or not string_list(business_rules):
                errors.append(f"`interfaces[{index}].business_rules` must be a non-empty list.")

    instructions = contract.get("instructions")
    seen_ids: set[str] = set()
    if not isinstance(instructions, list) or not instructions:
        errors.append("`instructions` must be a non-empty list.")
    else:
        errors.extend(_validate_expected_evidence_items(instructions))
        for index, item in enumerate(instructions):
            if not isinstance(item, dict):
                errors.append(f"`instructions[{index}]` must be an object.")
                continue
            instruction_id = item.get("id")
            if not isinstance(instruction_id, str) or not instruction_id.strip():
                errors.append(f"`instructions[{index}].id` must be a non-empty string.")
            elif instruction_id in seen_ids:
                errors.append(f"Duplicate instruction id: {instruction_id}")
            else:
                seen_ids.add(instruction_id)
            if not isinstance(item.get("task"), str) or not item.get("task", "").strip():
                errors.append(f"`instructions[{index}].task` must be a non-empty string.")
            expected = item.get("expected_evidence")
            if not isinstance(expected, list) or not expected:
                errors.append(f"`instructions[{index}].expected_evidence` must be a non-empty list.")

    if isinstance(scope, dict):
        if analyze_phase(contract, phase_name).writes_product_code:
            docs = read_first.get("docs") if isinstance(read_first, dict) else []
            if not isinstance(docs, list) or IMPLEMENTATION_QUALITY_DOC not in docs:
                errors.append(
                    f"`read_first.docs` must include `{IMPLEMENTATION_QUALITY_DOC}` for implementation phases."
                )
            if not isinstance(docs, list) or not task_design_doc_paths(task_path).intersection(docs):
                errors.append(
                    "`read_first.docs` must include the approved implementation design review "
                    "or design review waiver for implementation phases."
                )

    commands = contract_acceptance_commands(contract)
    if not commands:
        errors.append("`acceptance_commands` must be a non-empty list.")
    elif any(command == "TODO" for command in commands):
        errors.append("`acceptance_commands` must not contain TODO.")

    outputs = contract_required_outputs(contract)
    if not outputs:
        errors.append("`required_outputs` must be a non-empty list.")
    else:
        errors.extend(_validate_path_list(root, task_path, outputs, "required_outputs", False, task_relative=True))

    repo_outputs = contract.get("required_repo_outputs")
    if repo_outputs is not None:
        repo_output_values = contract_required_repo_outputs(contract)
        if not repo_output_values:
            errors.append("`required_repo_outputs` must be a non-empty list when present.")
        else:
            errors.extend(_validate_repo_relative_path_list(root, repo_outputs, "required_repo_outputs"))
            allowed_paths = contract_allowed_paths(contract)
            for raw_path in repo_output_values:
                if not path_allowed(raw_path, allowed_paths):
                    errors.append(
                        "`required_repo_outputs` entries must also be covered by "
                        f"`scope.allowed_paths`: {raw_path}"
                    )

    forbidden = contract.get("forbidden")
    if not isinstance(forbidden, list) or not forbidden:
        errors.append("`forbidden` must be a non-empty list.")
    else:
        for index, item in enumerate(forbidden):
            if not isinstance(item, dict):
                errors.append(f"`forbidden[{index}]` must be an object.")
                continue
            rule = item.get("rule")
            reason = item.get("reason")
            if not isinstance(rule, str) or not rule.strip():
                errors.append(f"`forbidden[{index}].rule` must be a non-empty string.")
            elif any(pattern.search(rule) for pattern in GENERIC_FORBIDDEN_RULE_PATTERNS):
                errors.append(f"`forbidden[{index}].rule` must be concrete, not generic caution.")
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"`forbidden[{index}].reason` must be a non-empty string.")

    return contract, errors


def checklist_markdown(contract: dict[str, Any]) -> str:
    lines = [
        f"# Phase {contract.get('phase')} Checklist",
        "",
        "## Read First",
        "",
    ]
    read_first = contract.get("read_first") if isinstance(contract.get("read_first"), dict) else {}
    for raw_path in read_first.get("docs") or []:
        lines.append(f"- [ ] `{raw_path}`")
    for raw_path in read_first.get("previous_outputs") or []:
        lines.append(f"- [ ] `{raw_path}`")

    scope = contract.get("scope") if isinstance(contract.get("scope"), dict) else {}
    lines.extend(["", "## Scope", ""])
    if scope.get("layer"):
        lines.append(f"- [ ] Layer: `{scope['layer']}`")
    for raw_path in scope.get("allowed_paths") or []:
        lines.append(f"- [ ] Only edit `{raw_path}`")

    lines.extend(["", "## Decision Refs", ""])
    for ref in contract.get("decision_refs") or []:
        lines.append(f"- [ ] `{ref}`")

    lines.extend(["", "## Architecture Refs", ""])
    for ref in contract.get("architecture_refs") or []:
        lines.append(f"- [ ] `{ref}`")

    dependency_policy = contract.get("dependency_policy") if isinstance(contract.get("dependency_policy"), dict) else {}
    lines.extend(["", "## Dependency Policy", ""])
    if dependency_policy:
        lines.append(f"- [ ] new_dependencies: `{dependency_policy.get('new_dependencies')}`")
        for item in dependency_policy.get("approved_new_dependencies") or []:
            lines.append(f"  - Approved: `{item}`")
        for item in dependency_policy.get("approved_dependency_manifest_changes") or []:
            lines.append(f"  - Approved manifest change: `{item}`")

    lines.extend(["", "## Interfaces", ""])
    for item in contract.get("interfaces") or []:
        lines.append(f"- [ ] `{item.get('signature', '')}` in `{item.get('path', '')}`")
        for rule in item.get("business_rules") or []:
            lines.append(f"  - Business rule: {rule}")

    lines.extend(["", "## Instructions", ""])
    for item in contract.get("instructions") or []:
        lines.append(f"- [ ] {item.get('id')}: {item.get('task')}")
        for expected in item.get("expected_evidence") or []:
            lines.append(f"  - Evidence: {expected}")

    lines.extend(["", "## Acceptance Commands", ""])
    for command in contract_acceptance_commands(contract):
        lines.append(f"- [ ] `{command}`")

    lines.extend(["", "## Success Criteria", ""])
    for item in contract.get("success_criteria") or []:
        lines.append(f"- [ ] {item}")

    lines.extend(["", "## Stop Rules", ""])
    for item in contract.get("stop_rules") or []:
        lines.append(f"- [ ] {item}")

    fallback = contract.get("fallback_behavior") if isinstance(contract.get("fallback_behavior"), dict) else {}
    lines.extend(["", "## Fallback Behavior", ""])
    for key in ["if_blocked", "if_tests_fail"]:
        if fallback.get(key):
            lines.append(f"- [ ] {key}: {fallback[key]}")

    budget = contract.get("validation_budget") if isinstance(contract.get("validation_budget"), dict) else {}
    lines.extend(["", "## Validation Budget", ""])
    for key in ["max_attempts", "command_timeout_seconds"]:
        if key in budget:
            lines.append(f"- [ ] {key}: `{budget[key]}`")

    lines.extend(["", "## Missing Evidence Behavior", ""])
    if contract.get("missing_evidence_behavior"):
        lines.append(f"- [ ] {contract.get('missing_evidence_behavior')}")

    verification = contract.get("verification_evidence") if isinstance(contract.get("verification_evidence"), dict) else {}
    if verification:
        lines.extend(["", "## Verification Evidence", ""])
        for item in verification.get("reproduction") or []:
            lines.append(f"- [ ] Reproduction: {item}")
        if verification.get("fallback_reason"):
            lines.append(f"- [ ] Fallback reason: {verification['fallback_reason']}")
        for item in verification.get("alternative_evidence") or []:
            lines.append(f"- [ ] Alternative evidence: {item}")

    command_expectations = [
        item for item in contract.get("command_expectations") or [] if isinstance(item, dict)
    ]
    if command_expectations:
        lines.extend(["", "## Command Expectations", ""])
        for item in command_expectations:
            expectation_id = item.get("id", "")
            role = item.get("role", "")
            command = item.get("command", "")
            target = item.get("target")
            repo_scan = item.get("repo_scan")
            suffix = []
            if target:
                suffix.append(f"target: {target}")
            if repo_scan is not None:
                suffix.append(f"repo_scan: {repo_scan}")
            suffix_text = f" ({', '.join(suffix)})" if suffix else ""
            prefix = f"{expectation_id} {role}".strip()
            lines.append(f"- [ ] {prefix}: `{command}`{suffix_text}")

    lines.extend(["", "## Required Outputs", ""])
    for raw_path in contract_required_outputs(contract):
        lines.append(f"- [ ] `{raw_path}`")

    repo_outputs = contract_required_repo_outputs(contract)
    if repo_outputs:
        lines.extend(["", "## Required Repo Outputs", ""])
        for raw_path in repo_outputs:
            lines.append(f"- [ ] `{raw_path}`")

    lines.extend(["", "## Forbidden", ""])
    for item in contract.get("forbidden") or []:
        lines.append(f"- [ ] {item.get('rule')}")
        lines.append(f"  - Reason: {item.get('reason')}")

    lines.append("")
    return "\n".join(lines)


def _handoff_marker_kind(matched_text: str) -> str:
    value = matched_text.lower()
    if "partial" in value or "부분" in matched_text or "일부" in matched_text:
        return "partial"
    if "skipped" in value:
        return "skipped"
    if "workaround" in value or "우회" in matched_text:
        return "workaround"
    if "failed" in value:
        return "failed"
    if (
        "blocked" in value
        or "could not" in value
        or "unable" in value
        or "not implemented" in value
        or "rejected path" in value
        or "막힘" in matched_text
        or "막혔" in matched_text
        or "차단" in matched_text
        or "구현하지 못" in matched_text
    ):
        return "blocked"
    return "unknown"


def _handoff_marker_is_negated(text: str, match: re.Match[str]) -> bool:
    window = text[max(0, match.start() - 24) : match.end() + 24].lower()
    return any(
        phrase in window
        for phrase in [
            "no workaround",
            "without workaround",
            "workaround was not",
            "workaround was never",
            "우회 없이",
            "우회하지 않",
            "우회 없음",
        ]
    )


def handoff_block_markers(text: str) -> list[dict[str, str]]:
    markers: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for rule in HANDOFF_BLOCK_RULES:
        pattern = rule["pattern"]
        match = pattern.search(text)
        if not match:
            continue
        if _handoff_marker_is_negated(text, match):
            continue
        matched_text = match.group(0).strip()
        kind = _handoff_marker_kind(matched_text)
        key = (str(rule["id"]), kind, matched_text)
        if key in seen:
            continue
        seen.add(key)
        markers.append(
            {
                "kind": kind,
                "rule_id": str(rule["id"]),
                "matched_text": matched_text,
                "message": f"handoff reports {kind} status: {matched_text}",
            }
        )
    return markers


def classify_handoff_text(text: str) -> dict[str, Any]:
    markers = handoff_block_markers(text)
    return {
        "status": "incomplete" if markers else "complete",
        "blocking": bool(markers),
        "source": "legacy_text_classifier",
        "markers": markers,
        "reasons": [marker["message"] for marker in markers],
    }


def handoff_block_reasons(text: str) -> list[str]:
    return [marker["message"] for marker in handoff_block_markers(text)]


def handoff_change_trace(text: str) -> dict[str, list[str]]:
    match = CHANGE_TRACE_SECTION_RE.search(text)
    if not match:
        return {}
    trace: dict[str, list[str]] = {}
    for line in match.group("body").splitlines():
        line_match = CHANGE_TRACE_LINE_RE.match(line)
        if not line_match:
            continue
        ids = [
            group
            for match_id in INSTRUCTION_ID_RE.finditer(line_match.group("ids"))
            for group in match_id.groups()
            if group
        ]
        trace[line_match.group("path").strip("/")] = ids
    return trace


def handoff_change_trace_errors(
    text: str,
    changed_files: list[str],
    instruction_ids: list[str],
) -> list[str]:
    normalized_changed = sorted({path.strip("/") for path in changed_files if path.strip("/")})
    if not normalized_changed:
        return []
    trace = handoff_change_trace(text)
    if not trace:
        return ["Handoff must include `## Change Trace` with changed file to instruction id mappings."]

    errors: list[str] = []
    allowed_ids = set(instruction_ids)
    for path in normalized_changed:
        ids = trace.get(path)
        if not ids:
            errors.append(f"Handoff change trace must map changed file to instruction id: {path}")
            continue
        unknown_ids = [item for item in ids if item not in allowed_ids]
        if unknown_ids:
            errors.append(
                "Handoff change trace uses unknown instruction id(s) "
                f"for {path}: {unknown_ids!r}"
            )
    return errors
