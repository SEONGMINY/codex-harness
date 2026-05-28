"""Task path resolution helpers for harness entrypoints."""

from __future__ import annotations

from pathlib import Path


def is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def resolve_task_path(root: Path, task_arg: str) -> Path:
    value = task_arg.strip()
    if not value:
        raise FileNotFoundError("Task directory not found: empty task path")

    root = root.resolve()
    tasks_root = (root / "tasks").resolve()
    raw_path = Path(value)
    if raw_path.is_absolute():
        candidate = raw_path
    elif raw_path.parts and raw_path.parts[0] == "tasks":
        candidate = root / raw_path
    else:
        candidate = tasks_root / raw_path

    resolved = candidate.resolve()
    if not is_relative_to(resolved, tasks_root):
        raise ValueError(f"Task directory must be under {tasks_root}: {task_arg}")
    if resolved.is_dir():
        return resolved
    raise FileNotFoundError(f"Task directory not found: {task_arg}")
