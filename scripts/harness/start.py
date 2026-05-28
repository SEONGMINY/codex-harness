#!/usr/bin/env python3
"""Launch a codex-harness orchestration session outside the parent chat."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from codex_exec import add_output_schema, run_codex_exec
from policy_pack import policy_pack_metadata
from policy_lineage import design_approval_scope_sha256, policy_pack_lineage_sha256, stable_json_sha256


SKIP_SNAPSHOT_DIRS = {
    ".git",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}
SKIP_SNAPSHOT_PATHS = {
    ".codex-harness",
    ".codex/harness/sessions",
}
HARNESS_VERSION = "0.1.5"
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
MANDATORY_COMMON_DOCS = [
    "docs/harness/runner-contract.md",
    "docs/harness/testing.md",
    "docs/harness/document-scope.md",
    "docs/harness/implementation-quality.md",
]
MANDATORY_TASK_DOCS = [
    "prd.md",
    "flow.md",
    "data-schema.md",
    "code-architecture.md",
    "adr.md",
]
MANDATORY_STATIC_FILES = [
    "original-prompt.md",
    "product.md",
    "decisions.md",
    "decisions.json",
    "open-decisions.json",
    "architecture.json",
    "dependency-policy.json",
    "context-gathering-budget.json",
    "rejected-options.md",
    "constraints.md",
    "test-policy.md",
    "clarify-review.md",
    "docs-approval.md",
    "context-gathering.md",
    "docs-index.md",
    "design-contract.json",
    "review-taxonomy.json",
    "review-findings.json",
    "review-coverage.json",
    "traceability-matrix.json",
]
DESIGN_REVIEW_DOC = "implementation-design-review.md"
DESIGN_REVIEW_WAIVER_DOC = "design-review-waiver.md"
DESIGN_APPROVAL_FILE = "design-approval.json"
DOCUMENT_RESULT_MAX_CHARS = 80_000


def now_id() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9가-힣]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:48] or "request"


def read_request(args: argparse.Namespace) -> str:
    if args.request_file:
        if args.request_file == "-":
            return sys.stdin.read()
        return Path(args.request_file).expanduser().read_text(encoding="utf-8")
    if args.request:
        return args.request
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise ValueError("Provide --request-file, --request, or pipe request text through stdin.")


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def codex_config_value(key: str, value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'{key}="{escaped}"'


def file_fingerprint(path: Path) -> str:
    if path.is_symlink():
        return f"symlink:{os.readlink(path)}"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_files(root: Path) -> list[Path]:
    files: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                if entry.name in SKIP_SNAPSHOT_DIRS or any(is_under(relative, skipped) for skipped in SKIP_SNAPSHOT_PATHS):
                    continue
                stack.append(path)
            elif entry.is_file(follow_symlinks=False) or entry.is_symlink():
                files.append(Path(entry.path))
    return files


def worktree_snapshot(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in snapshot_files(root):
        relative = path.relative_to(root)
        snapshot[relative.as_posix()] = file_fingerprint(path)
    return snapshot


def changed_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    paths = set(before) | set(after)
    return sorted(path for path in paths if before.get(path) != after.get(path))


def is_under(path: str, directory: str) -> bool:
    return path == directory or path.startswith(directory.rstrip("/") + "/")


def launcher_allowed_change(path: str, run_dir: Path, root: Path) -> bool:
    return is_under(path, rel(run_dir, root))


def build_prompt(
    root: Path,
    run_dir: Path,
    skill_path: Path,
    request_path: Path,
    answer_paths: list[Path],
    docs_approved: bool,
    design_approved: bool,
    run_phases: bool,
    reasoning_effort: str | None,
) -> str:
    answers = "\n".join(f"  - `{rel(path, root)}`" for path in answer_paths) or "  - 없음"
    approval = "approved" if docs_approved else "not_approved"
    design_approval = "approved" if design_approved else "not_approved"
    generate_state = "requested" if run_phases else "not_requested"
    effort_line = (
        f"- Harness session reasoning effort is forced to `{reasoning_effort}` by the launcher."
        if reasoning_effort
        else "- Harness session reasoning effort follows the active Codex config."
    )
    if docs_approved and design_approved:
        interaction_contract = f"""## Allowed Next State

Docs and implementation design are approved in this launcher run.

Produce `planned` or `blocked`.

Required before `planned`:

