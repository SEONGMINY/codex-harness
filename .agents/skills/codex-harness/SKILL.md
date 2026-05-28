---
name: codex-harness
description: Run a Codex implementation harness for scoped product or internal tooling work. Use when the user invokes `$codex-harness`, asks to clarify requirements before implementation, wants a strict Clarify to Review to Context Gathering to Plan to Generate to Evaluate workflow, or wants phase-based Codex execution controlled by scripts instead of subagents or long chained sessions.
version: 0.1.4
---

# Codex Harness

## Overview

Use this skill to launch a separate codex-harness orchestration session. The parent chat should stay small: save the user's request, run `.codex/harness/scripts/start.py`, and report the launcher result.

The harness session moves a request to exactly one durable state: `questions_needed`, `docs_approval_needed`, `design_approval_needed`, `planned`, `generated`, or `blocked`.

Each state must be backed by files. Do not rely on a long final explanation.

Clarify is a decision gate. Implementation-shaping decisions such as architecture, data model, public interface, module boundary, dependency changes, technology stack, and user-visible behavior must be approved before Plan. If a decision is unclear, write a targeted question or an open decision instead of guessing.

The harness does not chain long Codex conversations. It captures decisions as files, runs planning orchestration in a separate `codex exec` session, then the launcher process calls the runner, and each implementation phase runs in another fresh `codex exec` session while the runner owns status, retries, and failure decisions.

Harness `codex exec` calls use structured output schemas for launcher, phase, and evaluation final responses. Treat those final responses as summaries only. Runtime proof files and command results remain the source of truth.

When a task reaches a valid `planned` or `generated` state, the launcher or runner automatically writes a read-only relationship graph under `tasks/<task-dir>/context-pack/runtime/relationship-graph.json` and `.mmd`. This graph is derived from task artifacts only; it is not a new source of truth. If graph generation fails, treat `relationship-graph-warning.json` as a non-blocking warning unless `verify-task.py` or runner proof reports a real source artifact error.

When a phase fails a retryable check, the runner writes a repair packet under `context-pack/runtime/` and retries the same phase with that packet in context. The phase agent repairs only the listed failures; it does not decide the next phase.

If a repair packet lists `contaminating_changes`, the runner observed changes outside `scope.allowed_paths` for that attempt. Treat this as cleanup-required: review or clean those paths, or fix the phase contract scope, before resuming. Do not auto-retry the same phase against a contaminated worktree.

If repository hooks are installed, `.codex/harness/scripts/run-phases.py` passes the active task, phase, and runtime contract through `CODEX_HARNESS_*` environment variables. Required hooks then use that contract to block obvious phase-scope violations and to continue Codex when required outputs are missing.

## Installation Check

Before starting the workflow, check whether the current repository has the matching harness version:

```bash
python3 - <<'PY'
import json
from pathlib import Path
root = Path(".")
required = [
    root / "codex-harness.json",
    root / ".codex" / "harness" / "scripts" / "skill" / "SKILL.md",
    root / ".codex" / "harness" / "scripts" / "start.py",
    root / ".codex" / "harness" / "scripts" / "run-phases.py",
    root / ".codex" / "harness" / "scripts" / "relationship_graph.py",
    root / ".codex" / "harness" / "scripts" / "gen-relationship-graph.py",
    root / ".codex" / "harness" / "scripts" / "review-phase-plan.py",
    root / ".codex" / "harness" / "scripts" / "phase_semantics.py",
]
missing = [str(path) for path in required if not path.exists()]
if missing:
    raise SystemExit("missing: " + ", ".join(missing))
manifest_version = json.loads((root / "codex-harness.json").read_text(encoding="utf-8")).get("version")
skill_text = (root / ".codex" / "harness" / "scripts" / "skill" / "SKILL.md").read_text(encoding="utf-8")
if manifest_version != "0.1.4" or "version: 0.1.4" not in skill_text:
    raise SystemExit(f"version mismatch: manifest={manifest_version}")
PY
```

If it is missing or stale, install the harness into the current repository first:

