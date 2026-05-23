# Harness Workflow

## Principle

The harness is a state machine, not a long conversation.

- Codex sessions do work.
- Files hold durable context.
- Runner scripts decide state transitions.
- Tests and required outputs decide completion.

Every launcher run must produce exactly one next state:

- `questions_needed`
- `docs_approval_needed`
- `design_approval_needed`
- `planned`
- `generated`
- `blocked`

## Stage Order

1. Clarify
2. Clarify Review
3. User approval for docs
4. Docs and context-pack creation
5. Context Gathering
6. Implementation Design Review
7. User approval for implementation design
8. Plan
9. Generate
10. Evaluate and Improve Loop

## Clarify

Outcome: either ask for missing decisions, request docs approval, or record a blocking decision.

Clarify is a decision gate, not only a requirements interview.

Clarify passes only when these are explicit or intentionally not applicable:

- functional scope and non-scope
- technology stack
- runtime and execution environment
- data model
- external interface
- internal interface
- module boundary
- dependency direction
- object graph and cycle policy
- design pattern
- new dependency policy
- test strategy
- error handling
- migration, compatibility, performance, security, and operations constraints

If any item is missing, do one of these:

- return one targeted question as the launcher structured final output artifact
- write a blocking item to `open-decisions.json` after task context exists

Do not decide these automatically. You may propose a default only when it is grounded in an explicit existing repository pattern, and the user must approve it before Plan.

Local implementation choices may stay inside a phase when they do not add dependencies, layers, public interfaces, data model changes, user-visible behavior, or architecture edges.

Clarify should produce only one of these outcomes:

- `questions_needed`: `questions.md` exists after the launcher materializes the structured final output artifact.
- `docs_approval_needed`: Clarify Review passed and `docs-approval-request.md` exists after the launcher materializes the structured final output artifact.
- `blocked`: the request cannot be made safe or coherent.

Do not create docs until the user approves.

## Clarify Review

Use `review-gates.md`.

Choose the product feature gate for customer-facing product work.
Choose the internal tooling gate for automation, harness, dev workflow, scripts, and repo operations.

One failed checklist item rejects the proposal unless the gate says otherwise.

Clarify Review passes only when it can point to the accepted scope, non-scope, completion criteria, and implementation-shaping decisions.

## Docs And Context-Pack

After approval, create concise agent-facing documents.

Mandatory docs:

Common docs:

- `docs/harness/runner-contract.md`
- `docs/harness/testing.md`
- `docs/harness/document-scope.md`
- `docs/harness/implementation-quality.md`

Task docs:

- `tasks/<task-dir>/docs/prd.md`
- `tasks/<task-dir>/docs/flow.md`
- `tasks/<task-dir>/docs/data-schema.md`
- `tasks/<task-dir>/docs/code-architecture.md`
- `tasks/<task-dir>/docs/adr.md`
- `tasks/<task-dir>/docs/implementation-design-review.md`, or `tasks/<task-dir>/docs/design-review-waiver.md` only for tiny non-implementation work

Mandatory task context:

- `tasks/<task-dir>/context-pack/static/original-prompt.md`
- `tasks/<task-dir>/context-pack/static/product.md`
- `tasks/<task-dir>/context-pack/static/decisions.md`
- `tasks/<task-dir>/context-pack/static/decisions.json`
- `tasks/<task-dir>/context-pack/static/open-decisions.json`
- `tasks/<task-dir>/context-pack/static/architecture.json`
- `tasks/<task-dir>/context-pack/static/dependency-policy.json`
- `tasks/<task-dir>/context-pack/static/context-gathering-budget.json`
- `tasks/<task-dir>/context-pack/static/rejected-options.md`
- `tasks/<task-dir>/context-pack/static/constraints.md`
- `tasks/<task-dir>/context-pack/static/test-policy.md`
- `tasks/<task-dir>/context-pack/static/clarify-review.md`
- `tasks/<task-dir>/context-pack/static/docs-approval.md`
- `tasks/<task-dir>/context-pack/static/context-gathering.md`
- `tasks/<task-dir>/context-pack/static/docs-index.md`

