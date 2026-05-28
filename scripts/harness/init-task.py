#!/usr/bin/env python3
"""Create a harness task skeleton."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path


COMMON_DOC_TEMPLATES = {
    "runner-contract.md": """# Runner Contract

## State Ownership

- Runner scripts own task and phase status.
- Phase agents must not edit `tasks/*/index.json`.
- Runtime proof is required before a task can be considered complete.

## Runtime Proof

Completed phases require:

- `context-pack/runtime/phase<N>-prompt.md`
- `context-pack/runtime/phase<N>-contract.json`
- `context-pack/runtime/phase<N>-checklist.md`
- `context-pack/runtime/phase<N>-output-attempt<M>.jsonl`
- `context-pack/runtime/phase<N>-stderr-attempt<M>.txt`
- `context-pack/runtime/phase<N>-ac-attempt<M>.json`
- `context-pack/runtime/phase<N>-evidence.json`
- `context-pack/runtime/phase<N>-reconciliation.json`
- `context-pack/runtime/phase<N>-reconciliation.md`
- `context-pack/runtime/phase<N>-gate.json`
- `context-pack/runtime/phase<N>-result.json`
- `context-pack/handoffs/phase<N>.md`

The runner generates `phase<N>-result.json`.
The runner generates `phase<N>-gate.json`.
Phase agents only write handoffs and implementation changes.
Phase 0 also requires `context-pack/runtime/docs-diff.md`.
""",
    "testing.md": """# Harness Testing

## Principles

- Prefer executable commands over claims.
- Test runner-owned state transitions with temporary task directories.
- Keep tests standard-library only unless the target repository already provides a test stack.

## Required Evidence

- command
- exit code
- relevant stdout or stderr summary
- file outputs that prove the behavior
""",
    "document-scope.md": """# Document Scope

## Common Docs

Repository-level docs under `docs/harness/` describe reusable harness policy and runner contracts.

## Task Docs

Task-specific docs live under `tasks/<task-dir>/docs/`.

Use task docs for PRD, flow, data schema, architecture, and ADR for a single task.
""",
    "implementation-quality.md": """# Implementation Quality

## Purpose

Harness output should be simple, cohesive, and shaped by the target codebase.
Do not optimize for generic architecture. Optimize for the smallest design that satisfies the approved task and remains easy to change.

## Simplicity Rules

- Do not add abstractions before there is a concrete repeated responsibility.
- Do not create wrapper functions, helpers, mappers, managers, or handlers that only rename one call site.
- Keep one-off logic near the code that uses it unless it crosses a real boundary.
- Prefer existing project patterns over new local architecture.
- If a new layer, package, shared module, dependency, public interface, state management style, or cross-domain abstraction is needed, stop and record the missing decision instead of guessing.

## Responsibility Boundaries

Group code by lifecycle, change reason, and domain constraints.

- Keep objects and state that are created together and removed together in the same responsibility boundary.
- Keep objects that share domain constraints in the same responsibility boundary.
- Keep state that changes inside one domain transaction in the same responsibility boundary.
- Treat a transaction as one user action or domain event where state must change atomically.
- Split code when responsibilities have different lifecycles or different reasons to change.
- A module that creates a subscription, connection, timer, file handle, or similar resource owns cleanup for that resource.

## Architecture Rules

- Design starts with messages and responsibilities, not folders.
- A screen should send domain messages to hooks or domain modules instead of wiring internal setters.
- Dependencies must flow in one direction.
- Avoid cross-feature imports. Compose features at the app or page layer.
- Shared code may be imported by features and app code, but shared code must not import app or feature internals.
- Feature folders should contain only the folders they need. Do not create empty `api`, `components`, `hooks`, `types`, or `utils` folders just because a template lists them.
- Do not add barrel exports by default. Prefer direct imports unless the existing project already uses barrels consistently.

## UI Layer Roles

Layer names may vary by project, but roles should stay clear.

- Page or route layer: screen composition, providers, layout boundaries, suspense/error boundaries.
- Section layer: data loading, data shaping, empty-state routing, and wiring successful data into widgets.
- Widget layer: successful UI state and user interaction for a focused feature area.
- Item layer: repeated single item rendering.
- Utils: pure calculation or formatting without external library coupling.
- Lib: integration code for external libraries, SDKs, or framework adapters.

## TypeScript Rules

- Prefer `as const` value maps for status-like values.

