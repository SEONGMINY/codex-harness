"""Runtime harness attestation helpers."""

from __future__ import annotations

from collections.abc import Iterator
import hashlib
import json
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
RUNTIME_ATTESTATION_SUFFIXES = {".json", ".py"}
RUNTIME_ATTESTATION_EXCLUDED_DIRS = {
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "skill",
}


def stable_json_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_runtime_attestation_files(script_dir: Path) -> Iterator[str]:
    if not script_dir.exists():
        return
    for path in script_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(script_dir)
        if any(part in RUNTIME_ATTESTATION_EXCLUDED_DIRS for part in relative.parts):
            continue
        if path.suffix not in RUNTIME_ATTESTATION_SUFFIXES:
            continue
        yield relative.as_posix()


def harness_attestation(script_dir: Path | None = None) -> dict[str, Any]:
    base_dir = script_dir or SCRIPT_DIR
    entries = []
    for rel_path in sorted(iter_runtime_attestation_files(base_dir)):
        path = base_dir / rel_path
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
