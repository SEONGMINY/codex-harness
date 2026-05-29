"""Runtime artifact integrity helpers for runner-owned phase proof."""

from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path
from typing import Iterable

from artifact_io import atomic_write_text
from runtime_protocol import phase_attempt_manifest_path, task_relative


RUNTIME_HASH_BYTE_LIMIT = 1024 * 1024
RUNTIME_METADATA_ONLY_FILE_RE = re.compile(r"^phase\d+-(?:output|stderr)-attempt\d+\.(?:jsonl|txt)$")


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_artifact_fingerprint(path: Path) -> str:
    try:
        if path.is_symlink():
            return "symlink:" + os.readlink(path)
        if path.is_file():
            stat = path.stat()
            if stat.st_size > RUNTIME_HASH_BYTE_LIMIT or RUNTIME_METADATA_ONLY_FILE_RE.match(path.name):
                return f"file-meta:{stat.st_size}:{stat.st_mtime_ns}"
            return "file:" + file_digest(path)
        if path.is_dir():
            return "dir"
        return "other"
    except OSError as exc:
        return f"error:{type(exc).__name__}:{exc}"


def runtime_artifact_snapshot(task_path: Path) -> dict[str, str]:
    runtime_dir = task_path / "context-pack" / "runtime"
    if not runtime_dir.exists():
        return {}
    snapshot: dict[str, str] = {}
    for path in sorted(runtime_dir.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            continue
        snapshot[task_relative(path, task_path)] = runtime_artifact_fingerprint(path)
    return snapshot


def runtime_artifact_stable_snapshot(
    task_path: Path,
    *,
    settle_seconds: float = 0.0,
    poll_seconds: float = 0.05,
) -> dict[str, str]:
    snapshot = runtime_artifact_snapshot(task_path)
    if settle_seconds <= 0:
        return snapshot
    poll_interval = max(poll_seconds, 0.001)
    deadline = time.monotonic() + max(settle_seconds * 3, settle_seconds + poll_interval)
    stable_since = time.monotonic()
    while True:
        time.sleep(poll_interval)
        next_snapshot = runtime_artifact_snapshot(task_path)
        now = time.monotonic()
        if next_snapshot == snapshot:
            if now - stable_since >= settle_seconds:
                return next_snapshot
        else:
            snapshot = next_snapshot
            stable_since = now
        if now >= deadline:
            return snapshot


def runtime_artifact_integrity_changes(
    before: dict[str, str],
    after: dict[str, str],
    *,
    allowed_paths: Iterable[str] = (),
    ignored_paths: Iterable[str] = (),
) -> list[str]:
    allowed = set(allowed_paths)
    ignored = set(ignored_paths)
    changes: list[str] = []
    for path in sorted(set(before) | set(after)):
        if path in allowed or path in ignored:
            continue
        before_value = before.get(path)
        after_value = after.get(path)
        if before_value == after_value:
            continue
        if before_value is None:
            changes.append(f"{path} created")
        elif after_value is None:
            changes.append(f"{path} deleted")
        else:
            changes.append(f"{path} modified")
    return changes


def restore_attempt_manifest_content(
    task_path: Path,
    phase_number: int,
    trusted_content: str,
) -> None:
    manifest_path = phase_attempt_manifest_path(task_path, phase_number)
    try:
        if manifest_path.is_symlink():
            manifest_path.unlink()
        current_content = manifest_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        current_content = None
    if current_content != trusted_content:
        atomic_write_text(manifest_path, trusted_content)
