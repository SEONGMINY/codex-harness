"""Design obligation closure validation helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def design_obligations_by_id(design_contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    obligations = design_contract.get("obligations")
    if not isinstance(obligations, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in obligations:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip():
            result[item["id"].strip()] = item
    return result


def display_value(value: str) -> str:
    lowered = value.lower()
    if any(marker in lowered for marker in ["token", "secret", "password", "private key", "bearer", "jwt"]):
        return "[redacted]"
    return value


def passed_command_roles(phase_result: dict[str, Any]) -> set[str]:
    return {
        str(item.get("role"))
        for item in phase_result.get("commands_run") or []
        if isinstance(item, dict) and item.get("exit_code") == 0 and item.get("role")
    }


def passed_command_refs(phase_result: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for item in phase_result.get("commands_run") or []:
        if not isinstance(item, dict) or item.get("exit_code") != 0:
            continue
        for field in ["id", "command"]:
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                refs.add(value.strip())
    return refs


def passed_commands_by_ref(phase_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    commands: dict[str, dict[str, Any]] = {}
    for item in phase_result.get("commands_run") or []:
        if not isinstance(item, dict) or item.get("exit_code") != 0:
            continue
        for field in ["id", "command"]:
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                commands[value.strip()] = item
    return commands


def closure_command_refs(obligation: dict[str, Any]) -> set[str]:
    return {
        item.strip()
        for item in obligation.get("closure_command_refs") or []
        if isinstance(item, str) and item.strip()
    }


def closure_output_contains(obligation: dict[str, Any]) -> set[str]:
    return {
        item.strip()
        for item in obligation.get("closure_output_contains") or []
        if isinstance(item, str) and item.strip()
    }


def closure_output_assertions(obligation: dict[str, Any]) -> list[dict[str, str]]:
    assertions = [{"type": "contains", "value": item} for item in sorted(closure_output_contains(obligation))]
    for item in obligation.get("closure_output_assertions") or []:
        if not isinstance(item, dict):
            continue
        assertion_type = item.get("type")
        value = item.get("value")
        if assertion_type not in {"contains", "exact_line"} or not isinstance(value, str) or not value.strip():
            continue
        assertion = {"type": assertion_type, "value": value.strip()}
        command_ref = item.get("command_ref")
        if isinstance(command_ref, str) and command_ref.strip():
            assertion["command_ref"] = command_ref.strip()
        assertions.append(assertion)
    return assertions


def assertion_command_refs(assertion: dict[str, Any], refs: set[str]) -> set[str]:
    command_ref = assertion.get("command_ref")
    if isinstance(command_ref, str) and command_ref.strip():
        return {command_ref.strip()} if command_ref.strip() in refs else set()
    return set(refs)


def command_output(command: dict[str, Any]) -> str:
    output = command.get("output")
    if isinstance(output, str):
        return output
    tail = command.get("output_tail")
    return tail if isinstance(tail, str) else ""


def command_output_truncated(command: dict[str, Any]) -> bool:
    if command.get("output_truncated") is True:
        return True
    output = command_output(command).lower()
    return "[truncated]" in output


def output_satisfies_assertion(output: str, assertion: dict[str, Any]) -> bool:
    value = assertion.get("value")
    if not isinstance(value, str):
        return False
    if assertion.get("type") == "contains":
        return value in output
    if assertion.get("type") == "exact_line":
        return any(line.strip() == value for line in output.splitlines())
    return False


def build_phase_obligation_assertion_outcomes(
    *,
    contract: dict[str, Any],
    phase_result: dict[str, Any],
    obligations: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    commands = passed_commands_by_ref(phase_result)
    outcomes: list[dict[str, Any]] = []
    for obligation_id in contract.get("closes_obligations") or []:
        obligation = obligations.get(obligation_id)
        if not obligation:
            continue
        refs = closure_command_refs(obligation) or set(commands.keys())
        for assertion in closure_output_assertions(obligation):
            candidate_refs = sorted(assertion_command_refs(assertion, refs))
            matched_ref = None
            for ref in candidate_refs:
                command = commands.get(ref)
                if command and output_satisfies_assertion(command_output(command), assertion):
                    matched_ref = ref
                    break
            outcome = {
                "obligation_id": obligation_id,
                "type": assertion.get("type"),
                "value": display_value(str(assertion.get("value") or "")),
                "passed": matched_ref is not None,
                "candidate_command_refs": candidate_refs,
            }
            if matched_ref is not None:
                outcome["command_ref"] = matched_ref
            if assertion.get("command_ref"):
                outcome["declared_command_ref"] = assertion["command_ref"]
            outcomes.append(outcome)
    return outcomes


def load_phase_result(task_path: Path, phase_number: int) -> dict[str, Any] | None:
    path = task_path / "context-pack" / "runtime" / f"phase{phase_number}-result.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def phase_obligation_closure_errors(
    *,
    phase_number: int,
    contract: dict[str, Any],
    phase_result: dict[str, Any] | None,
    obligations: dict[str, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    if phase_result is None:
        return [f"Phase {phase_number} obligation closure requires phase result proof."]
    result_commands = phase_result.get("commands_run") or []
    command_results = phase_result.get("commands_run") or phase_result.get("acceptance_commands") or []
    roles = passed_command_roles({"commands_run": command_results})
    refs = passed_command_refs({"commands_run": command_results})
    commands = passed_commands_by_ref({"commands_run": command_results})
    stored_outcomes = phase_result.get("obligation_closure_assertions")
    for obligation_id in contract.get("closes_obligations") or []:
        obligation = obligations.get(obligation_id)
        if not obligation:
            continue
        required_roles = {
            item.strip()
            for item in obligation.get("required_command_roles") or []
            if isinstance(item, str) and item.strip()
        }
        required_refs = closure_command_refs(obligation)
        role_refs = set()
        for ref in required_refs:
            command = commands.get(ref)
            if command and command.get("role") in required_roles:
                role_refs.add(ref)
        missing_roles = sorted(required_roles - roles)
        if required_roles and required_refs and len(role_refs) < len(required_refs):
            missing_roles = sorted(required_roles)
        if missing_roles:
            errors.append(
                f"Phase {phase_number} obligation {obligation_id!r} missing required roles: {missing_roles!r}"
            )
        missing = sorted(required_refs - refs)
        if missing:
            errors.append(
                f"Phase {phase_number} obligation {obligation_id!r} missing closure_command_refs: {missing!r}"
            )
        assertions = closure_output_assertions(obligation)
        if assertions and phase_result.get("schema_version") == 1:
            if not isinstance(stored_outcomes, list):
                errors.append(
                    f"Phase {phase_number} obligation {obligation_id!r} missing runner-owned obligation_closure_assertions."
                )
                continue
            failed = [
                item for item in stored_outcomes
                if isinstance(item, dict) and item.get("obligation_id") == obligation_id and item.get("passed") is not True
            ]
            if failed:
                errors.append(
                    f"Phase {phase_number} obligation {obligation_id!r} has failed closure_output_assertions."
                )
            continue
        for assertion in assertions:
            candidate_refs = assertion_command_refs(assertion, required_refs or refs)
            if not candidate_refs:
                errors.append(
                    f"Phase {phase_number} obligation {obligation_id!r} closure_output_assertions missing command ref."
                )
                continue
            matched = False
            truncated = False
            for ref in candidate_refs:
                command = commands.get(ref)
                if not command:
                    continue
                truncated = truncated or command_output_truncated(command)
                if command_output_truncated(command):
                    continue
                if output_satisfies_assertion(command_output(command), assertion):
                    matched = True
                    break
            if truncated and not matched:
                errors.append(
                    f"Phase {phase_number} obligation {obligation_id!r} command output is truncated."
                )
            if not matched:
                errors.append(
                    f"Phase {phase_number} obligation {obligation_id!r} closure_output_assertions "
                    f"{assertion.get('type')}: [redacted] not satisfied."
                )
    return errors
