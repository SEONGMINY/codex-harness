# Thread Execution Policy

## Purpose

Codex app-server thread path exists as an execution surface experiment.
It is not a replacement runner, a new orchestration layer, or a generic
multi-agent framework.

The default phase execution path remains `codex exec`.
Thread-backed phase execution is opt-in. A thread may execute bounded phase
work, but the Harness still decides phase success through artifacts, gates,
acceptance commands, verifier/preflight checks, and approval/hash state.

Core policy:

```text
Codex thread may execute.
Harness still decides.
```

## Supported Categories

Thread-backed execution may be considered for the following Level 1 opt-in
phase categories.

| Category | Why allowed | Required gates and safeguards |
| --- | --- | --- |
| `docs` | Documentation changes are usually bounded and reviewable through required outputs and acceptance commands. | Explicit `allowed_paths`, required outputs, deterministic acceptance command when applicable, verifier/preflight outside the thread. |
| `fixtures` | Fixture updates can be checked through exact file outputs and targeted tests. | Required repo outputs, targeted acceptance command, fixture paths only, no unrelated test data changes. |
| `schema/config` | Small schema or config edits can be validated when the affected surface is narrow. | Deterministic schema/config tests, explicit allowed paths, no runtime/proof/approval mutation. |
| `bounded tests` | Test-only changes are acceptable when a targeted command proves the intended behavior. | Single test module or bounded fixture area, targeted acceptance command, verifier/preflight outside the thread. |
| `handoff/evidence` | Handoff and evidence work can be checked by existing handoff and evidence gates. | Required handoff/evidence gates, no direct runtime/proof/approval artifact mutation. |
| `small code changes` | Small implementation edits are acceptable only when behavior is tightly scoped and objectively checked. | Narrow allowed paths, single package or bounded repo area, expected small diff, deterministic acceptance command, verifier/preflight outside the thread. |

`small code changes` is the highest-risk supported category. It is allowed only
when the phase contract makes the expected behavior, allowed files, and
verification command concrete.

## Unsupported Categories

Thread-backed execution is not currently supported for the following categories.

| Category | Why unsafe | Missing evidence |
| --- | --- | --- |
| `large refactors` | High risk of semantic drift, broad edits, and hard-to-review diff shape. | Large-diff quality data and multi-attempt stability. |
| `multi-package changes` | Wide impact radius makes scope and integration risk harder to bound. | Cross-package safety and integration evidence. |
| `evaluation migration` | Risks reintroducing evaluation-triggered repair loops. | Separate design review and failure campaign. |
| `verifier migration` | Risks weakening verifier/preflight authority. | Evidence that verifier authority remains outside the thread. |
| `approval/proof mutations` | These are authoritative state and must not be thread-owned. | Protected artifact isolation guarantees. |
| `runtime artifact mutations` | Mixing thread state with project state would weaken source-of-truth boundaries. | Evidence that runtime proof remains runner-owned. |
| `high ambiguity phases` | Ambiguous work invites thread steering, scope growth, and implicit obligations. | Operator review data and stronger containment evidence. |
| `security-sensitive phases` | The current evidence does not cover security review depth or high-stakes side effects. | Security-specific validation and review. |

## Opt-In Criteria

Thread-backed execution may be used only when all criteria are met.

- The phase belongs to a supported category.
- `allowed_paths` are explicit and narrow.
- Expected changed files are small, normally no more than 8 files.
- The impact radius is a single package or one bounded repo area.
- Required outputs and required repo outputs are declared when applicable.
- A deterministic acceptance command exists for behavioral changes.
- Verifier/preflight checks remain outside the thread.
- Handoff gates remain enabled when handoff is required.
- Protected paths are excluded from thread writes.
- Thread invocation failure remains fail-closed.
- Post-thread Harness gate/AC failure follows the existing Harness retry policy.
- The default execution path remains `codex exec`.

Thread opt-in is not evidence that the thread owns phase status. It only changes
the mechanism used to produce candidate work for the Harness to validate.

## Protected Paths

Thread-backed phase execution must not directly write authoritative Harness
state or protected project metadata.

Protected paths include:

- `tasks/<task>/context-pack/runtime/**`
- `tasks/<task>/context-pack/static/**`
- approval, hash, and proof artifacts
- phase result artifacts
- attempt contracts and runner-owned proof files
- task indexes and top-level task indexes
- verifier/preflight outputs
- harness runner scripts and tests, unless the approved phase explicitly targets
  harness implementation files and the phase is not using thread-owned runtime
  artifact mutation
