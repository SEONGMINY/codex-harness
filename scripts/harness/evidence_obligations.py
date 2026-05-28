"""Helpers for matching phase evidence to contract expected evidence."""

from __future__ import annotations

from typing import Any


def command_result_by_id(command_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(item["id"]): item
        for item in command_results
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
    }


def successful_command_ids(command_results: list[dict[str, Any]]) -> set[str]:
    return {
        command_id
        for command_id, item in command_result_by_id(command_results).items()
        if item.get("exit_code") == 0
    }


def _successful_command_refs(evidence: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for item in evidence.get("commands") or []:
        if not isinstance(item, dict) or item.get("exit_code") != 0:
            continue
        for field in ["id", "command"]:
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                refs.add(value.strip())
    return refs


def _existing_paths(evidence: dict[str, Any], field: str) -> set[str]:
    paths: set[str] = set()
    for item in evidence.get(field) or []:
        if isinstance(item, dict) and item.get("exists") is True and isinstance(item.get("path"), str):
            paths.add(item["path"].strip())
    return paths


def _changed_files(evidence: dict[str, Any]) -> set[str]:
    return {item.strip() for item in evidence.get("changed_files") or [] if isinstance(item, str) and item.strip()}


def _legacy_path_match(ref: str, paths: set[str]) -> bool:
    return ref in paths or any(path.endswith("/" + ref) for path in paths)


def evidence_ref_matched(ref: Any, evidence: dict[str, Any]) -> bool:
    if isinstance(ref, dict):
        ref_type = ref.get("type")
        value = ref.get("ref")
        if not isinstance(value, str) or not value.strip():
            return False
        value = value.strip()
        if ref_type == "command":
            return value in _successful_command_refs(evidence)
        if ref_type == "required_output":
            return value in _existing_paths(evidence, "required_outputs")
        if ref_type == "required_repo_output":
            return value in _existing_paths(evidence, "required_repo_outputs")
        if ref_type == "changed_file":
            return value in _changed_files(evidence)
        return False
    if not isinstance(ref, str) or not ref.strip():
        return False
    value = ref.strip()
    if value in _successful_command_refs(evidence):
        return True
    if value in _existing_paths(evidence, "required_outputs"):
        return True
    if value in _existing_paths(evidence, "required_repo_outputs"):
        return True
    return _legacy_path_match(value, _changed_files(evidence))


def instruction_evidence_matches(contract: dict[str, Any], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in contract.get("instructions") or []:
        if not isinstance(item, dict):
            continue
        expected = [ref for ref in item.get("expected_evidence") or [] if ref]
        matched = [ref for ref in expected if evidence_ref_matched(ref, evidence)]
        missing = [ref for ref in expected if ref not in matched]
        results.append(
            {
                "id": item.get("id"),
                "matched_expected_evidence": matched,
                "missing_expected_evidence": missing,
            }
        )
    return results


def expected_evidence_gate_failures(contract: dict[str, Any], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": result.get("id"),
            "missing_expected_evidence": result["missing_expected_evidence"],
        }
        for result in instruction_evidence_matches(contract, evidence)
        if result.get("missing_expected_evidence")
    ]
