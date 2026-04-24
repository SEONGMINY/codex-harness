# Task Format

## Top-Level Index

`tasks/index.json`:

```json
{
  "tasks": [
    {
      "id": 0,
      "name": "harness-mvp",
      "dir": "0-harness-mvp",
      "status": "pending",
      "created_at": "2026-04-24T10:00:00+09:00"
    }
  ]
}
```

The runner updates `status`, `completed_at`, and `failed_at`.

## Task Index

`tasks/<task-dir>/index.json`:

```json
{
  "project": "Project",
  "task": "harness-mvp",
  "prompt": "original prompt",
  "created_at": "2026-04-24T10:00:00+09:00",
  "totalPhases": 3,
  "phases": [
    {
      "phase": 0,
      "name": "docs",
      "status": "pending",
      "ac_commands": ["python3 -m py_compile scripts/harness/run-phases.py"],
      "required_outputs": ["context-pack/handoffs/phase0.md"]
    }
  ]
}
```

Allowed phase statuses:

- `pending`
- `running`
- `completed`
- `error`

Only runner scripts update phase status.

## Phase Files

Preferred path:

```text
tasks/<task-dir>/phases/phase<N>.md
```

Required sections:

```markdown
# Phase <N>: <Name>

## Purpose

<one paragraph>

## Read First

- <docs/context paths>

## Work

<specific implementation instructions>

## Acceptance Criteria

```bash
<commands>
```

## Required Outputs

- `context-pack/handoffs/phase<N>.md`

## Constraints

- <what not to do>
```

## Phase Agent Contract

Phase agents must:

- implement only the phase
- write the required handoff
- run useful local checks when possible
- report what changed

Phase agents must not:

- update `tasks/*/index.json`
- mark themselves completed
- decide next phase
- spawn subagents for Generate
- commit unless the phase explicitly requires it