```ts
export const recordingStatus = {
  idle: "idle",
  recording: "recording",
  paused: "paused",
} as const;

export type RecordingStatus =
  (typeof recordingStatus)[keyof typeof recordingStatus];
```

- Keep related types together; use `Pick` to reuse relevant fields instead of duplicating disconnected shapes.
- Prefer extension or composition when a type is a narrower form of another domain type.
- Use `interface` for component props.
- Apply these rules to TypeScript implementation broadly. Simple Node scripts and test utilities may use simpler local types when that is clearer.

## React Rules

- Do not add `useCallback`, `useMemo`, or `memo` by default.
- Use memoization only when there is a concrete render stability requirement, expensive calculation, or external API contract that needs stable identity.
- Keep component props focused on domain data and user actions, not internal state setters from other modules.
- Hooks with setup and cleanup responsibilities should expose messages such as `start`, `stop`, `send`, or `change`, not a bag of setters for the caller to orchestrate.

## Mapper And Utility Rules

- Create a mapper only for a real boundary: external API response, persistence schema, native bridge, wire protocol, or third-party library options.
- Do not create a mapper only to rename fields for one caller.
- Do not create generic validation helpers unless multiple call sites share the same validation rule.
- Prefer straightforward parsing near the boundary over a tree of tiny predicates when the boundary is small and local.

## Testing Rules

- Tests should read as requirements, not implementation copies.
- Prefer given, when, then structure.
- Test pure logic first.
- Render components only when user interaction or visible UI behavior is the point.
- Avoid tests that only assert mock calls, private implementation details, or pass-through glue code.
- Use test names that express condition and result, such as `같은 값을 다시 선택하면 > 선택이 해제된다.`
- Bugfix and validation phases should include reproduction evidence. If a reproducible test or command is not possible, record the fallback reason and alternative evidence in the phase contract.

## Surgical Change Rules

- Every changed repository file must trace to a phase instruction id in the phase handoff.
- Do not change adjacent code, formatting, comments, or docs unless the phase contract asks for it.
- Remove only unused code created by the current phase. Report pre-existing dead code instead of deleting it.

## References

- Bulletproof React project structure: https://github.com/alan2207/bulletproof-react/blob/master/docs/project-structure.md
- 우아한 객체지향 정리: https://velog.io/@codemcd/우아한테크세미나-우아한객체지향-의존성을-이용해-설계-진화시키기-By-우아한형제들-개발실장-조영호님-vkk5brh7by
- 우아한 객체지향 세미나 영상: https://www.youtube.com/watch?v=dJ5C4qRqAgA
""",
}

DOC_TEMPLATES = {
    "prd.md": """# PRD

## Problem

TODO: Define the concrete user or operator problem.

## Goal

TODO: Define the smallest valuable outcome.

## Non-Goals

TODO: List what this task will not build.

## Completion Criteria

TODO: List observable completion criteria.
""",
    "flow.md": """# Flow

## Primary Flow

TODO: Describe the user or operator flow.

## Edge Cases

TODO: List meaningful edge cases.
""",
    "data-schema.md": """# Data Schema

## Data Model

TODO: Describe data structures, files, or persistence.

## Compatibility

TODO: Describe migration or compatibility constraints.
""",
    "code-architecture.md": """# Code Architecture

## Relevant Files

TODO: List files and responsibilities.

## Design

TODO: Describe the implementation shape and boundaries.
""",
    "adr.md": """# ADR

## Decision

TODO: Record the accepted technical decision.

## Rationale

TODO: Explain why this decision is better than alternatives.

## Rejected Options

TODO: List rejected options and reasons.
""",
    "implementation-design-review.md": """# Implementation Design Review

## Scope Summary

TODO: Summarize the implementation scope that needs approval.

## Layer Plan

TODO: Describe layer boundaries and responsibilities.

## Object/Module Dependency

TODO: Describe object, module, hook, component, API, DB, storage, and external dependency directions.

## Public Interfaces

TODO: List signature-level public interfaces.

## API Contract

TODO: Define request, response, event, or boundary contracts, or state that none are changed.

## DB/Storage Schema

TODO: Define schema changes, persistence shape, migrations, or state that none are changed.

## State And Lifecycle

TODO: Describe state ownership, creation, update, cleanup, and lifecycle boundaries.

## Transaction Boundaries

TODO: Describe user actions or domain events that change state atomically.

## Files To Add/Change

TODO: List files to add, change, or leave untouched.
Use repository-relative paths or path patterns. Implementation phase `scope.allowed_paths` and `required_repo_outputs` must stay inside these approved paths.

