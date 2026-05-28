#!/usr/bin/env python3
"""Review phase plans for semantic execution risks before Generate."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from phase_contract import (
    contract_acceptance_commands,
    parse_phase_contract,
)
from phase_semantics import (
    analyze_phase,
    command_mentions_path,
    command_runs_test_suite,
    command_targets_any_path,
    command_uses_fixture_or_meta,
    command_uses_repo_scan,
)


PHASE_FILE_RE = re.compile(r"^phase(?P<number>\d+)\.md$")
AMBIGUOUS_IMPLEMENT_OR_PROVE_RE = re.compile(
    r"\b(?:implement|fix|repair)\s+or\s+(?:prove|verify|document)\b|"
    r"(?:구현|수정|보완)\s*(?:또는|or)\s*(?:증명|검증)",
    re.IGNORECASE,
)
DEFERRED_VALIDATOR_RE = re.compile(
    r"phase\s*\d+\s+can\s+enforce|"
    r"future\s+(?:phase|work)\s+can\s+enforce|"
    r"known\s+(?:app\s+)?gaps?.{0,80}(?:documented|not\s+fail|instead\s+of\s+fail)|"
    r"instead\s+of\s+failing|"
    r"현재.{0,80}gap.{0,80}실패.{0,20}않|"
    r"나중에.{0,40}강제",
    re.IGNORECASE | re.DOTALL,
)
DESIGN_NOT_APPROVED_RE = re.compile(r"(?i)design approval status:\s*not approved|설계 승인 상태:\s*미승인")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def read_json_with_error(path: Path, label: str) -> tuple[dict[str, Any], str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, f"Missing {label}: {path.name}"
    except json.JSONDecodeError as exc:
        return {}, f"Invalid {label} JSON: {exc}"
    except OSError as exc:
        return {}, f"Cannot read {label}: {exc}"
    if not isinstance(value, dict):
        return {}, f"{label} must be a JSON object."
    return value, None


def repo_relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def phase_files(task_path: Path) -> list[Path]:
    phase_dir = task_path / "phases"
    return sorted(phase_dir.glob("phase*.md"), key=phase_file_sort_key)


def phase_file_sort_key(path: Path) -> tuple[int, int | str, str]:
    match = PHASE_FILE_RE.match(path.name)
    if match:
        return (0, int(match.group("number")), path.name)
    return (1, path.name, path.name)


def phase_number_from_contract(contract: dict[str, Any], fallback: int) -> int:
    value = contract.get("phase")
    return value if isinstance(value, int) else fallback


def text_for_contract(markdown: str, contract: dict[str, Any]) -> str:
    parts = [markdown, str(contract.get("name") or "")]
    scope = contract.get("scope")
    if isinstance(scope, dict):
        parts.append(str(scope.get("layer") or ""))
    for instruction in contract.get("instructions") or []:
        if isinstance(instruction, dict):
            parts.append(str(instruction.get("task") or ""))
    for criterion in contract.get("success_criteria") or []:
        if isinstance(criterion, str):
            parts.append(criterion)
    for interface in contract.get("interfaces") or []:
        if isinstance(interface, dict):
            for field in ["symbol", "signature"]:
                parts.append(str(interface.get(field) or ""))
            for rule in interface.get("business_rules") or []:
                if isinstance(rule, str):
                    parts.append(rule)
    return "\n".join(parts)


def review_design_approval_text(root: Path, task_path: Path) -> list[str]:
    approval = read_json(task_path / "context-pack" / "static" / "design-approval.json")
    if approval.get("approved") is not True:
        return []
    raw_doc = approval.get("approved_doc")
    if not isinstance(raw_doc, str) or not raw_doc.strip():
        return []
    doc_path = root / raw_doc
    try:
        text = doc_path.read_text(encoding="utf-8")
    except OSError:
        return []
    if DESIGN_NOT_APPROVED_RE.search(text):
        return [
            f"{repo_relative(doc_path, root)} still says design approval is not approved after design approval was recorded."
        ]
    return []


def review_validation_only_acceptance(label: str, contract: dict[str, Any]) -> list[str]:
    semantics = analyze_phase(contract)
    if not semantics.validation_only or not semantics.writes_validator:
        return []

    target_paths = semantics.validator_paths or semantics.test_or_validator_paths
    acceptance_commands = contract_acceptance_commands(contract)
    verification = contract.get("verification_evidence")
    reproduction_commands = []
    if isinstance(verification, dict):
        reproduction_commands = [
            item for item in verification.get("reproduction") or [] if isinstance(item, str)
        ]
    command_expectations = [
        item for item in contract.get("command_expectations") or [] if isinstance(item, dict)
    ]

    validator_acceptance = [
        command
        for command in acceptance_commands
        if command_targets_any_path(command, target_paths) or command_runs_test_suite(command)
    ]
    if not validator_acceptance:
        return []

    has_repo_scan_reproduction = any(
        (command_targets_any_path(command, target_paths) or command_runs_test_suite(command))
        and command_uses_repo_scan(command)
        for command in reproduction_commands
    ) or any(
        item.get("role") == "reproduction"
        and item.get("repo_scan") is True
        and isinstance(item.get("command"), str)
        and item.get("command") in reproduction_commands
        for item in command_expectations
    )
    has_fixture_or_meta_acceptance = any(
        command_uses_fixture_or_meta(command)
        for command in validator_acceptance
    )
    if not has_fixture_or_meta_acceptance:
        for item in command_expectations:
            command = item.get("command")
            target = item.get("target")
            if item.get("role") not in {"fixture", "meta"} or not isinstance(command, str):
                continue
            if command not in validator_acceptance:
                continue
            if item.get("role") == "meta" or command_uses_fixture_or_meta(command):
                has_fixture_or_meta_acceptance = True
                break
            if isinstance(target, str) and command_mentions_path(command, target):
                has_fixture_or_meta_acceptance = True
                break
    if not has_repo_scan_reproduction or has_fixture_or_meta_acceptance:
        return []

    return [
        f"{label}: validation-only phase must separate failing repo-scan reproduction "
        "from passing fixture/meta acceptance, or include product implementation scope."
    ]


def acceptance_refs(contract: dict[str, Any]) -> dict[str, str]:
    refs = {command: "acceptance" for command in contract_acceptance_commands(contract)}
    for item in contract.get("command_expectations") or []:
        if not isinstance(item, dict):
            continue
        command = item.get("command")
        ref_id = item.get("id")
        role = item.get("role")
        if role == "acceptance":
            if isinstance(command, str):
                refs[command] = "acceptance"
            if isinstance(ref_id, str):
                refs[ref_id] = "acceptance"
        elif isinstance(ref_id, str):
            refs[ref_id] = str(role or "")
    return refs


def design_obligations(design_contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: item
        for item in design_contract.get("obligations") or []
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def review_risk_ledger(label: str, contract: dict[str, Any]) -> list[str]:
    refs = acceptance_refs(contract)
    errors: list[str] = []
    for risk in contract.get("risk_ledger") or []:
        if not isinstance(risk, dict):
            continue
        missing = [
            item
            for item in risk.get("required_evidence") or []
            if not isinstance(item, str) or refs.get(item) != "acceptance"
        ]
        if missing:
            errors.append(f"{label}: risk_ledger required_evidence is not covered by same-phase acceptance evidence: {missing!r}")
    return errors


def review_obligation_closure(label: str, contract: dict[str, Any], obligations: dict[str, dict[str, Any]]) -> list[str]:
    refs = acceptance_refs(contract)
    errors: list[str] = []
    for obligation_id in contract.get("closes_obligations") or []:
        if obligation_id not in obligations:
            errors.append(f"{label}: design-contract obligations are unavailable for closes_obligations entry: {obligation_id}")
            continue
        obligation = obligations[obligation_id]
        closure_refs = [item for item in obligation.get("closure_command_refs") or [] if isinstance(item, str)]
        missing = [item for item in closure_refs if refs.get(item) != "acceptance"]
        if missing:
            errors.append(f"{label}: closes_obligations {obligation_id} closure_command_refs must be same-phase acceptance evidence: {missing!r}")
        required_roles = [item for item in obligation.get("required_command_roles") or [] if isinstance(item, str)]
        if "acceptance" in required_roles and missing:
            errors.append(f"{label}: closes_obligations {obligation_id} required roles are not satisfied by closure refs.")
    return errors


def review_traceability(label_by_phase: dict[int, str], parsed: list[tuple[Path, int, str, dict[str, Any]]], matrix: dict[str, Any]) -> list[str]:
    closes_by_phase = {
        phase_number: {
            item for item in contract.get("closes_obligations") or [] if isinstance(item, str)
        }
        for _path, phase_number, _markdown, contract in parsed
    }
    errors: list[str] = []
    for entry in matrix.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        phase = entry.get("phase")
        design_ref = entry.get("design_ref")
        evidence = entry.get("evidence") or []
        if isinstance(phase, int) and isinstance(design_ref, str) and f"obligation:{design_ref}" in evidence:
            if design_ref not in closes_by_phase.get(phase, set()):
                errors.append(
                    f"{label_by_phase.get(phase, 'phase ' + str(phase))}: traceability-matrix assigns obligation {design_ref} to this phase but the phase does not close it."
                )
    return errors


def review_public_interfaces(label: str, contract: dict[str, Any]) -> list[str]:
    interfaces = [item for item in contract.get("interfaces") or [] if isinstance(item, dict)]
    internal_symbols = {
        str(item.get("symbol"))
        for item in interfaces
        if str(item.get("visibility") or "").lower() == "internal"
        or re.search(r"\bprotocol\b", str(item.get("signature") or "")) and "public protocol" not in str(item.get("signature") or "")
    }
    errors: list[str] = []
    for item in interfaces:
        signature = str(item.get("signature") or "")
        symbol = str(item.get("symbol") or "")
        raw_visibility = item.get("visibility")
        is_public = (
            str(raw_visibility).lower() == "public"
            if isinstance(raw_visibility, str) and raw_visibility
            else bool(re.search(r"\bpublic\b", signature))
        )
        if not is_public:
            continue
        for internal in internal_symbols:
            if internal and internal != symbol and internal in signature:
                errors.append(f"{label}: public interface exposes internal protocol/type {internal}.")
        for exposed in item.get("exposes") or []:
            if isinstance(exposed, str) and exposed in internal_symbols:
                errors.append(f"{label}: public interface exposes non-public interface symbol(s) via structured metadata: {exposed}.")
    return errors


def review_implicit_obligation_claims(label: str, contract: dict[str, Any], obligations: dict[str, dict[str, Any]]) -> list[str]:
    text = text_for_contract("", contract).lower()
    closed = {item for item in contract.get("closes_obligations") or [] if isinstance(item, str)}
    closed_classes = {obligations[item].get("class") for item in closed if item in obligations}
    errors: list[str] = []
    if ("secret" in text or "sdk boundary" in text) and "secret_sdk_boundary" not in closed_classes:
        errors.append(f"{label}: secret_sdk_boundary design obligation must be closed in the same phase.")
    if ("append" in text or "re-reading" in text or "re-read" in text) and not ({"transaction_boundary", "concurrency_atomicity"} & set(closed_classes)):
        errors.append(f"{label}: append-preserving behavior requires transaction or concurrency design obligation closure.")
    return errors


def review_phase_plan(root: Path, task_path: Path) -> list[str]:
    errors: list[str] = []
    parsed: list[tuple[Path, int, str, dict[str, Any]]] = []
    for index, path in enumerate(phase_files(task_path)):
        markdown = path.read_text(encoding="utf-8")
        contract, parse_errors = parse_phase_contract(markdown)
        if parse_errors or contract is None:
            errors.extend(f"{repo_relative(path, root)}: {error}" for error in parse_errors)
            continue
        parsed.append((path, phase_number_from_contract(contract, index), markdown, contract))

    errors.extend(review_design_approval_text(root, task_path))
    static_dir = task_path / "context-pack" / "static"
    design_contract, design_error = read_json_with_error(static_dir / "design-contract.json", "design-contract.json")
    if design_error:
        errors.append(design_error)
    traceability, traceability_error = read_json_with_error(static_dir / "traceability-matrix.json", "traceability-matrix.json")
    if traceability_error:
        errors.append(traceability_error)
    obligations = design_obligations(design_contract)
    label_by_phase = {phase_number: repo_relative(path, root) for path, phase_number, _markdown, _contract in parsed}
    errors.extend(review_traceability(label_by_phase, parsed, traceability))

    previous_xcodebuild_implementation_phases: list[int] = []
    for path, phase_number, markdown, contract in parsed:
        label = repo_relative(path, root)
        contract_text = text_for_contract(markdown, contract)
        semantics = analyze_phase(contract)
        has_implementation = semantics.writes_product_code
        has_swift = semantics.has_swift_paths
        has_xcodebuild = semantics.has_xcodebuild_acceptance
        validation_or_qa = semantics.phase_kind == "validation"

        if has_swift and not has_xcodebuild:
            errors.append(
                f"{label}: Swift implementation paths require an xcodebuild acceptance command in the same phase."
            )

        if has_xcodebuild and not has_implementation and not previous_xcodebuild_implementation_phases:
            errors.append(
                f"{label}: xcodebuild first appears in a non-implementation phase; compile failures may be discovered where implementation repair is out of scope."
            )

        if has_implementation and AMBIGUOUS_IMPLEMENT_OR_PROVE_RE.search(contract_text):
            errors.append(
                f"{label}: implementation contract uses ambiguous 'implement or prove' wording; split implementation from verification evidence."
            )

        if validation_or_qa and not has_implementation and DEFERRED_VALIDATOR_RE.search(contract_text):
            errors.append(
                f"{label}: validator/QA phase defers enforcement of known gaps to a later phase; planned state requires enforceable phase semantics."
            )

        errors.extend(review_validation_only_acceptance(label, contract))
        errors.extend(review_risk_ledger(label, contract))
        errors.extend(review_obligation_closure(label, contract, obligations))
        errors.extend(review_public_interfaces(label, contract))
        errors.extend(review_implicit_obligation_claims(label, contract, obligations))

        if has_implementation and has_xcodebuild:
            previous_xcodebuild_implementation_phases.append(phase_number)

    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", type=Path, help="Task directory, e.g. tasks/demo")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    task_path = args.task if args.task.is_absolute() else root / args.task
    errors = review_phase_plan(root, task_path)
    result = {
        "status": "passed" if not errors else "failed",
        "task": repo_relative(task_path, root),
        "errors": errors,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif errors:
        print("Phase plan review failed:")
        for error in errors:
            print(f"- {error}")
    else:
        print(f"Phase plan review passed: {repo_relative(task_path, root)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
