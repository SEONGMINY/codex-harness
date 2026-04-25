# Context-Pack

## Purpose

Context-pack replaces session chaining.

It stores reusable, curated context fragments. The runner assembles only the fragments needed for the next phase.

## Directory

```text
docs/harness/
tasks/<task-dir>/context-pack/
  static/
  runtime/
  handoffs/
tasks/<task-dir>/docs/
```

Use `docs/harness/` for reusable harness policy.
Use `tasks/<task-dir>/docs/` for task-specific planning docs.

## Static Context

Created after Clarify Review and user approval.

Use for stable context:

- original prompt
- product intent
- decisions
- rejected options
- constraints
- architecture
- data schema
- test policy
- clarify review result
- docs approval record
- context gathering result
- docs index

Keep each file concise.
Do not leave placeholders in static context files before Generate.

## Runtime Context

Written by scripts.

Use for changing context:

- generated prompts
- command output summaries
- docs diff
- phase error summaries
- git status snapshots

Runtime files are not strategic source of truth.
Runtime files are execution proof.
Do not create runner-owned proof files manually.
The runner writes `phase<N>-result.json`.
The phase agent writes only `handoffs/phase<N>.md`.

Required Generate proof:

- `phase<N>-prompt.md`
- `phase<N>-output-attempt<M>.jsonl`
- `phase<N>-stderr-attempt<M>.txt`
- `phase<N>-result.json`
- `docs-diff.md` after phase 0

Required Evaluate proof:

- `evaluation-command-results.json`
- `evaluation-prompt.md`
- `evaluation-output.jsonl`

Runner-generated `phase<N>-result.json` schema:

```json
{
  "phase": 0,
  "status": "completed",
  "attempt": 1,
  "codex_exit_code": 0,
  "changed_files": ["path/from/repo/root"],
  "commands_run": [
    {"command": "npm test", "exit_code": 0}
  ],
  "tests_passed": true,
  "required_outputs": [
    {"path": "context-pack/handoffs/phase0.md", "exists": true}
  ],
  "artifacts": {
    "prompt": "context-pack/runtime/phase0-prompt.md",
    "stdout": "context-pack/runtime/phase0-output-attempt1.jsonl",
    "stderr": "context-pack/runtime/phase0-stderr-attempt1.txt",
    "ac_results": "context-pack/runtime/phase0-ac-attempt1.json",
    "handoff": "context-pack/handoffs/phase0.md"
  }
}
```

## Handoffs

Each phase writes:

```text
tasks/<task-dir>/context-pack/handoffs/phase<N>.md
```

Required structure:

```markdown
# Phase <N> Handoff

## Changed Files

- <path>: <what changed>

## Behavior

- <observable behavior added or changed>

## Notes For Next Phase

- <only details the next phase must know>

## Risks

- <remaining risk, or "None">
```

Handoff must not claim final success.
The runner decides success with AC commands and required output checks.
Handoff alone is not proof that Generate ran through the runner.

## Prompt Assembly

For each phase, include:

- harness execution contract
- task metadata
- mandatory docs listed in `tasks/<task-dir>/index.json`
- common docs listed in `tasks/<task-dir>/index.json`
- static context files
- current phase file
- previous handoffs
- docs diff when available
- git status and diff summary
- latest phase failure summary when retrying

Do not include the original chat transcript.
