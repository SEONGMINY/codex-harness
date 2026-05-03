---
name: codex-harness
description: Run a Codex implementation harness for scoped product or internal tooling work. Use when the user invokes `$codex-harness`, asks to clarify requirements before implementation, wants a strict Clarify to Review to Context Gathering to Plan to Generate to Evaluate workflow, or wants phase-based Codex execution controlled by scripts instead of subagents or long chained sessions.
version: 0.1.0
---

# Codex Harness

## Overview

Use this skill to launch a separate codex-harness orchestration session. The parent chat should stay small: save the user's request, run `scripts/harness/start.py`, and report the launcher result.

The harness session turns an ambiguous implementation request into concise agent-facing docs, a reviewed scope decision, a reusable context-pack, and phase files that can be executed by `scripts/harness/run-phases.py`.

The harness does not chain long Codex conversations. It captures decisions as files, runs orchestration in a separate `codex exec` session, then runs each implementation phase in another fresh `codex exec` session while the runner owns status, retries, and failure decisions.

Harness `codex exec` calls use structured output schemas for launcher, phase, and evaluation final responses. Treat those final responses as summaries only. Runtime proof files and command results remain the source of truth.

When a phase fails a retryable check, the runner writes a repair packet under `context-pack/runtime/` and retries the same phase with that packet in context. The phase agent repairs only the listed failures; it does not decide the next phase.

If repository hooks are installed, `scripts/harness/run-phases.py` passes the active task, phase, and runtime contract through `CODEX_HARNESS_*` environment variables. Required hooks then use that contract to block obvious phase-scope violations and to continue Codex when required outputs are missing.

## Installation Check

Before starting the workflow, check whether the current repository has the matching harness version:

```bash
python3 - <<'PY'
import json
from pathlib import Path
root = Path(".")
required = [
    root / "codex-harness.json",
    root / "scripts" / "harness" / "skill" / "SKILL.md",
    root / "scripts" / "harness" / "start.py",
    root / "scripts" / "harness" / "run-phases.py",
]
missing = [str(path) for path in required if not path.exists()]
if missing:
    raise SystemExit("missing: " + ", ".join(missing))
manifest_version = json.loads((root / "codex-harness.json").read_text(encoding="utf-8")).get("version")
skill_text = (root / "scripts" / "harness" / "skill" / "SKILL.md").read_text(encoding="utf-8")
if manifest_version != "0.1.0" or "version: 0.1.0" not in skill_text:
    raise SystemExit(f"version mismatch: manifest={manifest_version}")
PY
```

If it is missing or stale, install the harness into the current repository first:

```bash
python3 ~/.codex/skills/codex-harness/assets/bootstrap-install.py . --all --force
```

Project install removes old `.agents/skills/codex-harness` copies. The project should use the global skill for invocation and `scripts/harness/skill/SKILL.md` for isolated harness sessions.

For one-time user-wide setup, install the skill and global no-op-unless-active hooks:

```bash
python3 ~/.codex/skills/codex-harness/assets/bootstrap-install.py . --all --force
```

User-level hooks must remain no-op unless `CODEX_HARNESS_ACTIVE=1`. Do not install hooks that affect ordinary Codex work outside `run-phases.py`.

## Launcher Mode

Default to this mode when the user invokes `$codex-harness` from an ordinary chat.

1. Ensure the harness is installed in the current repository.
2. Do not run Clarify, Review, Context Gathering, Plan, Generate, or Evaluate in the parent chat.
3. Pass the user's request to the launcher through stdin.
4. Run:

```bash
python3 scripts/harness/start.py --request-file - --full-auto <<'EOF'
<user request>
EOF
```

Add `--docs-approved`, `--run-phases`, or `--evaluate` only when the user explicitly requested that state.

After the command finishes, read only these launcher outputs:

- `.codex-harness/sessions/<run-id>/last-message.md`
- `.codex-harness/sessions/<run-id>/questions.md`, when present
- `.codex-harness/sessions/<run-id>/docs-approval-request.md`, when present
- `.codex-harness/sessions/<run-id>/launcher-result.json`

Report the status and next file path. Do not summarize the whole harness session unless the user asks.

## Harness Session Mode

Use this mode when the prompt or environment says this is an isolated harness session launched by `scripts/harness/start.py`.

Do not invoke `scripts/harness/start.py` from this mode.

## Workflow

1. Ensure the harness is installed in the current repository.
2. Read `references/workflow.md`, `references/review-gates.md`, `references/context-pack.md`, and `references/task-format.md`.
3. Clarify the request.
4. Review the request with the correct gate:
   - product feature gate for customer-facing features
   - internal tooling gate for automation and developer workflow tools
5. Ask for approval before writing Clarify docs.
6. After approval, create all mandatory docs, context-pack files, task indexes, and phase files.
7. Gather code and project context into the context-pack.
8. Plan work into self-contained task/phase files.
9. Validate the task with `scripts/harness/verify-task.py <task-dir>` and `scripts/harness/run-phases.py <task-dir> --dry-run`.
10. Run phases with `scripts/harness/run-phases.py`.
11. Evaluate from fresh context.

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
