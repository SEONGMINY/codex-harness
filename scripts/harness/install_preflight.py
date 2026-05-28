"""Stdlib-only install validation for harness entrypoints."""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, TextIO


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


def iter_runtime_attestation_files(script_dir: Path) -> list[str]:
    if not script_dir.exists():
        return []
    paths: list[str] = []
    for path in script_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(script_dir)
        if any(part in RUNTIME_ATTESTATION_EXCLUDED_DIRS for part in relative.parts):
            continue
        if path.suffix not in RUNTIME_ATTESTATION_SUFFIXES:
            continue
        paths.append(relative.as_posix())
    return sorted(paths)


def harness_attestation(script_dir: Path) -> dict[str, Any]:
    entries = [
        {"path": f"harness:{rel_path}", "sha256": file_sha256(script_dir / rel_path)}
        for rel_path in iter_runtime_attestation_files(script_dir)
    ]
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


def parse_root_arg(argv: Sequence[str]) -> Path:
    for index, item in enumerate(argv):
        if item == "--root" and index + 1 < len(argv):
            return Path(argv[index + 1]).resolve()
        if item.startswith("--root="):
            return Path(item.split("=", 1)[1]).resolve()
    return Path(".").resolve()


def expected_runtime_paths(attestation: dict[str, Any]) -> list[str]:
    entries = attestation.get("entries")
    if not isinstance(entries, list):
        return []
    paths: list[str] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        raw_path = item.get("path")
        if isinstance(raw_path, str) and raw_path.startswith("harness:"):
            paths.append(raw_path.removeprefix("harness:"))
    return sorted(paths)


def install_validation_errors(root: Path, harness_version: str) -> list[str]:
    manifest_path = root / "codex-harness.json"
    install_manifest_path = root / ".codex" / "harness" / "install-manifest.json"
    script_dir = root / ".codex" / "harness" / "scripts"
    required_paths = [manifest_path, install_manifest_path]
    missing_required = [str(path.relative_to(root)) for path in required_paths if not path.exists()]
    if missing_required:
        return [
            "codex-harness is not installed in this project. Missing: "
            + ", ".join(missing_required)
        ]

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [f"Invalid codex-harness.json: {exc}"]

    version = manifest.get("version") if isinstance(manifest, dict) else None
    if version != harness_version:
        return [
            "codex-harness version mismatch: "
            f"script={harness_version}, manifest={version or '(missing)'}. "
            "Reinstall or update codex-harness in this project."
        ]

    try:
        install_manifest = json.loads(install_manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [f"Invalid codex-harness install manifest: {exc}"]

    expected_attestation = (
        install_manifest.get("runtime_attestation") if isinstance(install_manifest, dict) else None
    )
    expected = attestation_fingerprint(expected_attestation)
    if expected is None:
        return ["codex-harness install manifest is missing a valid runtime_attestation."]

    missing_runtime = [
        str((script_dir / rel_path).relative_to(root))
        for rel_path in expected_runtime_paths(expected_attestation)
        if not (script_dir / rel_path).exists()
    ]
    if missing_runtime:
        return [
            "codex-harness is not installed in this project. Missing: "
            + ", ".join(missing_runtime)
        ]

    current = attestation_fingerprint(harness_attestation(script_dir))
    if current != expected:
        return [
            "codex-harness installed runtime drift detected. "
            "Reinstall or update codex-harness in this project."
        ]
    return []


def validate_entrypoint_install_or_exit(
    argv: Sequence[str],
    harness_version: str,
    *,
    stderr: TextIO | None = None,
) -> None:
    errors = install_validation_errors(parse_root_arg(argv), harness_version)
    if not errors:
        return
    output = stderr or sys.stderr
    print("[ERROR] Invalid codex-harness installation:", file=output)
    for error in errors:
        print(f"- {error}", file=output)
    raise SystemExit(1)
