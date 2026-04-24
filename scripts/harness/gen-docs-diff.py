#!/usr/bin/env python3
"""Generate a docs diff artifact for a harness task."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def resolve_task_path(root: Path, task_arg: str) -> Path:
    candidate = Path(task_arg)
    if candidate.is_absolute() and candidate.is_dir():
        return candidate
    if candidate.is_dir():
        return candidate.resolve()
    task_path = root / "tasks" / task_arg
    if task_path.is_dir():
        return task_path
    raise FileNotFoundError(f"Task directory not found: {task_arg}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", help="Task directory name or path.")
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument("--baseline", required=True, help="Git revision to diff from.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    task_path = resolve_task_path(root, args.task)
    output_path = task_path / "context-pack" / "runtime" / "docs-diff.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ["git", "diff", args.baseline, "--", "docs/", str((task_path / "docs").relative_to(root))],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    diff = result.stdout.strip()
    if not diff:
        diff = "(no docs diff)"

    output_path.write_text(
        f"# docs-diff: {task_path.name}\n\n"
        f"Baseline: `{args.baseline}`\n\n"
        "```diff\n"
        f"{diff}\n"
        "```\n",
        encoding="utf-8",
    )
    print(output_path)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