- Mandatory task docs and context-pack files exist.
- `tasks/<task-dir>/docs/implementation-design-review.md` or `tasks/<task-dir>/docs/design-review-waiver.md` exists.
- `tasks/<task-dir>/context-pack/static/design-approval.json` records the approved design document path, SHA-256 hash, approval time, and approval source.
- `decisions.json`, `architecture.json`, and `dependency-policy.json` contain the approved implementation-shaping decisions.
- `open-decisions.json` has no blocking open item.
- Approved implementation design is reflected in `decisions.json`, `architecture.json`, `dependency-policy.json`, and phase contracts.
- Phase contracts reference only approved decisions and architecture refs.
- Implementation phase contracts stay within the approved `Files To Add/Change` paths from the design review.
- `python3 .codex/harness/scripts/verify-task.py <task-dir> --require-design-approval` passes.
- `python3 .codex/harness/scripts/run-phases.py <task-dir> --dry-run` passes.
- `python3 .codex/harness/scripts/review-phase-plan.py <task-dir>` passes.
"""
        generate_contract = f"""## Generate

Do not run Generate from this Codex orchestration session.

If Generate state is `requested`, still stop after docs, context gathering, planning, `verify-task.py`, `run-phases.py --dry-run`, and `review-phase-plan.py`.
The Python launcher process will run `.codex/harness/scripts/run-phases.py` after it receives a valid `planned` result.
"""
    elif docs_approved:
        interaction_contract = f"""## Allowed Next State

Docs are approved, but implementation design is not approved in this launcher run.

Produce exactly one of these:

- `design_approval_needed`: create task docs, context-pack files, and `tasks/<task-dir>/docs/implementation-design-review.md`.
- `design_approval_needed`: for tiny non-implementation work only, create `tasks/<task-dir>/docs/design-review-waiver.md` instead and explain why design review is unnecessary.
- `blocked`: use only when task docs or design review cannot be produced safely.

Do not produce `planned`.
Do not create final phase contracts for implementation.
Do not run `verify-task.py`, `run-phases.py`, `review-phase-plan.py`, Generate, or Evaluate.

The implementation design review must include these sections:

- Scope Summary
- Layer Plan
- Object/Module Dependency
- Public Interfaces
- API Contract
- DB/Storage Schema
- State And Lifecycle
- Transaction Boundaries
- Files To Add/Change
- Mermaid Diagrams
- Open Decisions
- Approval Checklist

When implementation introduces a phase, new file, public interface, layer boundary, or state flow, `Mermaid Diagrams` must contain at least one `mermaid` block using only `flowchart`, `sequenceDiagram`, or `stateDiagram-v2`.
Use Mermaid to show object/module dependency direction and layer dependency direction, not decorative layout.
If any implementation-shaping decision is unresolved, record it in the design review and `open-decisions.json` instead of guessing.
"""
        generate_contract = """## Generate

Generate is disabled until the launcher is rerun with `--design-approved`.
"""
    else:
        interaction_contract = f"""## Allowed Next State

Docs are not approved in this launcher run.

Produce exactly one of these:

- `questions_needed`: write `{rel(run_dir / "questions.md", root)}` when a blocking decision is missing.
- `docs_approval_needed`: write `{rel(run_dir / "docs-approval-request.md", root)}` when Clarify and Review pass.

Do not create task docs, task indexes, context-pack files, phase files, or implementation changes.
Do not run Context Gathering, Plan, Generate, Evaluate, `verify-task.py`, `run-phases.py`, or `review-phase-plan.py`.

Pre-approval state artifacts live under `.codex/harness/sessions`, and the launcher owns writing them.
Do not use shell commands or file-edit tools to create `questions.md` or `docs-approval-request.md`.
Instead, return the requested structured final output with:

- `artifact.path`: `{rel(run_dir / "questions.md", root)}` for `questions_needed`, or `{rel(run_dir / "docs-approval-request.md", root)}` for `docs_approval_needed`.
- `artifact.content`: the full Markdown content for that artifact.

Artifact content requirements:

- Write in Korean.
- `questions.md` must show the actual question content, not only "논의 필요".
- For each decision question, include `추천 방향`, `트레이드오프`, and `추천 이유`.
- `docs-approval-request.md` must include the Clarify Review gate result.
- If the gate result includes a score or confidence below 100, include `점수 부족 지점` with the checklist items that lost points and why.
"""
        generate_contract = """## Generate

Generate is disabled in this launcher run.
"""
    return f"""# codex-harness launcher prompt

You are the isolated codex-harness orchestration session.

Goal: create exactly one next-state artifact.

## Language

Write user-facing Markdown artifacts and task documents in Korean unless a code identifier, command, file path, API name, or source quote must remain in its original language.
When you include a score, confidence, or gate result, also explain which checklist items lowered the score and what evidence is missing or weak.

