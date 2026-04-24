# Context-Pack

## Purpose

Context-pack replaces session chaining.

It stores reusable, curated context fragments. The runner assembles only the fragments needed for the next phase.

## Directory

```text
tasks/<task-dir>/context-pack/
  static/
  runtime/
  handoffs/
```

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

Keep each file concise.

## Runtime Context

Written by scripts.

Use for changing context:

- generated prompts
- command output summaries
- docs diff
- phase error summaries
- git status snapshots

Runtime files are not strategic source of truth.

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

## Prompt Assembly

For each phase, include:

- harness execution contract
- task metadata
- static context files
- current phase file
- previous handoffs
- docs diff when available
- git status and diff summary
- latest phase failure summary when retrying

Do not include the original chat transcript.
