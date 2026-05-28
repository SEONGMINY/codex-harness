#!/usr/bin/env python3
"""Generate a read-only relationship graph for a harness task."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from artifact_io import atomic_write_text
from relationship_graph import graph_from_task, to_mermaid
from task_paths import resolve_task_path


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
        atomic_write_text(output_path, output)
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
