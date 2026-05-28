"""Canonical policy lineage helpers for design approval and runtime proof."""

from __future__ import annotations

import json
from typing import Any


FINGERPRINT_KEYS = ("id", "schema_version", "sha256")
LINEAGE_STATUSES = {"active", "historical", "revoked"}


def stable_json_sha256(value: object) -> str:
    import hashlib

    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def policy_pack_fingerprint(value: dict[str, Any] | None) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    result = {key: str(value.get(key) or "") for key in FINGERPRINT_KEYS}
    if not all(result.values()):
        return None
    return result


def _fingerprint_key(value: dict[str, str]) -> tuple[str, str, str]:
    return (value["id"], value["schema_version"], value["sha256"])


def sort_policy_pack_fingerprints(values: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(values, key=_fingerprint_key)


def normalize_policy_pack_fingerprints(
    values: Any,
    label: str,
) -> tuple[list[dict[str, str]], list[str]]:
    if not isinstance(values, list):
        return [], [f"{label} must be a list."]
    fingerprints: list[dict[str, str]] = []
    errors: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for index, item in enumerate(values):
        fingerprint = policy_pack_fingerprint(item if isinstance(item, dict) else None)
        if fingerprint is None:
            errors.append(f"{label}[{index}] must include non-empty id, schema_version, and sha256.")
            continue
        key = _fingerprint_key(fingerprint)
        if key in seen:
            errors.append(f"{label} duplicates policy pack fingerprint: {fingerprint}")
            continue
        seen.add(key)
        fingerprints.append(fingerprint)
    return sort_policy_pack_fingerprints(fingerprints), errors


def sort_policy_pack_lineage_entries(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(values, key=lambda item: (str(item["id"]), str(item["schema_version"]), str(item["sha256"]), str(item.get("status", ""))))


def normalize_policy_pack_lineage_entries(
    values: Any,
    label: str,
    active_policy_pack: dict[str, str] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(values, list):
        return [], [f"{label} must be a list."]
    errors: list[str] = []
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    active_key = _fingerprint_key(active_policy_pack) if active_policy_pack else None
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            errors.append(f"{label}[{index}] must be an object.")
            continue
        fingerprint = policy_pack_fingerprint(item)
        if fingerprint is None:
            errors.append(f"{label}[{index}] must include non-empty id, schema_version, and sha256.")
            continue
        key = _fingerprint_key(fingerprint)
        if key in seen:
            errors.append(f"{label} duplicates policy pack fingerprint: {fingerprint}")
            continue
        seen.add(key)
        status = str(item.get("status") or ("active" if key == active_key else "historical"))
        if status not in LINEAGE_STATUSES:
            errors.append(f"{label}[{index}].status must be one of {sorted(LINEAGE_STATUSES)!r}.")
            continue
        if status == "revoked":
            if not isinstance(item.get("revocation_reason"), str) or not item["revocation_reason"].strip():
                errors.append(f"{label}[{index}].revocation_reason is required for revoked policy packs.")
            if key == active_key:
                errors.append(f"{label}[{index}] active_policy_pack entry must not be revoked.")
        entry: dict[str, Any] = {**fingerprint, "status": status}
        if "revocation_reason" in item:
            entry["revocation_reason"] = str(item["revocation_reason"])
        replacement = policy_pack_fingerprint(item.get("replacement_policy_pack") if isinstance(item.get("replacement_policy_pack"), dict) else None)
        if replacement:
            entry["replacement_policy_pack"] = replacement
        entries.append(entry)
    return sort_policy_pack_lineage_entries(entries), errors


def allowed_policy_fingerprints(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    allowed = [
        {key: str(entry[key]) for key in FINGERPRINT_KEYS}
        for entry in entries
        if entry.get("status") != "revoked"
    ]
    return sort_policy_pack_fingerprints(allowed)


def policy_pack_lineage_sha256(entries: list[dict[str, Any]]) -> str:
    return stable_json_sha256(sort_policy_pack_lineage_entries(entries))


def design_approval_scope_sha256(
    approved_bundle: list[dict[str, Any]],
    approved_policy_packs: list[dict[str, str]],
    active_policy_pack: dict[str, str],
    approved_policy_pack_lineage: list[dict[str, Any]] | None = None,
) -> str:
    return stable_json_sha256(
        {
            "approved_bundle": approved_bundle,
            "approved_policy_packs": sort_policy_pack_fingerprints(approved_policy_packs),
            "active_policy_pack": active_policy_pack,
            "approved_policy_pack_lineage": sort_policy_pack_lineage_entries(approved_policy_pack_lineage or []),
        }
    )


def validate_current_policy_lineage(
    approval: dict[str, Any],
    current_policy_pack: dict[str, str] | None,
    *,
    action_label: str,
) -> list[str]:
    active = policy_pack_fingerprint(approval.get("active_policy_pack") if isinstance(approval, dict) else None)
    if active is None:
        return ["Design approval active_policy_pack must include non-empty id, schema_version, and sha256."]
    if current_policy_pack is None:
        return [f"Current policy pack is unavailable before {action_label}."]
    if _fingerprint_key(active) != _fingerprint_key(current_policy_pack):
        return [
            f"Current policy pack for {action_label} does not match design approval active_policy_pack."
        ]
    return []
