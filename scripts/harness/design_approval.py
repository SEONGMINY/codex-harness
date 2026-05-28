"""Shared design approval bundle helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


DESIGN_APPROVAL_STATIC_BUNDLE_FILES = [
    "design-contract.json",
    "traceability-matrix.json",
    "review-findings.json",
    "review-coverage.json",
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


def rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _bundle_entry(root: Path, path: Path) -> dict[str, str]:
    return {"path": rel(root, path), "sha256": file_sha256(path)}


def design_approval_bundle_entries(
    root: Path,
    task_path: Path,
    design_rel_path: str,
) -> tuple[list[dict[str, str]], list[str]]:
    errors: list[str] = []
    paths = [root / design_rel_path]
    static_dir = task_path / "context-pack" / "static"
    for name in DESIGN_APPROVAL_STATIC_BUNDLE_FILES:
        candidate = static_dir / name
        if candidate.exists():
            paths.append(candidate)
    entries: list[dict[str, str]] = []
    for path in paths:
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError:
            errors.append(f"Design approval bundle path must be repo-relative: {path}")
            continue
        if not path.exists() or not path.is_file():
            errors.append(f"Missing design approval bundle file: {rel(root, path)}")
            continue
        entries.append(_bundle_entry(root, path))
    return sorted(entries, key=lambda item: item["path"]), errors


def design_approval_bundle_sha256(entries: list[dict[str, str]]) -> str:
    return stable_json_sha256(sorted(entries, key=lambda item: item.get("path", "")))