```bash
python3 ~/.codex/skills/codex-harness/assets/bootstrap-install.py . --all --force
```

Project install removes old `.agents/skills/codex-harness` copies. The project should use the global skill for invocation and `.codex/harness/scripts/skill/SKILL.md` for isolated harness sessions.

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
python3 .codex/harness/scripts/start.py --request-file - --full-auto <<'EOF'
<user request>
EOF
```

Add `--docs-approved`, `--design-approved`, `--run-phases`, or `--evaluate` only when the user explicitly requested that state.
Use `--design-approved` only after the whole implementation design review has been approved.
When `--run-phases` is present, `start.py` must first obtain a valid `planned` result from the orchestration session, then call `.codex/harness/scripts/run-phases.py` itself. The orchestration session must not run Generate directly.

After the command finishes, read only these launcher outputs:

- `.codex/harness/sessions/<run-id>/last-message.md`
- `.codex/harness/sessions/<run-id>/questions.md`, when present
- `.codex/harness/sessions/<run-id>/docs-approval-request.md`, when present
- `.codex/harness/sessions/<run-id>/launcher-result.json`
- `.codex/harness/sessions/<run-id>/run-phases-output.txt`, when `runner_returncode` is non-zero
- `.codex/harness/sessions/<run-id>/run-phases-stderr.txt`, when `runner_returncode` is non-zero
- `.codex/harness/sessions/<run-id>/orchestration-violation.json`, when present

Report the status and show the relevant document content from `launcher-result.json.documents` directly in the parent chat.
Do not make the user open `questions.md`, `docs-approval-request.md`, or `implementation-design-review.md` just to understand the next decision.
If `launcher-result.json.documents` is missing because the repository has an older harness install, read the relevant file listed in the launcher result and show its content.
Do not summarize the whole harness session unless the user asks.
If `launcher-result.json` includes `relationship_graph.status: "warning"`, mention the warning path briefly without changing the task status.
For `planned` or `generated`, use `launcher-result.json.relationship_graph` as the relationship graph status. The isolated harness session cannot verify this file because the launcher writes it after the session exits.

## Harness Session Mode

Use this mode when the prompt or environment says this is an isolated harness session launched by `.codex/harness/scripts/start.py`.

Do not invoke `.codex/harness/scripts/start.py` from this mode.

When docs are not approved yet, the launcher owns files under `.codex/harness/sessions`.
Do not use shell commands or file-edit tools to create `questions.md` or `docs-approval-request.md`.
Return their Markdown content in the structured final output's `artifact.content`; the launcher writes the file.

## Workflow

1. Ensure the harness is installed in the current repository.
2. Read `references/workflow.md`, `references/review-gates.md`, `references/context-pack.md`, and `references/task-format.md`.
3. Move the request to exactly one next state.
4. During Clarify, ask only for blocking implementation-shaping decisions.
5. Review the request with the correct gate:
   - product feature gate for customer-facing features
   - internal tooling gate for automation and developer workflow tools
6. Ask for approval before writing task docs.
7. After docs approval, create mandatory docs, context-pack files, and task indexes.
8. Gather only the code and project context needed for the approved task.
9. Create `tasks/<task-dir>/docs/implementation-design-review.md`, or `design-review-waiver.md` only for tiny non-implementation work, and stop with `design_approval_needed` until the whole design review is approved.
10. After design approval, Plan work into self-contained task/phase files.
11. Validate the task with `.codex/harness/scripts/verify-task.py <task-dir> --require-design-approval`, `.codex/harness/scripts/run-phases.py <task-dir> --dry-run`, and `.codex/harness/scripts/review-phase-plan.py <task-dir>`.
12. Run phases with `.codex/harness/scripts/run-phases.py`.
13. Evaluate from fresh context.

## Hard Rules

- Do not create Clarify docs until the user explicitly approves.
- Do not flatter the proposal. Challenge weak evidence, unclear value, vague urgency, and bloated scope.
- Do not use subagents for Generate phases.
- Do not implement Generate work directly in the orchestrator session.
- Generate means the launcher or user runs `.codex/harness/scripts/run-phases.py`; direct edits are only allowed while acting as a phase agent launched by the runner.
- Do not let phase agents update task status.
- Let the runner decide phase success, retry, failure, and next phase.
- Treat conversation as source material, not execution state.
- Store durable decisions in files under the task context-pack.
- Store runner-enforced decisions in `decisions.json`, `open-decisions.json`, `architecture.json`, and `dependency-policy.json`.
- Do not let Plan or Generate invent implementation-shaping decisions.
- Do not create final implementation phase contracts before implementation design approval.
- Do not stop after docs approval until mandatory docs, context-pack files, task indexes, and an implementation design review or waiver exist.
- After implementation design approval, write `tasks/<task-dir>/context-pack/static/design-approval.json` with the approved design document path and current SHA-256 hash before Plan.
- Do not let implementation phase contracts include files outside the approved design review `Files To Add/Change` paths.
- Do not require the isolated harness session to verify relationship graph outputs. The launcher or runner writes them after the session or phase process exits.
- Do not run Generate when phase files still contain placeholders or missing AC commands.
- Do not run Generate for bugfix or validation phases unless the contract records reproduction evidence, or a fallback reason with alternative evidence.
- Do not run Generate for implementation phases unless the contract lists concrete `required_repo_outputs` in addition to the handoff.
- Let `run-phases.py` perform its package-manager install preflight before phase Codex execution. If install fails, treat the phase as environment-blocked instead of weakening checks.
- Do not manually mark phases or tasks completed.
- Do not manually create runner-owned runtime proof files.
- Do not claim Generate or Evaluate is complete unless the required runtime proof exists, acceptance commands pass, required files exist, and the handoff does not report blocked, partial, skipped, or workaround status.
- Do not bypass installed codex-harness hooks. If a hook blocks a path that should match `scope.allowed_paths`, report/fix the harness path rule. Do not weaken typecheck, shrink tsconfig includes, or remove validation to pass around the block.

## Stop Conditions

- Stop with `questions_needed` when a blocking decision is missing.
- Stop with `docs_approval_needed` when Clarify Review passes and task docs are not approved yet.
- Stop with `design_approval_needed` after docs approval once task docs, context-pack files, and `implementation-design-review.md` or `design-review-waiver.md` exist but implementation design is not approved yet.
- Stop with `planned` only after task docs, context-pack files, indexes, phase files, `verify-task.py`, `run-phases.py --dry-run`, and `review-phase-plan.py` pass.
- Stop with `generated` only after requested phases run and runtime proof passes verification.
- Stop with `blocked` only when the next durable state cannot be produced safely.
- After the user approves docs creation, do not stop until these exist:
  - `docs/harness/runner-contract.md`
  - `docs/harness/testing.md`
  - `docs/harness/document-scope.md`
  - `docs/harness/implementation-quality.md`
  - `tasks/<task-dir>/docs/prd.md`
  - `tasks/<task-dir>/docs/flow.md`
  - `tasks/<task-dir>/docs/data-schema.md`
  - `tasks/<task-dir>/docs/code-architecture.md`
  - `tasks/<task-dir>/docs/adr.md`
  - `tasks/<task-dir>/docs/implementation-design-review.md` or `tasks/<task-dir>/docs/design-review-waiver.md`
  - `tasks/index.json`
  - `tasks/<task-dir>/index.json`
  - `tasks/<task-dir>/context-pack/static/decisions.json`
  - `tasks/<task-dir>/context-pack/static/open-decisions.json`
  - `tasks/<task-dir>/context-pack/static/architecture.json`
  - `tasks/<task-dir>/context-pack/static/dependency-policy.json`
  - `tasks/<task-dir>/context-pack/static/context-gathering-budget.json`
  - `tasks/<task-dir>/context-pack/static/design-approval.json` after implementation design approval
  - `tasks/<task-dir>/context-pack/static/*`
  - `tasks/<task-dir>/phases/phase<N>.md`
- After Plan, run `python3 .codex/harness/scripts/verify-task.py <task-dir> --require-design-approval`, `python3 .codex/harness/scripts/run-phases.py <task-dir> --dry-run`, and `python3 .codex/harness/scripts/review-phase-plan.py <task-dir>`. Fix failures before stopping.
- After Plan, stop after verification, dry-run, and phase-plan semantic review pass. The launcher will generate `relationship-graph.json` and `.mmd`, or `relationship-graph-warning.json`, after the isolated session exits.
- After Generate, verify runtime proof before stopping.
- After Generate, the runner refreshes `relationship-graph.json` and `.mmd`, or records `relationship-graph-warning.json`, after phase execution.
- After Generate, run evaluation in a review/improve loop unless the user explicitly asks not to: review from fresh context, improve only rejected blockers and required follow-ups, then review again until evaluation returns approved or the runner's `--review-iterations` budget is exhausted.

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
- `tasks/<task-dir>/context-pack/runtime/phase<N>-quality.json` for every executed phase
- `tasks/<task-dir>/context-pack/runtime/phase<N>-result.json` for every completed phase
- `tasks/<task-dir>/context-pack/runtime/phase<N>-repair-packet.json` and `.md` for failed/retried attempts, when present
- `tasks/<task-dir>/context-pack/runtime/docs-diff.md` after phase 0
- `tasks/<task-dir>/context-pack/handoffs/phase<N>.md` for every completed phase

`phase<N>-result.json` is runner-owned. It contains measured facts: exit codes, changed files, required output status, and artifact paths. Phase agents write handoffs, not result JSON.
`phase<N>-gate.json` is runner-owned. It must pass before the phase can be marked completed.
`phase<N>-quality.json` is runner-owned. It records runnable project lint results, or harness baseline style checks when project lint is unavailable, and feeds the gate quality check.
`phase<N>-repair-packet.*` is runner-owned. It summarizes retryable failures for the next attempt. If it contains `contaminating_changes`, the failure is not auto-retryable until the paths are reviewed, cleaned up, or explicitly brought into phase scope.

For implementation phases, the contract must list repository files under `required_repo_outputs`; every entry must also be covered by `scope.allowed_paths`. The runner checks those files exist separately from task-relative `required_outputs`. A handoff that says blocked, partial, skipped, workaround, or equivalent Korean wording is a failed phase even if files and commands exist. A handoff that does not map changed repository files to phase instruction ids in `## Change Trace` is also a failed phase.

Evaluate is not complete unless these files exist:

- `tasks/<task-dir>/context-pack/runtime/evaluation-command-results.json`
- `tasks/<task-dir>/context-pack/runtime/evaluation-prompt.md`
- `tasks/<task-dir>/context-pack/runtime/evaluation-output.jsonl`
- `tasks/<task-dir>/context-pack/runtime/evaluation-last-message.json`

If runtime proof is missing, report the task as blocked or failed. Do not infer success from handoffs or status JSON alone.

Before final reporting, run:

```bash
python3 .codex/harness/scripts/verify-task.py <task-dir> --require-evaluation
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

Create a task skeleton after Clarify, Review, docs approval, Context Gathering, and implementation design review:

```bash
python3 .codex/harness/scripts/init-task.py <task-name> \
  --project "<project-name>" \
  --prompt-file <prompt-file> \
  --phase docs \
  --phase implementation \
  --phase tests
```

Build the next phase prompt without running Codex:

```bash
python3 .codex/harness/scripts/verify-task.py <task-dir>
python3 .codex/harness/scripts/run-phases.py <task-dir> --dry-run
python3 .codex/harness/scripts/review-phase-plan.py <task-dir>
```

Run pending phases:

```bash
python3 .codex/harness/scripts/run-phases.py <task-dir> --full-auto --evaluate
```

Resume from the earliest failed phase or repair packet:

```bash
python3 .codex/harness/scripts/run-phases.py <task-dir> --resume-repair --full-auto
```

Evaluate from fresh context:

```bash
python3 .codex/harness/scripts/evaluate-task.py <task-dir> --command "npm test" --full-auto
```
