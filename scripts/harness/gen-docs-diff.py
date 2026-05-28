#!/usr/bin/env python3
"""Generate a docs diff artifact for a harness task."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from artifact_io import atomic_write_text
from task_paths import resolve_task_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", help="Task directory name or path.")
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument("--baseline", required=True, help="Git revision to diff from.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    task_path = resolve_task_path(root, args.task)
    output_path = task_path / "context-pack" / "runtime" / "docs-diff.md"

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

    atomic_write_text(
        output_path,
        f"# docs-diff: {task_path.name}\n\n"
        f"Baseline: `{args.baseline}`\n\n"
        "```diff\n"
        f"{diff}\n"
        "```\n",
    )
    print(output_path)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
