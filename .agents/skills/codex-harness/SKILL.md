---
name: codex-harness
description: Run a Codex implementation harness for scoped product or internal tooling work. Use when the user invokes `$codex-harness`, asks to clarify requirements before implementation, wants a strict Clarify to Review to Context Gathering to Plan to Generate to Evaluate workflow, or wants phase-based Codex execution controlled by scripts instead of subagents or long chained sessions.
---

# Codex Harness

## Overview

Use this skill to turn an ambiguous implementation request into concise agent-facing docs, a reviewed scope decision, a reusable context-pack, and phase files that can be executed by `scripts/harness/run-phases.py`.

The harness does not chain long Codex conversations. It captures decisions as files, then runs each phase in a fresh `codex exec` session while the runner owns status, retries, and failure decisions.

When a phase fails a retryable check, the runner writes a repair packet under `context-pack/runtime/` and retries the same phase with that packet in context. The phase agent repairs only the listed failures; it does not decide the next phase.

If repository hooks are installed, `scripts/harness/run-phases.py` passes the active task, phase, and runtime contract through `CODEX_HARNESS_*` environment variables. Required hooks then use that contract to block obvious phase-scope violations and to continue Codex when required outputs are missing.

## Workflow

1. Read `references/workflow.md`, `references/review-gates.md`, `references/context-pack.md`, and `references/task-format.md`.
2. Clarify the request.
3. Review the request with the correct gate:
   - product feature gate for customer-facing features
   - internal tooling gate for automation and developer workflow tools
4. Ask for approval before writing Clarify docs.
5. After approval, create all mandatory docs, context-pack files, task indexes, and phase files.
6. Gather code and project context into the context-pack.
7. Plan work into self-contained task/phase files.
8. Validate the task with `scripts/harness/verify-task.py <task-dir>` and `scripts/harness/run-phases.py <task-dir> --dry-run`.
9. Run phases with `scripts/harness/run-phases.py`.
10. Evaluate from fresh context.

## Hard Rules

- Do not create Clarify docs until the user explicitly approves.
- Do not flatter the proposal. Challenge weak evidence, unclear value, vague urgency, and bloated scope.
- Do not use subagents for Generate phases.
- Do not implement Generate work directly in the orchestrator session.
- Generate means running `scripts/harness/run-phases.py`; direct edits are only allowed while acting as a phase agent launched by the runner.
- Do not let phase agents update task status.
- Let the runner decide phase success, retry, failure, and next phase.
- Treat conversation as source material, not execution state.
- Store durable decisions in files under the task context-pack.
- Do not stop after approval until mandatory docs, context-pack files, task indexes, and phase files exist.
- Do not run Generate when phase files still contain placeholders or missing AC commands.
- Do not manually mark phases or tasks completed.
- Do not manually create runner-owned runtime proof files.
- Do not claim Generate or Evaluate is complete unless the required runtime proof exists.
- Do not bypass installed codex-harness hooks. If a hook blocks a tool call, fix the phase work or contract instead of weakening the hook.

## Stop Conditions

- During Clarify, stop only to ask targeted questions or to present Clarify Review.
- After Clarify Review passes, stop and ask the user to approve docs creation.
- After the user approves docs creation, do not stop until these exist:
  - `docs/harness/runner-contract.md`
  - `docs/harness/testing.md`
  - `docs/harness/document-scope.md`
  - `tasks/<task-dir>/docs/prd.md`
  - `tasks/<task-dir>/docs/flow.md`
  - `tasks/<task-dir>/docs/data-schema.md`
  - `tasks/<task-dir>/docs/code-architecture.md`
  - `tasks/<task-dir>/docs/adr.md`
  - `tasks/index.json`
  - `tasks/<task-dir>/index.json`
  - `tasks/<task-dir>/context-pack/static/*`
  - `tasks/<task-dir>/phases/phase<N>.md`
- After Plan, run `python3 scripts/harness/verify-task.py <task-dir>` and `python3 scripts/harness/run-phases.py <task-dir> --dry-run`. Fix failures before stopping.
- After Generate, verify runtime proof before stopping.
- After Generate, run `python3 scripts/harness/evaluate-task.py <task-dir>` with the task's evaluation commands unless the user explicitly asks not to.

## Runtime Proof

Generate is not complete unless these files exist:

- `tasks/<task-dir>/context-pack/runtime/phase<N>-prompt.md` for every executed phase
- `tasks/<task-dir>/context-pack/runtime/phase<N>-contract.json` for every executed phase
- `tasks/<task-dir>/context-pack/runtime/phase<N>-checklist.md` for every executed phase
- `tasks/<task-dir>/context-pack/runtime/phase<N>-output-attempt<M>.jsonl` for every executed phase
- `tasks/<task-dir>/context-pack/runtime/phase<N>-stderr-attempt<M>.txt` for every executed phase
- `tasks/<task-dir>/context-pack/runtime/phase<N>-ac-attempt<M>.json` for every executed phase
- `tasks/<task-dir>/context-pack/runtime/phase<N>-evidence.json` for every executed phase
- `tasks/<task-dir>/context-pack/runtime/phase<N>-reconciliation.json` for every executed phase
- `tasks/<task-dir>/context-pack/runtime/phase<N>-reconciliation.md` for every executed phase
- `tasks/<task-dir>/context-pack/runtime/phase<N>-gate.json` for every executed phase
- `tasks/<task-dir>/context-pack/runtime/phase<N>-result.json` for every completed phase
- `tasks/<task-dir>/context-pack/runtime/phase<N>-repair-packet.json` and `.md` for failed/retried attempts, when present
- `tasks/<task-dir>/context-pack/runtime/docs-diff.md` after phase 0
- `tasks/<task-dir>/context-pack/handoffs/phase<N>.md` for every completed phase

`phase<N>-result.json` is runner-owned. It contains measured facts: exit codes, changed files, required output status, and artifact paths. Phase agents write handoffs, not result JSON.
`phase<N>-gate.json` is runner-owned. It must pass before the phase can be marked completed.
`phase<N>-repair-packet.*` is runner-owned. It summarizes retryable failures for the next attempt.

Evaluate is not complete unless these files exist:

- `tasks/<task-dir>/context-pack/runtime/evaluation-command-results.json`
- `tasks/<task-dir>/context-pack/runtime/evaluation-prompt.md`
- `tasks/<task-dir>/context-pack/runtime/evaluation-output.jsonl`

If runtime proof is missing, report the task as blocked or failed. Do not infer success from handoffs or status JSON alone.

Before final reporting, run:

```bash
python3 scripts/harness/verify-task.py <task-dir> --require-evaluation
find tasks/<task-dir>/context-pack/runtime -maxdepth 1 -type f | sort
find tasks/<task-dir>/context-pack/handoffs -maxdepth 1 -type f | sort
```

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
python3 scripts/harness/verify-task.py <task-dir>
python3 scripts/harness/run-phases.py <task-dir> --dry-run
```

Run pending phases:

```bash
python3 scripts/harness/run-phases.py <task-dir> --full-auto --evaluate
```

Evaluate from fresh context:

```bash
python3 scripts/harness/evaluate-task.py <task-dir> --command "npm test" --full-auto
```
