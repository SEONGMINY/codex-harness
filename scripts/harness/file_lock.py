"""Symlink-safe file lock helpers for harness state files."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

from artifact_io import ensure_no_symlink_path


LOCK_INVALID_JSON_STALE_SECONDS = 30


class LockHandle(NamedTuple):
    path: Path
    identity: tuple[int, int, int, int]


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def file_identity(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size)


def lock_is_stale(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        try:
            age_seconds = time.time() - path.stat().st_mtime
        except OSError:
            return True
        return age_seconds > LOCK_INVALID_JSON_STALE_SECONDS
    pid = data.get("pid") if isinstance(data, dict) else None
    if not isinstance(pid, int) or pid <= 0:
        return True
    return not process_is_alive(pid)


def remove_stale_lock(path: Path) -> bool:
    try:
        observed_identity = file_identity(path)
    except FileNotFoundError:
        return True
    if not lock_is_stale(path):
        return False
    try:
        current_identity = file_identity(path)
    except FileNotFoundError:
        return True
    if current_identity != observed_identity:
        return False
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return True


def write_lock_candidate(path: Path, metadata: dict[str, Any] | None = None, boundary: Path | None = None) -> Path:
    ensure_no_symlink_path(path, boundary=boundary)
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_no_symlink_path(path.parent, boundary=boundary)
    candidate = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    payload: dict[str, Any] = {"pid": os.getpid(), "started_at": now()}
    if metadata:
        payload.update(metadata)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY | nofollow, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return candidate


def acquire_lock(
    path: Path,
    metadata: dict[str, Any] | None = None,
    wait_timeout_seconds: float = 0,
    poll_interval_seconds: float = 0.05,
    boundary: Path | None = None,
) -> LockHandle:
    deadline = time.monotonic() + wait_timeout_seconds
    while True:
        candidate = write_lock_candidate(path, metadata, boundary)
        try:
            os.link(candidate, path)
        except FileExistsError as exc:
            candidate.unlink(missing_ok=True)
            if remove_stale_lock(path):
                continue
            if wait_timeout_seconds > 0 and time.monotonic() < deadline:
                time.sleep(poll_interval_seconds)
                continue
            raise RuntimeError(f"Another codex-harness process is active: {path}") from exc
        finally:
            candidate.unlink(missing_ok=True)
        return LockHandle(path=path, identity=file_identity(path))


def task_runtime_lock_path(task_path: Path) -> Path:
    return task_path / "context-pack" / "runtime" / "run-phases.lock"


def acquire_task_runtime_lock(
    task_path: Path,
    owner: str,
    *,
    wait_timeout_seconds: float = 0,
) -> LockHandle:
    return acquire_lock(
        task_runtime_lock_path(task_path),
        metadata={"owner": owner, "task_dir": task_path.name},
        wait_timeout_seconds=wait_timeout_seconds,
        boundary=task_path,
    )


def release_lock(handle: LockHandle | None) -> None:
    if handle is None:
        return
    try:
        if file_identity(handle.path) != handle.identity:
            return
    except FileNotFoundError:
        return
    handle.path.unlink(missing_ok=True)