Docs should be compact. Preserve intent, tradeoffs, and rejected options.
Do not leave placeholders in mandatory docs or context files before Generate.

Markdown explains decisions for people.
JSON enforces decisions for the runner.

After docs and context gathering, stop with `design_approval_needed` unless the launcher run already has design approval.
The implementation design review must cover scope, layer plan, object/module dependency direction, public interfaces, API contract, DB/storage schema, state and lifecycle, transaction boundaries, files to add/change, Mermaid diagrams, open decisions, and approval checklist.
Use Mermaid `flowchart`, `sequenceDiagram`, or `stateDiagram-v2` blocks to show object/module dependency direction and layer dependency direction when implementation introduces a phase, new file, public interface, layer boundary, or state flow.
Do not create final implementation phase contracts until the whole design review is approved.

After implementation design approval, write `tasks/<task-dir>/context-pack/static/design-approval.json`:

```json
{
  "approved": true,
  "approved_doc": "tasks/<task-dir>/docs/implementation-design-review.md",
  "approved_doc_sha256": "<sha256 of approved_doc>",
  "approved_at": "2026-05-22T10:00:00+09:00",
  "approval_source": "--design-approved"
}
```

If the design document changes after approval, its hash no longer matches and Plan must stop until approval is refreshed.

## Context Gathering

Find only context needed for the approved task.

Use `context-gathering-budget.json`.

Stop gathering when the target files, architecture boundary, and test command are known.
Escalate once if signals conflict or the scope boundary is unclear.

Record:

- relevant files
- relevant commands
- examples to follow
- known risks
- external docs or links when needed

Do not dump the whole repository into context-pack.

## Plan

Outcome: phase contracts that translate approved decisions into executable work.

Plan may run only when:

- `implementation-design-review.md` or `design-review-waiver.md` exists and is approved.
- `design-approval.json` records the current approved design document hash.
- `open-decisions.json` has no blocking open decision.
- `decisions.json` contains approved implementation decisions.
- `architecture.json` contains approved architecture refs.
- `dependency-policy.json` is valid.
- Mandatory task docs and context-pack files have no placeholders.
- Implementation-shaping assumptions are recorded as approved decisions or blocking open decisions.

Rules:

- Phase 0 should update docs when docs must change.
- Each phase should target one layer or module.
- Each phase must include a `## Contract` JSON block.
- Each phase contract must be self-contained and must not reference prior chat context.
- Each phase contract must list `read_first.docs` and, for phase N > 0, `read_first.previous_outputs`.
- Each implementation phase contract must include the approved implementation design review or waiver in `read_first.docs`.
- Each implementation phase contract's `scope.allowed_paths` and `required_repo_outputs` must stay within the design review `Files To Add/Change` paths.
- Each phase contract must list `scope.allowed_paths`.
- Each non-documentation phase should describe function/class signatures in `interfaces`.
- Each phase contract must list approved `decision_refs`.
- Each phase contract must list approved `architecture_refs`.
- Each phase contract must define `dependency_policy`.
- Each phase contract must list outcome-first `success_criteria`.
- Each phase contract must define `stop_rules`, `fallback_behavior`, `validation_budget`, and `missing_evidence_behavior`.
- Bugfix or validation phases must include reproduction evidence, or a fallback reason with alternative evidence.
- Each forbidden rule must include a concrete reason.
- Each phase must have executable AC commands.
- Each phase must write a handoff file.
- Each phase handoff must map changed repository files to instruction ids in `## Change Trace`.
- Status is owned by the runner, not Codex.
- Result JSON is generated by the runner, not Codex.
- Phase files must be self-contained.
- Phase files must not contain `TODO` placeholders before Generate.
- Plan must not create new decisions. It translates approved decisions into phase contracts.
- Blocking `open-decisions.json` entries must be resolved before Plan can pass.

Before stopping after Plan, run:

```bash
python3 .codex/harness/scripts/verify-task.py <task-dir> --require-design-approval
python3 .codex/harness/scripts/run-phases.py <task-dir> --dry-run
```

Fix any preflight failure.

## Generate

Run each phase in a fresh `codex exec` session.

