#!/usr/bin/env python3
"""Create a harness task skeleton."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "task"


def read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def phase_template(phase: int, name: str) -> str:
    return f"""# Phase {phase}: {name}

## Purpose

TODO: Describe the single outcome for this phase.

## Read First

- `context-pack/static/original-prompt.md`
- `context-pack/static/decisions.md`
- `context-pack/static/constraints.md`

## Work

TODO: Add specific implementation instructions.

## Acceptance Criteria

```bash
TODO
```

## Required Outputs

- `context-pack/handoffs/phase{phase}.md`

## Constraints

- Do not update `tasks/*/index.json`; the runner owns status.
- Do not spawn subagents for implementation.
- Do not expand scope beyond this phase.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="Task name. It is normalized to kebab-case.")
    parser.add_argument("--project", required=True, help="Project name.")
    parser.add_argument("--prompt-file", help="File containing the original request.")
    parser.add_argument("--prompt", help="Original request text.")
    parser.add_argument(
        "--phase",
        action="append",
        required=True,
        help="Phase slug. Repeat for each phase, in order.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root. Defaults to current directory.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    tasks_root = root / "tasks"
    tasks_root.mkdir(parents=True, exist_ok=True)

    prompt = args.prompt or ""
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8")

    top_index_path = tasks_root / "index.json"
    top_index = read_json(top_index_path, {"tasks": []})
    next_id = max((int(task["id"]) for task in top_index["tasks"]), default=-1) + 1

    task_name = slugify(args.name)
    task_dir = f"{next_id}-{task_name}"
    task_path = tasks_root / task_dir
    phases_path = task_path / "phases"
    context_path = task_path / "context-pack"

    for directory in [
        phases_path,
        context_path / "static",
        context_path / "runtime",
        context_path / "handoffs",
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    (context_path / "static" / "original-prompt.md").write_text(
        prompt.rstrip() + "\n",
        encoding="utf-8",
    )
    for filename, title in [
        ("decisions.md", "Decisions"),
        ("rejected-options.md", "Rejected Options"),
        ("constraints.md", "Constraints"),
        ("test-policy.md", "Test Policy"),
    ]:
        target = context_path / "static" / filename
        if not target.exists():
            target.write_text(f"# {title}\n\nTODO\n", encoding="utf-8")

    phase_entries = []
    for phase_number, raw_name in enumerate(args.phase):
        phase_name = slugify(raw_name)
        (phases_path / f"phase{phase_number}.md").write_text(
            phase_template(phase_number, phase_name),
            encoding="utf-8",
        )
        phase_entries.append(
            {
                "phase": phase_number,
                "name": phase_name,
                "status": "pending",
                "ac_commands": [],
                "required_outputs": [
                    f"context-pack/handoffs/phase{phase_number}.md"
                ],
            }
        )

    task_index = {
        "project": args.project,
        "task": task_name,
        "prompt": prompt,
        "baseline": git_head(root),
        "created_at": now(),
        "totalPhases": len(phase_entries),
        "phases": phase_entries,
    }
    write_json(task_path / "index.json", task_index)

    top_index["tasks"].append(
        {
            "id": next_id,
            "name": task_name,
            "dir": task_dir,
            "status": "pending",
            "created_at": task_index["created_at"],
        }
    )
    write_json(top_index_path, top_index)

    print(task_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
