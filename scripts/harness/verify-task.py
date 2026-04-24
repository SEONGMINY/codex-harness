#!/usr/bin/env python3
"""Verify harness task artifacts and runtime proof."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


MANDATORY_STATIC_FILES = [
    "original-prompt.md",
    "product.md",
    "decisions.md",
    "rejected-options.md",
    "constraints.md",
    "test-policy.md",
    "clarify-review.md",
    "docs-approval.md",
    "context-gathering.md",
    "docs-index.md",
]
MANDATORY_TASK_DOCS = [
    "prd.md",
    "flow.md",
    "data-schema.md",
    "code-architecture.md",
    "adr.md",
]
PLACEHOLDER_PATTERNS = [
    re.compile(r"^\s*TODO\b", re.MULTILINE),
    re.compile(r"\[TODO", re.IGNORECASE),
    re.compile(r"PLACEHOLDER", re.IGNORECASE),
]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def has_placeholder(text: str) -> bool:
    return any(pattern.search(text) for pattern in PLACEHOLDER_PATTERNS)


def rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def require_file(
    root: Path,
    path: Path,
    label: str,
    check_placeholder: bool = True,
    allow_empty: bool = False,
) -> list[str]:
    if not path.exists():
        return [f"Missing {label}: {rel(root, path)}"]
    if not path.is_file():
        return [f"Not a file: {rel(root, path)}"]
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    errors = []
    if not text and not allow_empty:
        errors.append(f"Empty {label}: {rel(root, path)}")
    if check_placeholder and has_placeholder(text):
        errors.append(f"Placeholder remains in {label}: {rel(root, path)}")
    return errors


def phase_ac_commands(markdown: str) -> list[str]:
    match = re.search(
        r"## Acceptance Criteria(?P<body>.*?)(?:\n## |\Z)",
        markdown,
        flags=re.DOTALL,
    )
    if not match:
        return []
    commands: list[str] = []
    for block in re.findall(r"```(?:bash|sh|shell)?\n(.*?)```", match.group("body"), re.DOTALL):
        for line in block.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and stripped != "TODO":
                commands.append(stripped)
    return commands


def phase_attempts(phase: dict) -> list[int]:
    attempts = phase.get("attempts")
    if isinstance(attempts, int) and attempts > 0:
        return [attempts]
    return [1]


def verify(root: Path, task_path: Path, require_evaluation: bool) -> list[str]:
    errors: list[str] = []
    task_index_path = task_path / "index.json"
    errors.extend(require_file(root, task_index_path, "task index", check_placeholder=False))
    if errors:
        return errors

    task_index = read_json(task_index_path)
    task_dir = task_path.name

    common_docs = [root / raw for raw in task_index.get("common_docs") or []]
    if not common_docs:
        errors.append("Task index must list common_docs.")
    for path in common_docs:
        errors.extend(require_file(root, path, "common doc"))

    task_docs = [root / raw for raw in task_index.get("docs") or []]
    expected_task_doc_dir = task_path / "docs"
    if len(task_docs) < len(MANDATORY_TASK_DOCS):
        errors.append("Task index must list mandatory task docs.")
    for filename in MANDATORY_TASK_DOCS:
        expected = expected_task_doc_dir / filename
        errors.extend(require_file(root, expected, "task doc"))
        if expected not in task_docs:
            errors.append(f"Task index docs must include {rel(root, expected)}")
    for path in task_docs:
        if not str(path).startswith(str(expected_task_doc_dir)):
            errors.append(f"Task-specific doc must live under {rel(root, expected_task_doc_dir)}: {rel(root, path)}")
        errors.extend(require_file(root, path, "task doc"))

    static_dir = task_path / "context-pack" / "static"
    for filename in MANDATORY_STATIC_FILES:
        errors.extend(require_file(root, static_dir / filename, "static context"))

    phase_count = int(task_index.get("totalPhases") or len(task_index.get("phases") or []))
    phases = task_index.get("phases") or []
    if phase_count != len(phases):
        errors.append("totalPhases must match phases length.")

    runtime_dir = task_path / "context-pack" / "runtime"
    handoff_dir = task_path / "context-pack" / "handoffs"
    for phase in phases:
        phase_number = int(phase["phase"])
        phase_path = task_path / "phases" / f"phase{phase_number}.md"
        errors.extend(require_file(root, phase_path, "phase file"))
        if phase_path.exists():
            markdown = phase_path.read_text(encoding="utf-8", errors="replace")
            if not phase_ac_commands(markdown) and not phase.get("ac_commands"):
                errors.append(f"Missing AC commands for phase {phase_number}.")

        if phase.get("status") == "completed":
            errors.extend(require_file(root, handoff_dir / f"phase{phase_number}.md", "handoff"))
            errors.extend(require_file(root, runtime_dir / f"phase{phase_number}-prompt.md", "runtime prompt"))
            for attempt in phase_attempts(phase):
                errors.extend(
                    require_file(
                        root,
                        runtime_dir / f"phase{phase_number}-output-attempt{attempt}.jsonl",
                        "runtime output",
                        check_placeholder=False,
                    )
                )
                errors.extend(
                    require_file(
                        root,
                        runtime_dir / f"phase{phase_number}-stderr-attempt{attempt}.txt",
                        "runtime stderr",
                        check_placeholder=False,
                        allow_empty=True,
                    )
                )
            if phase_number == 0:
                errors.extend(require_file(root, runtime_dir / "docs-diff.md", "docs diff", check_placeholder=False))

    if require_evaluation:
        errors.extend(
            require_file(root, runtime_dir / "evaluation-command-results.json", "evaluation command results", False)
        )
        errors.extend(require_file(root, runtime_dir / "evaluation-prompt.md", "evaluation prompt"))
        errors.extend(require_file(root, runtime_dir / "evaluation-output.jsonl", "evaluation output", False))

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", help="Task directory name or path.")
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument("--require-evaluation", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    task_path = resolve_task_path(root, args.task)
    errors = verify(root, task_path, args.require_evaluation)
    if errors:
        print("Task verification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Task verification passed: {task_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
