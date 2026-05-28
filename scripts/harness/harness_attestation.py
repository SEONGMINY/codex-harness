"""Runtime harness attestation helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ATTESTED_FILES = [
    "artifact_io.py",
    "codex_exec.py",
    "command_policy.py",
    "design_contract.py",
    "env_policy.py",
    "evaluate-task.py",
    "evidence_obligations.py",
    "harness_attestation.py",
    "obligation_ledger.py",
    "phase_contract.py",
    "phase_semantics.py",
    "policy-packs/default-security.json",
    "policy_lineage.py",
    "policy_pack.py",
    "redaction.py",
    "reference_resolver.py",
    "review-phase-plan.py",
    "run-phases.py",
    "run-quality-checks.py",
    "verify-task.py",
]


def stable_json_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def harness_attestation() -> dict[str, Any]:
    entries = []
    for rel_path in ATTESTED_FILES:
        path = SCRIPT_DIR / rel_path
        if not path.exists():
            continue
        entries.append({"path": f"harness:{rel_path}", "sha256": file_sha256(path)})
    entries = sorted(entries, key=lambda item: item["path"])
    return {
        "schema_version": 1,
        "profile": "runtime-proof",
        "hash_algorithm": "sha256",
        "entries": entries,
        "digest": stable_json_sha256(entries),
    }


def attestation_fingerprint(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    entries = value.get("entries")
    if not isinstance(entries, list):
        return None
    digest = value.get("digest")
    if digest != stable_json_sha256(entries):
        return None
    return {
        "schema_version": value.get("schema_version"),
        "profile": value.get("profile"),
        "hash_algorithm": value.get("hash_algorithm"),
        "digest": digest,
    }