## Mermaid Diagrams

TODO: Include at least one Mermaid block using flowchart, sequenceDiagram, or stateDiagram-v2 when implementation design review is required.

## Open Decisions

TODO: List unresolved decisions or state that none remain.

## Approval Checklist

TODO: List exactly what is being approved before implementation.
""",
}

STATIC_TEMPLATES = {
    "product.md": "# Product Context\n\nTODO: Summarize the approved product or tooling intent.\n",
    "decisions.md": "# Decisions\n\nTODO: List final decisions that guide implementation.\n",
    "rejected-options.md": "# Rejected Options\n\nTODO: List options rejected during Clarify and why.\n",
    "constraints.md": "# Constraints\n\nTODO: List hard constraints and non-negotiables.\n",
    "test-policy.md": "# Test Policy\n\nTODO: Describe the test strategy and required commands.\n",
    "clarify-review.md": "# Clarify Review\n\nTODO: Paste the final review gate result.\n",
    "docs-approval.md": "# Docs Approval\n\nTODO: Record who approved docs creation and when.\n",
    "context-gathering.md": """# Context Gathering

## Relevant Files

TODO: List relevant files and why they matter.

## Relevant Commands

TODO: List commands used to inspect or validate the repo.

## Examples To Follow

TODO: List local examples and patterns.

## Risks

TODO: List implementation risks.

## Ignored Context

TODO: List intentionally ignored files or areas and why.
""",
}

STATIC_JSON_TEMPLATES = {
    "decisions.json": {
        "decisions": []
    },
    "open-decisions.json": {
        "decisions": [
            {
                "id": "OD-001",
                "question": "Approve implementation-shaping decisions before Plan.",
                "blocking_stage": "plan",
                "status": "open",
            }
        ]
    },
    "architecture.json": {
        "nodes": [],
        "allowed_edges": [],
        "decisions": [],
        "forbid_cycles": True,
    },
    "dependency-policy.json": {
        "new_dependencies": "forbidden",
        "approved_new_dependencies": [],
        "approved_dependency_manifest_changes": [],
    },
    "context-gathering-budget.json": {
        "search_batches": 2,
        "max_files_to_read": 12,
        "stop_when": [
            "target files are known",
            "architecture boundary is known",
            "test command is known",
        ],
        "escalate_when": [
            "signals conflict",
            "scope boundary is unclear",
        ],
    },
}


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


def write_text_if_missing(path: Path, content: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def docs_index(task_dir: str, common_docs: list[str], docs: list[str]) -> str:
    lines = ["# Docs Index", ""]
    lines.append("## Common Docs")
    lines.append("")
    for doc in common_docs:
        lines.append(f"- `{doc}`")
    lines.append("")
    lines.append("## Task Docs")
    lines.append("")
    for doc in docs:
        lines.append(f"- `{doc}`")
    lines.append("")
    lines.append("Keep these docs aligned with phase files and implementation.")
    lines.append("")
    return "\n".join(lines)


def phase_template(
    phase: int,
    name: str,
    common_docs: list[str],
    docs: list[str],
) -> str:
    common_doc_lines = "\n".join(f"- `{doc}`" for doc in common_docs)
    doc_lines = "\n".join(f"- `{doc}`" for doc in docs)
    previous_outputs = []
    if phase > 0:
        previous = phase - 1
        previous_outputs = [
            f"context-pack/runtime/phase{previous}-reconciliation.md",
            f"context-pack/runtime/phase{previous}-gate.json",
            f"context-pack/handoffs/phase{previous}.md",
        ]
    contract = {
        "phase": phase,
        "name": name,
        "read_first": {
            "docs": [
                *common_docs,
                *docs,
                "context-pack/static/original-prompt.md",
                "context-pack/static/product.md",
                "context-pack/static/decisions.md",
                "context-pack/static/decisions.json",
                "context-pack/static/open-decisions.json",
                "context-pack/static/architecture.json",
                "context-pack/static/dependency-policy.json",
                "context-pack/static/context-gathering-budget.json",
                "context-pack/static/rejected-options.md",
                "context-pack/static/constraints.md",
                "context-pack/static/context-gathering.md",
            ],
            "previous_outputs": previous_outputs,
        },
        "scope": {
            "layer": "TODO",
            "allowed_paths": [],
        },
        "interfaces": [],
        "decision_refs": [],
        "architecture_refs": [],
        "dependency_policy": {
            "new_dependencies": "forbidden",
            "approved_new_dependencies": [],
            "approved_dependency_manifest_changes": [],
        },
        "instructions": [
            {
                "id": f"P{phase}-001",
                "task": "TODO: Describe one concrete task.",
                "expected_evidence": [
                    "TODO: Describe observable evidence for this instruction."
                ],
            }
        ],
        "success_criteria": [
            "TODO: Describe the observable phase outcome."
        ],
        "stop_rules": [
            "Stop and report blocked if required context is missing.",
            "Stop and report blocked if the work requires edits outside allowed_paths.",
        ],
        "fallback_behavior": {
            "if_blocked": "Write the blocker and missing decision to the phase handoff.",
            "if_tests_fail": "Fix failures inside the phase scope before reporting.",
        },
        "validation_budget": {
            "max_attempts": 2,
            "command_timeout_seconds": 600,
        },
        "missing_evidence_behavior": "Treat missing expected evidence as unresolved until command output or required files prove it.",
        "command_expectations": [],
        "acceptance_commands": [
            "TODO"
        ],
        "required_outputs": [
            f"context-pack/handoffs/phase{phase}.md"
        ],
        "forbidden": [
            {
                "rule": "Do not update `tasks/*/index.json`.",
                "reason": "The runner owns task and phase status.",
            },
            {
                "rule": f"Do not write `context-pack/runtime/phase{phase}-result.json`.",
                "reason": "The runner owns phase result proof.",
            },
            {
                "rule": "Do not spawn subagents for implementation.",
                "reason": "Generate phases must run in one fresh Codex session.",
            },
        ],
    }
    contract_json = json.dumps(contract, ensure_ascii=False, indent=2)
    return f"""# Phase {phase}: {name}

