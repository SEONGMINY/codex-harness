"""Artifact write helpers for harness runtime files."""

from __future__ import annotations

import errno
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, TextIO


class SymlinkPathError(RuntimeError):
    """Raised when a runner-owned artifact path crosses a symlink."""


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def ensure_no_symlink_path(path: Path) -> None:
    """Reject symlinks in runner-owned path components."""

    absolute_path = path if path.is_absolute() else Path.cwd() / path
    cwd = Path.cwd()
    boundary = cwd if _is_relative_to(absolute_path, cwd) else None

    current = absolute_path
    candidates: list[Path] = []
    while True:
        candidates.append(current)
        if boundary is not None and current == boundary:
            break
        if boundary is None and current.exists() and not current.is_symlink():
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    for candidate in reversed(candidates):
        try:
            if candidate.is_symlink():
                raise SymlinkPathError(f"runner-owned artifact path must not be a symlink: {candidate}")
        except OSError as exc:
            raise SymlinkPathError(
                f"runner-owned artifact path could not be checked for symlinks: {candidate}: {exc}"
            ) from exc


def ensure_artifact_parent(path: Path) -> None:
    ensure_no_symlink_path(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_no_symlink_path(path.parent)


def atomic_write_text(path: Path, content: str) -> None:
    ensure_no_symlink_path(path)
    ensure_artifact_parent(path)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        tmp_name = None
    finally:
        if tmp_name is not None:
            try:
                Path(tmp_name).unlink()
            except FileNotFoundError:
                pass


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


@contextmanager
def open_append_text(path: Path) -> Iterator[TextIO]:
    ensure_no_symlink_path(path)
    ensure_artifact_parent(path)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags | nofollow, 0o666)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise SymlinkPathError(f"runner-owned artifact path must not be a symlink: {path}") from exc
        raise
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        yield handle