- unrelated repository files outside `scope.allowed_paths`

If a thread writes outside allowed paths, the Harness scope gate must reject the
attempt. Scope contamination may be terminal under the existing Harness policy.

## Failure Policy

Thread-backed phase execution has two distinct failure classes.

### Thread Invocation Failure

Thread invocation failure means the thread execution surface itself failed.

Examples:

- SDK unavailable
- auth/session failure
- thread start failure
- thread run failure
- timeout
- interrupted
- empty final response
- invalid final response
- partial output without a completed final response
- output artifact write failure

Policy:

```text
failure.type = codex_thread
retryable = false
phase complete 없음
phase result 없음
automatic fallback 없음
automatic retry 없음
automatic repair 없음
Main/user decision required
```

### Post-Thread Harness Gate Failure

Post-thread Harness gate failure means the thread invocation completed, but the
candidate work did not pass Harness validation.

Examples:

- required output missing
- required repo output missing
- handoff failure
- acceptance command failure
- scope validation failure
- verifier/preflight failure

Policy:

```text
existing Harness retry policy applies
```

This preserves semantic equivalence with `codex exec`:

```text
codex exec succeeds -> Harness gate fails -> Harness retry policy applies
Codex thread succeeds -> Harness gate fails -> Harness retry policy applies
```

Verifier-triggered repair loops remain forbidden. Thread-owned retry and repair
remain forbidden.

## Rollout Levels

### Level 0: Experimental

Level 0 is the current baseline for validation and smoke testing.

Entry conditions:

- SDK/app-server path can execute one-shot.
- Read-only and workspace-write smoke paths are validated.
- Fail-closed invocation behavior is tested.
- Artifact/gate authority is preserved.

### Level 1: Supported Categories Opt-In

Level 1 allows official opt-in use for supported categories only.

Entry conditions:

- 12 or more completed phase observations.
- Final verify chains pass.
- Gate semantics are equivalent to `codex exec`.
- Scope violations are 0.
- Thread state leakage is 0.
- Artifact authority bypass is 0.
- This policy is documented and followed.

Level 1 does not change the default execution path.

### Level 2: Default Candidate

Level 2 is not currently reached.

Entry conditions:

- 5 or more real tasks.
- 20 to 40 unique phases.
- Multiple phase categories represented.
- Success and failure campaigns completed.
- Cost or stable proxy metrics available.
- Operator debugging review completed.
- Thread completion/gate pass rate is at least comparable to `codex exec`.
- No protected path writes, authority bypass, or thread state leakage.

### Level 3: Default Path

Level 3 is out of scope for the current baseline.

Entry conditions:

- Level 2 criteria hold across repeated campaigns.
- Rollback plan exists.
- Operational diagnostics are acceptable.
- Cost/performance advantage is stable.
- Failure behavior is predictable.

## Expansion Rules

Any expansion beyond Level 1 must answer these questions before implementation:

```text
Why are the current supported categories insufficient?

What new evidence shows the proposed category preserves Harness semantics?

How does the change avoid reintroducing:
- default execution switch
- Execution Surface abstraction
- adapter/registry layer
- automatic fallback
- automatic retry/repair for invocation failure
- verifier/evaluation/docs-review migration
- thread lifecycle model
- resume/fork dependency
- planner/reviewer/improver role framework
- thread-owned task state
```

Broader migration requires a separate design review and a validation campaign
covering the affected category.

## Examples

Allowed Level 1 examples:

- Update one documentation file and pass docs checks.
- Update a fixture and pass the targeted fixture test.
- Adjust a small schema/config file with deterministic validation.
- Add or update one bounded test module.
- Write a required phase handoff/evidence file through the approved Harness path.
- Make a small code edit with explicit allowed paths and a targeted acceptance
  command.

Not allowed at Level 1:

- Refactor a subsystem.
- Change multiple packages at once.
- Move verifier or evaluation execution into thread mode.
- Let a thread write runtime proof, approval, hash, or phase result artifacts.
- Use thread state as task state.
- Enable automatic fallback, retry, or repair after thread invocation failure.

## Future Requirements

Before considering Level 2, collect evidence for:

- 5 or more real tasks.
- 20 to 40 unique phases.
- More phase categories, including moderate code changes.
- Failure-heavy validation under live-like conditions.
- Direct token/cost data or stable cost proxies.
- Operator review of debugging quality and artifact usefulness.
- Long-running phase behavior.
- Continued 0 protected path writes.
- Continued 0 authority bypass.
- Continued 0 thread state leakage.
