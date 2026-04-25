# Codex Harness

Runner-owned Codex implementation harness.

The harness turns an approved request into task docs, curated context, phase files, runner-owned execution proof, and fresh-context evaluation.

## Install In A Codex Project

From this repository:

```bash
python3 scripts/install-codex-harness.py /path/to/target-repo
```

Overwrite an existing harness install:

```bash
python3 scripts/install-codex-harness.py /path/to/target-repo --force
```

This copies:

- `.agents/skills/codex-harness`
- `scripts/harness`

## Use

In the target repo, invoke:

```text
$codex-harness
```

Then follow the Clarify, Review, Context Gathering, Plan, Generate, Evaluate workflow.

Generate work must run through:

```bash
python3 scripts/harness/run-phases.py <task-dir> --full-auto --evaluate
```

## Contract

- Phase agents write implementation changes and `context-pack/handoffs/phase<N>.md`.
- Runner scripts own task status, retries, AC commands, and completion decisions.
- Runner scripts generate `context-pack/runtime/phase<N>-result.json`.
- `verify-task.py` is the artifact validity source of truth.