Allowed states:

- Before docs approval: questions_needed | docs_approval_needed | blocked
- After docs approval before design approval: design_approval_needed | blocked
- After docs and design approval: planned | blocked

Decision rule:

- Do not act as the parent chat.
- Do not ask the parent chat to reason through this task.
- Do not invoke `.codex/harness/scripts/start.py` again.
- If a Plan-impacting decision is not approved, do not plan.
- Before docs approval, return missing decisions through `artifact.content` for `questions.md`.
- In `questions.md`, each blocking decision must include a recommended direction, tradeoffs, and why that direction is recommended.
- After task context exists, write unresolved blocking decisions to `open-decisions.json`.
- Store approved decisions in `decisions.json`, `architecture.json`, and `dependency-policy.json`.
- When design approval is approved, write `tasks/<task-dir>/context-pack/static/design-approval.json` with `approved: true`, `approved_doc`, `approved_doc_sha256`, `approved_at`, and `approval_source`.
- Keep the response short. Files and runner proof carry the detail.

## Required Inputs

- Request file: `{rel(request_path, root)}`
- Launcher run directory: `{rel(run_dir, root)}`
- Answer files:
{answers}
- Docs approval state: `{approval}`
- Design approval state: `{design_approval}`
- Generate state: `{generate_state}`
{effort_line}

## First Steps

1. Read `{rel(skill_path, root)}`.
2. Follow the `Harness Session Mode` and outcome rules in that skill.
3. Read the request file and answer files before making any task files.
4. Treat the parent chat as unavailable context.

{interaction_contract}

{generate_contract}

## Final Output

