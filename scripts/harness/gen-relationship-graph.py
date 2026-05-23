#!/usr/bin/env python3
"""Generate a read-only relationship graph for a harness task."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from relationship_graph import graph_from_task, to_mermaid


def resolve_task_path(root: Path, task_arg: str) -> Path:
    candidate = Path(task_arg)
    if candidate.is_absolute() and candidate.is_dir():
        return candidate
    root_relative = root / candidate
    if root_relative.is_dir():
        return root_relative
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
    parser.add_argument(
        "--format",
        choices=["json", "mermaid"],
        default="json",
        help="Output format.",
    )
    parser.add_argument("--output", help="Write output to this file instead of stdout.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    task_path = resolve_task_path(root, args.task)
    graph = graph_from_task(root, task_path)
    if args.format == "mermaid":
        output = to_mermaid(graph)
    else:
        output = json.dumps(graph, ensure_ascii=False, indent=2) + "\n"

    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = root / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
