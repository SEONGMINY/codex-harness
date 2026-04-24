# Harness Workflow

## Principle

The harness is a state machine, not a long conversation.

- Codex sessions do work.
- Files hold durable context.
- Runner scripts decide state transitions.
- Tests and required outputs decide completion.

## Stage Order

1. Clarify
2. Clarify Review
3. User approval for docs
4. Docs and context-pack creation
5. Context Gathering
6. Plan
7. Generate
8. Evaluate

## Clarify

Goal: define the work precisely enough that another Codex session can implement it without relying on the original chat.

Discuss:

- customer or operator problem
- user flow
- implementation feasibility
- data model
- architecture
- constraints
- completion criteria
- alternatives that avoid building

Do not create docs until the user approves.

## Clarify Review

Use `review-gates.md`.

Choose the product feature gate for customer-facing product work.
Choose the internal tooling gate for automation, harness, dev workflow, scripts, and repo operations.

One failed checklist item rejects the proposal unless the gate says otherwise.

## Docs And Context-Pack

After approval, create concise agent-facing documents.

Recommended docs:

- `docs/prd.md`
- `docs/flow.md`
- `docs/data-schema.md`
- `docs/code-architecture.md`
- `docs/adr.md`

Recommended task context:

- `tasks/<task-dir>/context-pack/static/product.md`
- `tasks/<task-dir>/context-pack/static/decisions.md`
- `tasks/<task-dir>/context-pack/static/rejected-options.md`
- `tasks/<task-dir>/context-pack/static/constraints.md`
- `tasks/<task-dir>/context-pack/static/test-policy.md`

Docs should be compact. Preserve intent, tradeoffs, and rejected options.

## Context Gathering

Find only context needed for the approved task.

Record:

- relevant files
- relevant commands
- examples to follow
- known risks
- external docs or links when needed

Do not dump the whole repository into context-pack.

## Plan

Split work into phases.

Rules:

- Phase 0 should update docs when docs must change.
- Each phase should target one layer or module.
- Each phase must have executable AC commands.
- Each phase must write a handoff file.
- Status is owned by the runner, not Codex.

## Generate

Run each phase in a fresh `codex exec` session.

Do not use subagents for implementation phases.
Do not use long conversation resume as the default.

Allowed exception:

- A runner may retry the same phase with fresh context and the latest failure summary.

## Evaluate

Evaluate from fresh context.

Minimum checks:

- run tests from `testing.md`
- verify acceptance criteria
- review git diff against original intent
- check that rejected options were not reintroduced
- check that scope did not expand

Evaluation should not trust a phase agent's success claim.