Do not use subagents for implementation phases.
Do not use long conversation resume as the default.
Do not implement phase work directly in the orchestrator session.
The orchestrator runs the runner; the phase agent launched by the runner edits implementation files.

Generate must not make implementation-shaping decisions.
If the phase needs an unapproved architecture, dependency, data model, external interface, module boundary, or user-visible behavior decision, it must stop blocked and write the missing decision to the handoff.

Allowed exception:

- A runner may retry the same phase with fresh context and a runner-generated repair packet.

Generate completion requires runtime proof:

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
- `context-pack/runtime/phase<N>-repair-packet.json` and `.md` for failed/retried attempts, when present
- `context-pack/runtime/docs-diff.md` after phase 0
- `context-pack/handoffs/phase<N>.md`

The runner-generated phase result JSON is the machine-readable completion contract.
The runner-generated gate JSON decides whether the phase may complete.
For implementation phases, `required_repo_outputs` must name concrete repository files, and the gate checks that they exist.
The gate fails if the handoff reports blocked, partial, skipped, workaround, or equivalent Korean wording.
The gate fails if changed repository files are not mapped to phase instruction ids in the handoff `## Change Trace` section.
The runner-generated repair packet tells the next attempt exactly what failed.
The reconciliation summary is included in later phase context.
Unverified reconciliation items are QA notes, not retry triggers. Retry only when the gate fails.
The handoff remains the human-readable summary.
`start.py`, `run-phases.py`, and `evaluate-task.py` stream child Codex stdout/stderr into runtime log files while Codex is running.
They fail a silent child after `--codex-idle-timeout` when stdout, stderr, stdin progress, and watched files stay unchanged.

When hooks are installed, the runner passes these environment variables to `codex exec`:

- `CODEX_HARNESS_ACTIVE`
- `CODEX_HARNESS_ROOT`
- `CODEX_HARNESS_TASK`
- `CODEX_HARNESS_TASK_PATH`
- `CODEX_HARNESS_PHASE`
- `CODEX_HARNESS_CONTRACT_PATH`

Required hooks:

- `PreToolUse`: blocks supported edits outside `Contract.scope.allowed_paths` and runner-owned proof files.
- `Stop`: continues Codex if `Contract.required_outputs` are missing.

Optional hooks:

- `PostToolUse`: feeds back scope violations after supported tools run.
- `UserPromptSubmit`: adds harness reminders when the user invokes `$codex-harness`.

Hooks are guardrails. Runner proof remains the source of truth.

If runtime proof is absent, the orchestrator must report failure or blocked status.
It must not manually mark phases complete.
Use `.codex/harness/scripts/verify-task.py <task-dir>` as the source of truth for artifact validity.

## Evaluate And Improve Loop

Evaluate from fresh context.

Minimum checks:

- run tests from `testing.md`
- verify acceptance criteria
- review git diff against original intent
- check that rejected options were not reintroduced
- check that scope did not expand

Evaluation should not trust a phase agent's success claim.

When Generate completes, run `.codex/harness/scripts/evaluate-task.py` with the task's evaluation commands unless the user explicitly asks not to.
If evaluation returns `rejected`, enter improvement mode:

1. Use the evaluation blockers and required follow-ups as the improvement scope.
2. Edit only paths already allowed by completed phase contracts.
3. Write `context-pack/handoffs/evaluation-repair<N>.md`.
4. Re-run evaluation from fresh context.
5. Repeat review -> improve -> review until evaluation returns `approved`.

The runner caps the loop with `--review-iterations` to prevent infinite repair cycles. Exhausting the limit is a failed evaluation, not a completed task.

Evaluate completion requires runtime proof:

- `context-pack/runtime/evaluation-command-results.json`
- `context-pack/runtime/evaluation-prompt.md`
- `context-pack/runtime/evaluation-output.jsonl`
- `context-pack/runtime/evaluation-last-message.json`
- `context-pack/runtime/evaluation-repair<N>-result.json`, when an improvement iteration ran

Use `.codex/harness/scripts/verify-task.py <task-dir> --require-evaluation` after evaluation.