Return only the structured final output requested by the active output schema.
Use only the status values allowed for this launcher run.
Always include `task_path`, `files_to_read_next`, `blockers`, and `artifact`.
Use `task_path: null` unless a task directory exists.
Use `artifact: null` unless returning `questions_needed` or `docs_approval_needed`.
"""


def run_codex(
    root: Path,
    prompt: str,
    run_dir: Path,
    args: argparse.Namespace,
) -> int:
    output_path = run_dir / "harness-output.jsonl"
    stderr_path = run_dir / "harness-stderr.txt"
    last_message_path = run_dir / "last-message.md"
    command = [args.codex_bin, "exec", "--json", "--output-last-message", str(last_message_path)]
    add_output_schema(command, SCHEMA_DIR / "launcher-final.schema.json")
    if args.model:
        command.extend(["--model", args.model])
    if args.reasoning_effort:
        command.extend(["-c", codex_config_value("model_reasoning_effort", args.reasoning_effort)])
    if args.yolo:
        command.append("--dangerously-bypass-approvals-and-sandbox")
    elif args.full_auto:
        command.append("--full-auto")
    command.append("-")

    env = os.environ.copy()
    env.update(
        {
            "CODEX_HARNESS_SESSION": "1",
            "CODEX_HARNESS_LAUNCH_ROOT": str(root),
            "CODEX_HARNESS_LAUNCH_DIR": str(run_dir),
            "CODEX_HARNESS_CHILD_CODEX_YOLO": "0",
        }
    )
    activity_paths = [run_dir]
    if args.docs_approved:
        activity_paths.extend([root / "docs", root / "tasks"])
    return run_codex_exec(
        command,
        cwd=root,
        prompt=prompt,
        output_path=output_path,
        stderr_path=stderr_path,
        env=env,
        idle_timeout=args.codex_idle_timeout,
        activity_paths=activity_paths,
    )


def installed_harness_script(root: Path, name: str) -> Path:
    return root / ".codex" / "harness" / "scripts" / name


def resolve_task_path(root: Path, final: dict[str, object] | None) -> Path | None:
    if final is None:
        return None
    task_path = final.get("task_path")
    if not isinstance(task_path, str) or not task_path.strip():
        return None
    resolved = (root / task_path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved if resolved.exists() else None


def read_json_object(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def design_doc_info(root: Path, task_path: Path) -> tuple[Path, str] | None:
    for filename in [DESIGN_REVIEW_DOC, DESIGN_REVIEW_WAIVER_DOC]:
        path = task_path / "docs" / filename
        if path.exists():
            return path, rel(path, root)
    return None


def design_approval_bundle(root: Path, task_path: Path, design_rel_path: str) -> list[dict[str, str]]:
    paths = [root / design_rel_path]
    for filename in ["design-contract.json", "traceability-matrix.json", "review-findings.json", "review-coverage.json"]:
        path = task_path / "context-pack" / "static" / filename
        if path.exists():
            paths.append(path)
    return sorted(
        [{"path": rel(path, root), "sha256": file_sha256(path)} for path in paths if path.exists() and path.is_file()],
        key=lambda item: item["path"],
    )


def write_design_approval(root: Path, task_path: Path) -> None:
    info = design_doc_info(root, task_path)
    if info is None:
        return
    design_path, design_rel_path = info
    bundle = design_approval_bundle(root, task_path, design_rel_path)
    active_policy = {
        key: value
        for key, value in policy_pack_metadata().items()
        if key in {"id", "schema_version", "sha256"}
    }
    approved_policies = [active_policy]
    approved_policy_entries = [{**active_policy, "status": "active"}]
    approval = {
        "schema_version": 3,
        "approved": True,
        "approved_doc": design_rel_path,
        "approved_doc_sha256": file_sha256(design_path),
        "approved_bundle": bundle,
        "approved_bundle_sha256": stable_json_sha256(bundle),
        "active_policy_pack": active_policy,
        "approved_policy_packs": approved_policies,
        "approved_policy_packs_sha256": policy_pack_lineage_sha256(approved_policies),
        "design_approval_scope_sha256": design_approval_scope_sha256(
            bundle,
            approved_policies,
            active_policy,
            approved_policy_entries,
        ),
        "approved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "approval_source": "launcher --design-approved",
    }
    path = task_path / "context-pack" / "static" / DESIGN_APPROVAL_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, approval)


def design_approval_artifacts_exist(root: Path, task_path: Path) -> bool:
    if not (root / "tasks" / "index.json").is_file():
        return False
    task_index = read_json_object(task_path / "index.json")
    if task_index is None:
        return False

    common_docs = task_index.get("common_docs")
    docs = task_index.get("docs")
    if not isinstance(common_docs, list) or not isinstance(docs, list):
        return False
    if not all(isinstance(path, str) for path in common_docs + docs):
        return False

    for raw_path in MANDATORY_COMMON_DOCS:
        if raw_path not in common_docs or not (root / raw_path).is_file():
            return False

    task_dir = task_path.name
    for filename in MANDATORY_TASK_DOCS:
        raw_path = f"tasks/{task_dir}/docs/{filename}"
        if raw_path not in docs or not (root / raw_path).is_file():
            return False

    review_path = f"tasks/{task_dir}/docs/{DESIGN_REVIEW_DOC}"
    waiver_path = f"tasks/{task_dir}/docs/{DESIGN_REVIEW_WAIVER_DOC}"
    if review_path in docs:
        design_doc_exists = (root / review_path).is_file()
    elif waiver_path in docs:
        design_doc_exists = (root / waiver_path).is_file()
    else:
        design_doc_exists = False
    if not design_doc_exists:
        return False

    static_dir = task_path / "context-pack" / "static"
    return all((static_dir / filename).is_file() for filename in MANDATORY_STATIC_FILES)


def run_phases(root: Path, task_path: Path, run_dir: Path, args: argparse.Namespace) -> int:
    output_path = run_dir / "run-phases-output.txt"
    stderr_path = run_dir / "run-phases-stderr.txt"
    command = [
        sys.executable,
        str(installed_harness_script(root, "run-phases.py")),
        rel(task_path, root),
        "--root",
        str(root),
        "--codex-bin",
        args.codex_bin,
        "--codex-idle-timeout",
        str(args.codex_idle_timeout),
    ]
    if args.full_auto:
        command.append("--full-auto")
    if args.evaluate:
        command.append("--evaluate")
    if args.yolo:
        command.append("--yolo")
    if getattr(args, "strict_current_harness", False):
        command.append("--strict-current-harness")

    with output_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        result = subprocess.run(command, cwd=root, text=True, stdout=stdout, stderr=stderr, check=False)
    return int(result.returncode)


def run_phases_dry_run(root: Path, task_path: Path, run_dir: Path, args: argparse.Namespace) -> int:
    output_path = run_dir / "run-phases-dry-run-output.txt"
    stderr_path = run_dir / "run-phases-dry-run-stderr.txt"
    command = [
        sys.executable,
        str(installed_harness_script(root, "run-phases.py")),
        rel(task_path, root),
        "--root",
        str(root),
        "--dry-run",
    ]
    if getattr(args, "strict_current_harness", False):
        command.append("--strict-current-harness")
    with output_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        result = subprocess.run(command, cwd=root, text=True, stdout=stdout, stderr=stderr, check=False)
    return int(result.returncode)


def verify_task(root: Path, task_path: Path, run_dir: Path, strict_current_harness: bool = False) -> int:
    output_path = run_dir / "verify-task-output.txt"
    stderr_path = run_dir / "verify-task-stderr.txt"
    command = [
        sys.executable,
        str(installed_harness_script(root, "verify-task.py")),
        rel(task_path, root),
        "--root",
        str(root),
        "--require-design-approval",
    ]
    if strict_current_harness:
        command.append("--strict-current-harness")
    with output_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        result = subprocess.run(command, cwd=root, text=True, stdout=stdout, stderr=stderr, check=False)
    return int(result.returncode)


def review_phase_plan(root: Path, task_path: Path, run_dir: Path) -> int:
    output_path = run_dir / "phase-plan-review-output.txt"
    stderr_path = run_dir / "phase-plan-review-stderr.txt"
    command = [
        sys.executable,
        str(installed_harness_script(root, "review-phase-plan.py")),
        rel(task_path, root),
        "--root",
        str(root),
    ]
    with output_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        result = subprocess.run(command, cwd=root, text=True, stdout=stdout, stderr=stderr, check=False)
    return int(result.returncode)


def generate_relationship_graph(root: Path, task_path: Path | None) -> dict[str, object] | None:
    if task_path is None:
        return None
    from relationship_graph import write_relationship_graph_outputs

    return write_relationship_graph_outputs(root, task_path)


def write_json(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def skill_version(skill_path: Path) -> str | None:
    try:
        text = skill_path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"(?m)^version:\s*['\"]?([^'\"\n]+)", text)
    if not match:
        return None
    return match.group(1).strip()


def harness_skill_path(root: Path) -> Path | None:
    installed = root / ".codex" / "harness" / "scripts" / "skill" / "SKILL.md"
    if installed.exists():
        return installed
    legacy_installed = root / "scripts" / "harness" / "skill" / "SKILL.md"
    if legacy_installed.exists():
        return legacy_installed
    if not (root / "scripts" / "install-codex-harness.py").exists():
        return None
    source_tree = root / ".agents" / "skills" / "codex-harness" / "SKILL.md"
    if source_tree.exists():
        return source_tree
    return None


def harness_install_errors(root: Path) -> list[str]:
    required_paths = [
        root / "codex-harness.json",
        root / ".codex" / "harness" / "scripts" / "artifact_io.py",
        root / ".codex" / "harness" / "scripts" / "codex_exec.py",
        root / ".codex" / "harness" / "scripts" / "command_policy.py",
        root / ".codex" / "harness" / "scripts" / "design_contract.py",
        root / ".codex" / "harness" / "scripts" / "env_policy.py",
        root / ".codex" / "harness" / "scripts" / "evidence_obligations.py",
        root / ".codex" / "harness" / "scripts" / "harness_attestation.py",
        root / ".codex" / "harness" / "scripts" / "obligation_ledger.py",
        root / ".codex" / "harness" / "scripts" / "policy_lineage.py",
        root / ".codex" / "harness" / "scripts" / "policy_pack.py",
        root / ".codex" / "harness" / "scripts" / "redaction.py",
        root / ".codex" / "harness" / "scripts" / "reference_resolver.py",
        root / ".codex" / "harness" / "scripts" / "start.py",
        root / ".codex" / "harness" / "scripts" / "run-phases.py",
        root / ".codex" / "harness" / "scripts" / "verify-task.py",
        root / ".codex" / "harness" / "scripts" / "review-phase-plan.py",
        root / ".codex" / "harness" / "scripts" / "relationship_graph.py",
        root / ".codex" / "harness" / "scripts" / "gen-relationship-graph.py",
    ]
    missing_required = [str(path.relative_to(root)) for path in required_paths if not path.exists()]
    if missing_required:
        return [
            "codex-harness is not installed in this project. Missing: "
            + ", ".join(missing_required)
        ]

    errors: list[str] = []
    try:
        manifest = json.loads((root / "codex-harness.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"Invalid codex-harness.json: {exc}")
    else:
        manifest_version = manifest.get("version")
        if manifest_version != HARNESS_VERSION:
            errors.append(
                "codex-harness version mismatch: "
                f"launcher={HARNESS_VERSION}, manifest={manifest_version or '(missing)'}."
            )

    skill_path = harness_skill_path(root)
    if skill_path is None:
        errors.append("Missing harness skill instructions: .codex/harness/scripts/skill/SKILL.md")
        return errors

    declared_skill_version = skill_version(skill_path)
    if declared_skill_version != HARNESS_VERSION:
        errors.append(
            "codex-harness skill version mismatch: "
            f"launcher={HARNESS_VERSION}, skill={declared_skill_version or '(missing)'}."
        )
    return errors


def launcher_status(run_dir: Path, returncode: int | None, dry_run: bool) -> str:
    if dry_run:
        return "dry_run"
    if returncode != 0:
        return "failed"
    if (run_dir / "questions.md").exists():
        return "questions_needed"
    if (run_dir / "docs-approval-request.md").exists():
        return "docs_approval_needed"
    return "completed"


def parse_last_message(path: Path) -> dict[str, object] | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def materialize_preapproval_artifact(run_dir: Path, final: dict[str, object] | None) -> None:
    if final is None:
        return
    status = final.get("status")
    expected_name = {
        "questions_needed": "questions.md",
        "docs_approval_needed": "docs-approval-request.md",
    }.get(status)
    if expected_name is None:
        return
    target = run_dir / expected_name
    if target.exists():
        return
    artifact = final.get("artifact")
    if not isinstance(artifact, dict):
        return
    content = artifact.get("content")
    if not isinstance(content, str) or not content.strip():
        return
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def resolve_document_path(root: Path, raw_path: object) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    lowered = raw_path.lower()
    if any(marker in lowered for marker in [".env", ".ssh", "secret", "password", "token", "private_key"]):
        return None
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved


def append_document_path(paths: list[Path], path: Path | None) -> None:
    if path is None:
        return
    if path not in paths:
        paths.append(path)


def visible_document_paths(root: Path, run_dir: Path, final: dict[str, object] | None) -> list[Path]:
    paths: list[Path] = []
    append_document_path(paths, run_dir / "questions.md")
    append_document_path(paths, run_dir / "docs-approval-request.md")
    if final is None:
        return paths

    files_to_read_next = final.get("files_to_read_next")
    if isinstance(files_to_read_next, list):
        for raw_path in files_to_read_next:
            append_document_path(paths, resolve_document_path(root, raw_path))

    artifact = final.get("artifact")
    if isinstance(artifact, dict):
        append_document_path(paths, resolve_document_path(root, artifact.get("path")))

    task_path = resolve_task_path(root, final)
    if final.get("status") == "design_approval_needed" and task_path is not None:
        append_document_path(paths, task_path / "docs" / DESIGN_REVIEW_DOC)
        append_document_path(paths, task_path / "docs" / DESIGN_REVIEW_WAIVER_DOC)
    return paths


def document_result(root: Path, path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        relative = rel(path, root)
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    truncated = len(content) > DOCUMENT_RESULT_MAX_CHARS
    if truncated:
        content = content[:DOCUMENT_RESULT_MAX_CHARS] + "\n\n[truncated]\n"
    return {
        "path": relative,
        "content": content,
        "truncated": truncated,
    }


def visible_documents(root: Path, run_dir: Path, final: dict[str, object] | None) -> list[dict[str, object]]:
    documents: list[dict[str, object]] = []
    seen: set[str] = set()
    for path in visible_document_paths(root, run_dir, final):
        item = document_result(root, path)
        if item is None:
            continue
        item_path = str(item["path"])
        if item_path in seen:
            continue
        seen.add(item_path)
        documents.append(item)
    return documents


def launcher_status_from_final(root: Path, run_dir: Path, final: dict[str, object] | None) -> str | None:
    if final is None:
        return None
    status = final.get("status")
    if status not in {"questions_needed", "docs_approval_needed", "design_approval_needed", "planned", "generated", "blocked"}:
        return None
    if status == "questions_needed":
        return "questions_needed" if (run_dir / "questions.md").exists() else "blocked"
    if status == "docs_approval_needed":
        return "docs_approval_needed" if (run_dir / "docs-approval-request.md").exists() else "blocked"
    if status == "design_approval_needed":
        task_path = resolve_task_path(root, final)
        if task_path is None:
            return "blocked"
        return status if design_approval_artifacts_exist(root, task_path) else "blocked"
    if status in {"planned", "generated"}:
        return status if resolve_task_path(root, final) is not None else "blocked"
    return "blocked"


def create_run_dir(root: Path, request: str) -> Path:
    base = root / ".codex" / "harness" / "sessions" / f"{now_id()}-{slugify(request)}"
    for suffix in ["", *[f"-{index}" for index in range(1, 100)]]:
        run_dir = Path(f"{base}{suffix}")
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
            return run_dir
        except FileExistsError:
            continue
    raise FileExistsError(f"Could not create unique launcher run directory under {base.parent}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    parser.add_argument("--request-file", help="Request file path. Use '-' to read stdin.")
    parser.add_argument("--request", help="Request text.")
    parser.add_argument("--answer-file", action="append", default=[], help="Additional answer/context file.")
    parser.add_argument("--docs-approved", action="store_true", help="Allow the harness session to create docs.")
    parser.add_argument("--design-approved", action="store_true", help="Allow the harness session to create phase plans after implementation design approval.")
    parser.add_argument("--run-phases", action="store_true", help="Tell the harness session to run Generate.")
    parser.add_argument("--evaluate", action="store_true", help="Tell the harness session to evaluate after Generate.")
    parser.add_argument("--codex-bin", default="codex", help="Codex executable.")
    parser.add_argument("--model", help="Model for the harness session.")
    parser.add_argument(
        "--reasoning-effort",
        default="high",
        help="Reasoning effort for the harness session. Use an empty value to inherit config.",
    )
    parser.add_argument("--full-auto", action="store_true", help="Pass --full-auto to codex exec.")
    parser.add_argument(
        "--codex-idle-timeout",
        type=int,
        default=300,
        help="Fail codex exec after this many seconds with no activity. Use 0 to disable.",
    )
    parser.add_argument(
        "--yolo",
        action="store_true",
        help="Pass --dangerously-bypass-approvals-and-sandbox to codex exec.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Write launcher files without running Codex.")
    parser.add_argument("--strict-current-harness", action="store_true", help="Require current harness runtime metadata.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"[ERROR] Root directory does not exist: {root}", file=sys.stderr)
        return 1
    install_errors = harness_install_errors(root)
    if install_errors:
        print("[ERROR] Invalid codex-harness installation:", file=sys.stderr)
        for error in install_errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    skill_path = harness_skill_path(root)
    if skill_path is None:
        print("[ERROR] Missing harness skill instructions.", file=sys.stderr)
        return 1

    try:
        request = read_request(args).strip()
    except (OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    if not request:
        print("[ERROR] Request is empty.", file=sys.stderr)
        return 1

    answer_paths = [Path(path).expanduser().resolve() for path in args.answer_file]
    missing_answers = [str(path) for path in answer_paths if not path.exists()]
    if missing_answers:
        print("[ERROR] Missing answer file(s): " + ", ".join(missing_answers), file=sys.stderr)
        return 1

    run_dir = create_run_dir(root, request)
    request_path = run_dir / "request.md"
    request_path.write_text(request.rstrip() + "\n", encoding="utf-8")

    reasoning_effort = args.reasoning_effort or None
    prompt = build_prompt(
        root,
        run_dir,
        skill_path,
        request_path,
        answer_paths,
        args.docs_approved,
        args.design_approved,
        args.run_phases,
        reasoning_effort,
    )
    prompt_path = run_dir / "harness-prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")

    returncode: int | None = None
    before_snapshot: dict[str, str] | None = None
    protocol_violations: list[str] = []
    if not args.dry_run and not args.docs_approved:
        before_snapshot = worktree_snapshot(root)

    if not args.dry_run:
        returncode = run_codex(root, prompt, run_dir, args)

    final_output = parse_last_message(run_dir / "last-message.md")
    materialize_preapproval_artifact(run_dir, final_output)

    if before_snapshot is not None:
        after_snapshot = worktree_snapshot(root)
        protocol_violations = [
            path
            for path in changed_paths(before_snapshot, after_snapshot)
            if not launcher_allowed_change(path, run_dir, root)
        ]
        if protocol_violations:
            write_json(
                run_dir / "protocol-violation.json",
                {
                    "status": "protocol_violation",
                    "reason": "Docs approval is required before changing files outside the launcher run directory.",
                    "changed_files": protocol_violations,
                },
            )

    final_status = launcher_status_from_final(root, run_dir, final_output)
    if args.docs_approved and not args.design_approved and final_output and final_output.get("status") in {"planned", "generated"}:
        final_status = "blocked"
        write_json(
            run_dir / "orchestration-violation.json",
            {
                "status": "orchestration_violation",
                "reason": "Implementation design approval is required before planned or generated states.",
            },
        )
    elif args.docs_approved and final_output and final_output.get("status") == "generated":
        final_status = "blocked"
        write_json(
            run_dir / "orchestration-violation.json",
            {
                "status": "orchestration_violation",
                "reason": "Generate is runner-owned. The launcher Codex session must stop at planned.",
            },
        )
    verifier_returncode: int | None = None
    if (
        args.docs_approved
        and args.design_approved
        and not args.dry_run
        and returncode == 0
        and final_status == "planned"
    ):
        task_path = resolve_task_path(root, final_output)
        if task_path is None:
            final_status = "blocked"
        else:
            write_design_approval(root, task_path)
            verifier_returncode = verify_task(root, task_path, run_dir, args.strict_current_harness)
            if verifier_returncode != 0:
                final_status = "blocked"
                write_json(
                    run_dir / "orchestration-violation.json",
                    {
                        "status": "orchestration_violation",
                        "reason": "Task verification must pass before the launcher can accept planned state.",
                        "verifier_returncode": verifier_returncode,
                    },
                )

    phase_plan_review_returncode: int | None = None
    dry_run_returncode: int | None = None
    if (
        args.docs_approved
        and args.design_approved
        and not args.dry_run
        and not protocol_violations
        and returncode == 0
        and final_status == "planned"
    ):
        task_path = resolve_task_path(root, final_output)
        if task_path is None:
            final_status = "blocked"
        else:
            phase_plan_review_returncode = review_phase_plan(root, task_path, run_dir)
            if phase_plan_review_returncode != 0:
                final_status = "blocked"
                write_json(
                    run_dir / "orchestration-violation.json",
                    {
                        "status": "orchestration_violation",
                        "reason": "Phase plan semantic review must pass before the launcher can accept planned state.",
                        "phase_plan_review_returncode": phase_plan_review_returncode,
                    },
                )

    if (
        args.docs_approved
        and args.design_approved
        and not args.dry_run
        and not protocol_violations
        and returncode == 0
        and final_status == "planned"
    ):
        task_path = resolve_task_path(root, final_output)
        if task_path is None:
            final_status = "blocked"
        else:
            dry_run_returncode = run_phases_dry_run(root, task_path, run_dir, args)
            if dry_run_returncode != 0:
                final_status = "blocked"
                write_json(
                    run_dir / "orchestration-violation.json",
                    {
                        "status": "orchestration_violation",
                        "reason": "Phase runner dry-run must pass before the launcher can accept planned state.",
                        "dry_run_returncode": dry_run_returncode,
                    },
                )

    runner_returncode: int | None = None
    if (
        args.run_phases
        and not args.dry_run
        and not protocol_violations
        and returncode == 0
        and final_status == "planned"
    ):
        task_path = resolve_task_path(root, final_output)
        if task_path is None:
            final_status = "blocked"
        else:
            runner_returncode = run_phases(root, task_path, run_dir, args)
            final_status = "generated" if runner_returncode == 0 else "blocked"

    relationship_graph: dict[str, object] | None = None
    if not args.dry_run and final_status in {"planned", "generated"}:
        relationship_graph = generate_relationship_graph(root, resolve_task_path(root, final_output))

    result = {
        "status": "protocol_violation"
        if protocol_violations
        else (final_status or launcher_status(run_dir, returncode, args.dry_run)),
        "returncode": returncode,
        "verifier_returncode": verifier_returncode,
        "phase_plan_review_returncode": phase_plan_review_returncode,
        "dry_run_returncode": dry_run_returncode,
        "runner_returncode": runner_returncode,
        "run_dir": rel(run_dir, root),
        "request": rel(request_path, root),
        "prompt": rel(prompt_path, root),
        "last_message": rel(run_dir / "last-message.md", root),
        "output": rel(run_dir / "harness-output.jsonl", root),
        "stderr": rel(run_dir / "harness-stderr.txt", root),
        "run_phases_output": rel(run_dir / "run-phases-output.txt", root),
        "run_phases_stderr": rel(run_dir / "run-phases-stderr.txt", root),
        "run_phases_dry_run_output": rel(run_dir / "run-phases-dry-run-output.txt", root),
        "run_phases_dry_run_stderr": rel(run_dir / "run-phases-dry-run-stderr.txt", root),
        "verify_task_output": rel(run_dir / "verify-task-output.txt", root),
        "verify_task_stderr": rel(run_dir / "verify-task-stderr.txt", root),
        "phase_plan_review_output": rel(run_dir / "phase-plan-review-output.txt", root),
        "phase_plan_review_stderr": rel(run_dir / "phase-plan-review-stderr.txt", root),
        "relationship_graph": relationship_graph,
        "documents": visible_documents(root, run_dir, final_output),
        "questions": rel(run_dir / "questions.md", root),
        "docs_approval_request": rel(run_dir / "docs-approval-request.md", root),
        "orchestration_violation": rel(run_dir / "orchestration-violation.json", root),
        "protocol_violations": protocol_violations,
    }
    write_json(run_dir / "launcher-result.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if protocol_violations:
        return 1
    if runner_returncode is not None and runner_returncode != 0:
        return runner_returncode
    return 0 if returncode in (None, 0) else int(returncode)


if __name__ == "__main__":
    raise SystemExit(main())
