#!/usr/bin/env python3
"""Launch a codex-harness orchestration session outside the parent chat."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from codex_exec import add_output_schema, run_codex_exec


SKIP_SNAPSHOT_DIRS = {
    ".git",
    ".codex-harness",
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
HARNESS_VERSION = "0.1.0"
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"


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
                if entry.name not in SKIP_SNAPSHOT_DIRS:
                    stack.append(Path(entry.path))
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
    run_phases: bool,
    evaluate: bool,
    full_auto: bool,
    reasoning_effort: str | None,
) -> str:
    answers = "\n".join(f"  - `{rel(path, root)}`" for path in answer_paths) or "  - 없음"
    approval = "approved" if docs_approved else "not_approved"
    phase_command = "python3 scripts/harness/run-phases.py <task-dir>"
    if full_auto:
        phase_command += " --full-auto"
    if evaluate:
        phase_command += " --evaluate"
    generate_state = "requested" if run_phases else "not_requested"
    effort_line = (
        f"- Harness session reasoning effort is forced to `{reasoning_effort}` by the launcher."
        if reasoning_effort
        else "- Harness session reasoning effort follows the active Codex config."
    )
    if docs_approved:
        interaction_contract = f"""## Allowed Next State

Docs are approved in this launcher run.

Produce `planned`, `generated`, or `blocked`.

Required before `planned`:

- Mandatory task docs and context-pack files exist.
- `decisions.json`, `architecture.json`, and `dependency-policy.json` contain the approved implementation-shaping decisions.
- `open-decisions.json` has no blocking open item.
- Phase contracts reference only approved decisions and architecture refs.
- `python3 scripts/harness/verify-task.py <task-dir>` passes.
- `python3 scripts/harness/run-phases.py <task-dir> --dry-run` passes.
"""
        generate_contract = f"""## Generate

Run Generate only when phase files are valid and Generate state is `requested`.

If Generate state is `not_requested`, stop after docs, context gathering, planning, `verify-task.py`, and `run-phases.py --dry-run`.

Use this command shape:

```bash
{phase_command}
```
"""
    else:
        interaction_contract = f"""## Allowed Next State

Docs are not approved in this launcher run.

Produce exactly one of these:

- `questions_needed`: write `{rel(run_dir / "questions.md", root)}` when a blocking decision is missing.
- `docs_approval_needed`: write `{rel(run_dir / "docs-approval-request.md", root)}` when Clarify and Review pass.

Do not create task docs, task indexes, context-pack files, phase files, or implementation changes.
Do not run Context Gathering, Plan, Generate, Evaluate, `verify-task.py`, or `run-phases.py`.
"""
        generate_contract = """## Generate

Generate is disabled in this launcher run.
"""
    return f"""# codex-harness launcher prompt

You are the isolated codex-harness orchestration session.

Goal: create exactly one next-state artifact.

Allowed states:

- questions_needed
- docs_approval_needed
- planned
- generated
- blocked

Decision rule:

- Do not act as the parent chat.
- Do not ask the parent chat to reason through this task.
- Do not invoke `scripts/harness/start.py` again.
- If a Plan-impacting decision is not approved, do not plan.
- Before docs approval, write missing decisions to `questions.md`.
- After task context exists, write unresolved blocking decisions to `open-decisions.json`.
- Store approved decisions in `decisions.json`, `architecture.json`, and `dependency-policy.json`.
- Keep the response short. Files and runner proof carry the detail.

## Required Inputs

- Request file: `{rel(request_path, root)}`
- Launcher run directory: `{rel(run_dir, root)}`
- Answer files:
{answers}
- Docs approval state: `{approval}`
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
Use status: questions_needed | docs_approval_needed | planned | generated | blocked.
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
    installed = root / "scripts" / "harness" / "skill" / "SKILL.md"
    if installed.exists():
        return installed
    if not (root / "scripts" / "install-codex-harness.py").exists():
        return None
    source_tree = root / ".agents" / "skills" / "codex-harness" / "SKILL.md"
    if source_tree.exists():
        return source_tree
    return None


def harness_install_errors(root: Path) -> list[str]:
    required_paths = [
        root / "codex-harness.json",
        root / "scripts" / "harness" / "start.py",
        root / "scripts" / "harness" / "run-phases.py",
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
        errors.append("Missing harness skill instructions: scripts/harness/skill/SKILL.md")
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


def create_run_dir(root: Path, request: str) -> Path:
    base = root / ".codex-harness" / "sessions" / f"{now_id()}-{slugify(request)}"
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
        args.run_phases,
        args.evaluate,
        args.full_auto,
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

    result = {
        "status": "protocol_violation"
        if protocol_violations
        else launcher_status(run_dir, returncode, args.dry_run),
        "returncode": returncode,
        "run_dir": rel(run_dir, root),
        "request": rel(request_path, root),
        "prompt": rel(prompt_path, root),
        "last_message": rel(run_dir / "last-message.md", root),
        "output": rel(run_dir / "harness-output.jsonl", root),
        "stderr": rel(run_dir / "harness-stderr.txt", root),
        "questions": rel(run_dir / "questions.md", root),
        "docs_approval_request": rel(run_dir / "docs-approval-request.md", root),
        "protocol_violations": protocol_violations,
    }
    write_json(run_dir / "launcher-result.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if protocol_violations:
        return 1
    return 0 if returncode in (None, 0) else int(returncode)


if __name__ == "__main__":
    raise SystemExit(main())
