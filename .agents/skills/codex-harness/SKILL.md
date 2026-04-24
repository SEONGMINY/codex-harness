---
name: codex-harness
description: Run a Codex implementation harness for scoped product or internal tooling work. Use when the user invokes `$codex-harness`, asks to clarify requirements before implementation, wants a strict Clarify to Review to Context Gathering to Plan to Generate to Evaluate workflow, or wants phase-based Codex execution controlled by scripts instead of subagents or long chained sessions.
---

# Codex Harness

## Overview

Use this skill to turn an ambiguous implementation request into concise agent-facing docs, a reviewed scope decision, a reusable context-pack, and phase files that can be executed by `scripts/harness/run-phases.py`.

The harness does not chain long Codex conversations. It captures decisions as files, then runs each phase in a fresh `codex exec` session while the runner owns status, retries, and failure decisions.

## Workflow

1. Clarify the request.
2. Review the request with the correct gate:
   - product feature gate for customer-facing features
   - internal tooling gate for automation and developer workflow tools
3. Ask for approval before writing Clarify docs.
4. Create concise docs and `context-pack/static/*`.
5. Gather code and project context.
6. Plan work into task/phase files.
7. Run phases with `scripts/harness/run-phases.py`.
8. Evaluate from fresh context.

## Hard Rules

- Do not create Clarify docs until the user explicitly approves.
- Do not flatter the proposal. Challenge weak evidence, unclear value, vague urgency, and bloated scope.
- Do not use subagents for Generate phases.
- Do not let phase agents update task status.
- Let the runner decide phase success, retry, failure, and next phase.
- Treat conversation as source material, not execution state.
- Store durable decisions in files under the task context-pack.

## References

- Read `references/workflow.md` for the full stage contract.
- Read `references/review-gates.md` before approving or rejecting scope.
- Read `references/context-pack.md` before creating task context.
- Read `references/task-format.md` before creating `tasks/*`.
- Read `references/testing.md` before writing or reviewing tests.

## Runner Commands

Create a task skeleton after Clarify, Review, docs approval, Context Gathering, and Plan:

```bash
python3 scripts/harness/init-task.py <task-name> \
  --project "<project-name>" \
  --prompt-file <prompt-file> \
  --phase docs \
  --phase implementation \
  --phase tests
```

Build the next phase prompt without running Codex:

```bash
python3 scripts/harness/run-phases.py <task-dir> --dry-run
```

Run pending phases:

```bash
python3 scripts/harness/run-phases.py <task-dir> --full-auto
```

Evaluate from fresh context:

```bash
python3 scripts/harness/evaluate-task.py <task-dir> --command "npm test" --full-auto
```