## Purpose

TODO: Describe the single outcome for this phase.

## Contract

```json
{contract_json}
```

## Read First

{common_doc_lines}
{doc_lines}
- `context-pack/static/original-prompt.md`
- `context-pack/static/product.md`
- `context-pack/static/decisions.md`
- `context-pack/static/rejected-options.md`
- `context-pack/static/constraints.md`
- `context-pack/static/context-gathering.md`

## Work

TODO: Add specific implementation instructions.

## Acceptance Criteria

The runner uses `acceptance_commands` from the Contract block.

## Required Outputs

The runner uses `required_outputs` from the Contract block.

## Constraints

- Do not update `tasks/*/index.json`; the runner owns status.
- Do not write `context-pack/runtime/phase{phase}-result.json`; the runner generates it.
- Do not spawn subagents for implementation.
- Do not expand scope beyond this phase.
- In `context-pack/handoffs/phase{phase}.md`, include `## Change Trace` and map every changed repository file to one or more instruction ids.
- Follow `docs/harness/implementation-quality.md` when implementing code.
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
        "--evaluation-command",
        action="append",
        default=[],
        help="Evaluation command. Repeat for each command.",
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
    common_docs_path = root / "docs" / "harness"
    docs_path = task_path / "docs"

    for directory in [
        phases_path,
        context_path / "static",
        context_path / "runtime",
        context_path / "handoffs",
        common_docs_path,
        docs_path,
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    common_docs = []
    for filename, template in COMMON_DOC_TEMPLATES.items():
        target = common_docs_path / filename
        write_text_if_missing(target, template)
        common_docs.append(str(target.relative_to(root)))

    docs = []
    for filename, template in DOC_TEMPLATES.items():
        target = docs_path / filename
        write_text_if_missing(target, template)
        docs.append(str(target.relative_to(root)))

    (context_path / "static" / "original-prompt.md").write_text(
        prompt.rstrip() + "\n",
        encoding="utf-8",
    )
    for filename, template in STATIC_TEMPLATES.items():
        write_text_if_missing(context_path / "static" / filename, template)
    for filename, template in STATIC_JSON_TEMPLATES.items():
        target = context_path / "static" / filename
        if not target.exists():
            write_json(target, template)
    write_text_if_missing(
        context_path / "static" / "docs-index.md",
        docs_index(task_dir, common_docs, docs),
    )

    phase_entries = []
    for phase_number, raw_name in enumerate(args.phase):
        phase_name = slugify(raw_name)
        (phases_path / f"phase{phase_number}.md").write_text(
            phase_template(phase_number, phase_name, common_docs, docs),
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
        "common_docs": common_docs,
        "docs": docs,
        "evaluation_commands": args.evaluation_command,
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
