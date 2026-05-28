"""Symlink-safe file lock helpers for harness state files."""

from __future__ import annotations

import json
import os
import time
import fcntl
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

from artifact_io import ensure_no_symlink_path


class LockHandle(NamedTuple):
    path: Path
    identity: tuple[int, int, int, int]
    fd: int


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def file_identity(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size)


def fd_identity(fd: int) -> tuple[int, int, int, int]:
    stat = os.fstat(fd)
    return (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size)


def open_lock_file(path: Path, boundary: Path | None = None, *, create: bool = True) -> int:
    ensure_no_symlink_path(path, boundary=boundary)
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
        ensure_no_symlink_path(path.parent, boundary=boundary)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    flags = os.O_RDWR | nofollow
    if create:
        flags |= os.O_CREAT
    return os.open(path, flags, 0o600)


def try_lock_fd(fd: int) -> bool:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def write_lock_payload(fd: int, metadata: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"pid": os.getpid(), "started_at": now()}
    if metadata:
        payload.update(metadata)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, data)
    os.fsync(fd)


def lock_is_stale(path: Path) -> bool:
    try:
        fd = open_lock_file(path, create=False)
    except FileNotFoundError:
        return True
    except OSError:
        return True
    try:
        return try_lock_fd(fd)
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def remove_stale_lock(path: Path) -> bool:
    try:
        fd = open_lock_file(path, create=False)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    try:
        if not try_lock_fd(fd):
            return False
        observed_identity = fd_identity(fd)
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
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def acquire_lock(
    path: Path,
    metadata: dict[str, Any] | None = None,
    wait_timeout_seconds: float = 0,
    poll_interval_seconds: float = 0.05,
    boundary: Path | None = None,
) -> LockHandle:
    deadline = time.monotonic() + wait_timeout_seconds
    while True:
        fd = open_lock_file(path, boundary)
        if try_lock_fd(fd):
            write_lock_payload(fd, metadata)
            return LockHandle(path=path, identity=fd_identity(fd), fd=fd)
        os.close(fd)
        if wait_timeout_seconds > 0 and time.monotonic() < deadline:
            time.sleep(poll_interval_seconds)
            continue
        raise RuntimeError(f"Another codex-harness process is active: {path}")


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
        pass
    else:
        handle.path.unlink(missing_ok=True)
    finally:
        try:
            fcntl.flock(handle.fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(handle.fd)
