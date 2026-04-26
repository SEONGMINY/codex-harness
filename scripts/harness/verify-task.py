#!/usr/bin/env python3
"""Verify harness task artifacts and runtime proof."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from phase_contract import (
    contract_acceptance_commands,
    contract_required_outputs,
    parse_phase_contract,
    scope_violations,
    validate_phase_contract,
)


MANDATORY_STATIC_FILES = [
    "original-prompt.md",
    "product.md",
    "decisions.md",
    "rejected-options.md",
    "constraints.md",
    "test-policy.md",
    "clarify-review.md",
    "docs-approval.md",
    "context-gathering.md",
    "docs-index.md",
]
MANDATORY_TASK_DOCS = [
    "prd.md",
    "flow.md",
    "data-schema.md",
    "code-architecture.md",
    "adr.md",
]
PLACEHOLDER_PATTERNS = [
    re.compile(r"^\s*TODO\b", re.MULTILINE),
    re.compile(r"\[TODO", re.IGNORECASE),
    re.compile(r"PLACEHOLDER", re.IGNORECASE),
]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_task_path(root: Path, task_arg: str) -> Path:
    candidate = Path(task_arg)
    if candidate.is_absolute() and candidate.is_dir():
        return candidate
    if candidate.is_dir():
        return candidate.resolve()
    task_path = root / "tasks" / task_arg
    if task_path.is_dir():
        return task_path
    raise FileNotFoundError(f"Task directory not found: {task_arg}")


def has_placeholder(text: str) -> bool:
    return any(pattern.search(text) for pattern in PLACEHOLDER_PATTERNS)


def rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def require_file(
    root: Path,
    path: Path,
    label: str,
    check_placeholder: bool = True,
    allow_empty: bool = False,
) -> list[str]:
    if not path.exists():
        return [f"Missing {label}: {rel(root, path)}"]
    if not path.is_file():
        return [f"Not a file: {rel(root, path)}"]
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    errors = []
    if not text and not allow_empty:
        errors.append(f"Empty {label}: {rel(root, path)}")
    if check_placeholder and has_placeholder(text):
        errors.append(f"Placeholder remains in {label}: {rel(root, path)}")
    return errors


def resolve_task_relative_path(
    root: Path,
    task_path: Path,
    raw_path: str,
    label: str,
) -> tuple[Path | None, list[str]]:
    path = Path(raw_path)
    if path.is_absolute():
        return None, [f"`{label}` must be relative to the task directory: {raw_path}"]

    target = (task_path / path).resolve()
    task_root = task_path.resolve()
    try:
        target.relative_to(task_root)
    except ValueError:
        return None, [f"`{label}` must not escape the task directory: {raw_path}"]
    return target, []


def phase_ac_commands(markdown: str) -> list[str]:
    match = re.search(
        r"## Acceptance Criteria(?P<body>.*?)(?:\n## |\Z)",
        markdown,
        flags=re.DOTALL,
    )
    if not match:
        return []
    commands: list[str] = []
    for block in re.findall(r"```(?:bash|sh|shell)?\n(.*?)```", match.group("body"), re.DOTALL):
        for line in block.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and stripped != "TODO":
                commands.append(stripped)
    return commands


def expected_ac_commands(phase: dict, markdown: str) -> list[str]:
    contract, _ = parse_phase_contract(markdown)
    if contract is not None:
        commands = contract_acceptance_commands(contract)
        if commands:
            return commands
    commands = list(phase.get("ac_commands") or [])
    commands.extend(phase_ac_commands(markdown))
    unique_commands = []
    seen = set()
    for command in commands:
        if not command or command == "TODO" or command in seen:
            continue
        seen.add(command)
        unique_commands.append(command)
    return unique_commands


def expected_required_outputs(phase: dict, markdown: str) -> list[str]:
    contract, _ = parse_phase_contract(markdown)
    if contract is not None:
        outputs = contract_required_outputs(contract)
        if outputs:
            return outputs
    return list(phase.get("required_outputs") or [])


def phase_attempts(phase: dict) -> list[int]:
    attempts = phase.get("attempts")
    if isinstance(attempts, int) and attempts > 0:
        return [attempts]
    return [1]


def require_string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        return [f"`{field}` must be a list."]
    if not all(isinstance(item, str) for item in value):
        return [f"`{field}` entries must be strings."]
    return []


def validate_commands_run(value: object, expected_commands: list[str]) -> list[str]:
    if not isinstance(value, list):
        return ["`commands_run` must be a list."]
    errors: list[str] = []
    if not value:
        errors.append("`commands_run` must not be empty.")
    actual_commands = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"`commands_run[{index}]` must be an object.")
            continue
        if not isinstance(item.get("command"), str) or not item.get("command", "").strip():
            errors.append(f"`commands_run[{index}].command` must be a non-empty string.")
        else:
            actual_commands.append(item["command"])
        if not isinstance(item.get("exit_code"), int):
            errors.append(f"`commands_run[{index}].exit_code` must be an integer.")
        elif item.get("exit_code") != 0:
            errors.append(f"`commands_run[{index}].exit_code` must be 0 for a completed phase.")
    if actual_commands != expected_commands:
        errors.append(
            "`commands_run` must match phase AC commands. "
            f"expected={expected_commands!r} actual={actual_commands!r}"
        )
    return errors


def validate_required_outputs(
    root: Path,
    task_path: Path,
    value: object,
    expected_outputs: list[str],
) -> list[str]:
    if not isinstance(value, list):
        return ["`required_outputs` must be a list."]
    errors: list[str] = []
    actual_outputs = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"`required_outputs[{index}]` must be an object.")
            continue
        if not isinstance(item.get("path"), str) or not item.get("path", "").strip():
            errors.append(f"`required_outputs[{index}].path` must be a non-empty string.")
            continue
        raw_path = item["path"]
        actual_outputs.append(raw_path)
        if item.get("exists") is not True:
            errors.append(f"`required_outputs[{index}].exists` must be true.")
        target, path_errors = resolve_task_relative_path(
            root,
            task_path,
            raw_path,
            f"required_outputs[{index}].path",
        )
        errors.extend(path_errors)
        if target is not None and not target.exists():
            errors.append(f"`required_outputs[{index}].path` does not exist: {rel(root, target)}")
    if actual_outputs != expected_outputs:
        errors.append(
            "`required_outputs` must match phase required_outputs. "
            f"expected={expected_outputs!r} actual={actual_outputs!r}"
        )
    return errors


def validate_artifacts(
    root: Path,
    task_path: Path,
    value: object,
    phase_number: int,
    attempt: int | None,
) -> list[str]:
    if not isinstance(value, dict):
        return ["`artifacts` must be an object."]
    errors: list[str] = []
    expected_paths = {
        "prompt": f"context-pack/runtime/phase{phase_number}-prompt.md",
        "handoff": f"context-pack/handoffs/phase{phase_number}.md",
    }
    if attempt is not None:
        expected_paths.update(
            {
                "stdout": f"context-pack/runtime/phase{phase_number}-output-attempt{attempt}.jsonl",
                "stderr": f"context-pack/runtime/phase{phase_number}-stderr-attempt{attempt}.txt",
                "ac_results": f"context-pack/runtime/phase{phase_number}-ac-attempt{attempt}.json",
            }
        )
    for key in ["prompt", "stdout", "stderr", "ac_results", "handoff"]:
        raw_path = value.get(key)
        if not isinstance(raw_path, str) or not raw_path.strip():
            errors.append(f"`artifacts.{key}` must be a non-empty string.")
            continue
        if key in expected_paths and raw_path != expected_paths[key]:
            errors.append(f"`artifacts.{key}` must be {expected_paths[key]}.")
        target, path_errors = resolve_task_relative_path(root, task_path, raw_path, f"artifacts.{key}")
        errors.extend(path_errors)
        if target is None:
            continue
        allow_empty = key == "stderr"
        errors.extend(
            require_file(
                root,
                target,
                f"phase result artifact {key}",
                check_placeholder=False,
                allow_empty=allow_empty,
            )
        )
    return errors


def validate_phase_gate(root: Path, path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        gate = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid phase gate JSON: {rel(root, path)}: {exc}"]
    if not isinstance(gate, dict):
        return [f"Phase gate must be a JSON object: {rel(root, path)}"]
    if gate.get("status") != "passed":
        return [f'Phase gate status must be "passed": {rel(root, path)}']
    checks = gate.get("checks")
    if not isinstance(checks, list) or not checks:
        return [f"Phase gate must include checks: {rel(root, path)}"]
    return []


def validate_phase_reconciliation(root: Path, path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        reconciliation = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid phase reconciliation JSON: {rel(root, path)}: {exc}"]
    if not isinstance(reconciliation, dict):
        return [f"Phase reconciliation must be a JSON object: {rel(root, path)}"]
    if reconciliation.get("status") != "satisfied":
        return [f'Phase reconciliation status must be "satisfied": {rel(root, path)}']
    if not isinstance(reconciliation.get("instruction_results"), list):
        return [f"Phase reconciliation must include instruction_results: {rel(root, path)}"]
    return []


def required_output_repo_paths(task_path: Path, required_outputs: list[str]) -> list[str]:
    return [f"tasks/{task_path.name}/{raw_path.strip('/')}" for raw_path in required_outputs]


def contract_allowed_paths(contract: dict) -> list[str]:
    scope = contract.get("scope")
    if not isinstance(scope, dict):
        return []
    values = scope.get("allowed_paths")
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, str) and item.strip()]


def validate_runtime_contract_bundle(
    root: Path,
    task_path: Path,
    phase_number: int,
    expected_commands: list[str],
    expected_outputs: list[str],
) -> list[str]:
    runtime_dir = task_path / "context-pack" / "runtime"
    contract_path = runtime_dir / f"phase{phase_number}-contract.json"
    evidence_path = runtime_dir / f"phase{phase_number}-evidence.json"
    reconciliation_path = runtime_dir / f"phase{phase_number}-reconciliation.json"
    gate_path = runtime_dir / f"phase{phase_number}-gate.json"
    errors: list[str] = []

    try:
        contract = read_json(contract_path)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return [f"Cannot read phase runtime contract: {rel(root, contract_path)}: {exc}"]
    try:
        evidence = read_json(evidence_path)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return [f"Cannot read phase evidence: {rel(root, evidence_path)}: {exc}"]
    try:
        reconciliation = read_json(reconciliation_path)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return [f"Cannot read phase reconciliation: {rel(root, reconciliation_path)}: {exc}"]
    try:
        gate = read_json(gate_path)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return [f"Cannot read phase gate: {rel(root, gate_path)}: {exc}"]

    if contract_acceptance_commands(contract) != expected_commands:
        errors.append(
            "Runtime contract acceptance_commands must match phase contract. "
            f"expected={expected_commands!r} actual={contract_acceptance_commands(contract)!r}"
        )
    if contract_required_outputs(contract) != expected_outputs:
        errors.append(
            "Runtime contract required_outputs must match phase contract. "
            f"expected={expected_outputs!r} actual={contract_required_outputs(contract)!r}"
        )

    commands = evidence.get("commands") if isinstance(evidence, dict) else None
    actual_commands = [
        item.get("command")
        for item in commands or []
        if isinstance(item, dict)
    ]
    if actual_commands != expected_commands:
        errors.append(
            "Evidence commands must match phase contract. "
            f"expected={expected_commands!r} actual={actual_commands!r}"
        )

    output_entries = evidence.get("required_outputs") if isinstance(evidence, dict) else None
    actual_outputs = [
        item.get("path")
        for item in output_entries or []
        if isinstance(item, dict)
    ]
    if actual_outputs != expected_outputs:
        errors.append(
            "Evidence required_outputs must match phase contract. "
            f"expected={expected_outputs!r} actual={actual_outputs!r}"
        )

    changed_files = evidence.get("changed_files") if isinstance(evidence, dict) else []
    if not isinstance(changed_files, list) or not all(isinstance(item, str) for item in changed_files):
        errors.append("Evidence changed_files must be a string list.")
        changed_files = []
    violations = scope_violations(
        changed_files,
        contract_allowed_paths(contract),
        required_output_repo_paths(task_path, expected_outputs),
    )
    if violations:
        errors.append(f"Evidence changed_files include paths outside scope: {violations!r}")

    contract_instruction_ids = [
        item.get("id")
        for item in contract.get("instructions", [])
        if isinstance(item, dict)
    ]
    reconciliation_items = reconciliation.get("instruction_results")
    actual_instruction_ids = [
        item.get("id")
        for item in reconciliation_items or []
        if isinstance(item, dict)
    ]
    if actual_instruction_ids != contract_instruction_ids:
        errors.append(
            "Reconciliation instruction ids must match contract instructions. "
            f"expected={contract_instruction_ids!r} actual={actual_instruction_ids!r}"
        )
    if any(item.get("status") != "satisfied" for item in reconciliation_items or [] if isinstance(item, dict)):
        errors.append("All reconciliation instruction results must be satisfied for a completed phase.")

    gate_checks = gate.get("checks") if isinstance(gate, dict) else []
    if not isinstance(gate_checks, list) or not gate_checks:
        errors.append("Gate checks must be a non-empty list.")
    elif any(check.get("status") != "passed" for check in gate_checks if isinstance(check, dict)):
        errors.append("All gate checks must be passed for a completed phase.")

    return errors


def validate_phase_result(
    root: Path,
    task_path: Path,
    phase_number: int,
    expected_commands: list[str],
    expected_outputs: list[str],
) -> list[str]:
    result_path = task_path / "context-pack" / "runtime" / f"phase{phase_number}-result.json"
    if not result_path.exists():
        return [f"Missing phase result: {rel(root, result_path)}"]
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid phase result JSON: {rel(root, result_path)}: {exc}"]

    if not isinstance(result, dict):
        return [f"Phase result must be a JSON object: {rel(root, result_path)}"]

    errors: list[str] = []
    required_fields = {
        "phase",
        "status",
        "attempt",
        "codex_exit_code",
        "changed_files",
        "commands_run",
        "tests_passed",
        "required_outputs",
        "artifacts",
    }
    missing = sorted(required_fields - set(result))
    if missing:
        errors.append(f"Phase result missing fields: {', '.join(missing)}")
    if result.get("phase") != phase_number:
        errors.append(f"`phase` must be {phase_number}.")
    if result.get("status") != "completed":
        errors.append('`status` must be "completed".')
    attempt = result.get("attempt")
    if not isinstance(attempt, int) or attempt <= 0:
        errors.append("`attempt` must be a positive integer.")
        attempt = None
    if result.get("codex_exit_code") != 0:
        errors.append("`codex_exit_code` must be 0 for a completed phase.")
    errors.extend(require_string_list(result.get("changed_files"), "changed_files"))
    errors.extend(validate_commands_run(result.get("commands_run"), expected_commands))
    if result.get("tests_passed") is not True:
        errors.append("`tests_passed` must be true for a completed phase.")
    errors.extend(validate_required_outputs(root, task_path, result.get("required_outputs"), expected_outputs))
    errors.extend(validate_artifacts(root, task_path, result.get("artifacts"), phase_number, attempt))
    artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), dict) else {}
    if artifacts.get("handoff") != f"context-pack/handoffs/phase{phase_number}.md":
        errors.append(f"`artifacts.handoff` must be context-pack/handoffs/phase{phase_number}.md.")
    return errors


def verify(root: Path, task_path: Path, require_evaluation: bool) -> list[str]:
    errors: list[str] = []
    task_index_path = task_path / "index.json"
    errors.extend(require_file(root, task_index_path, "task index", check_placeholder=False))
    if errors:
        return errors

    task_index = read_json(task_index_path)
    task_dir = task_path.name

    common_docs = [root / raw for raw in task_index.get("common_docs") or []]
    if not common_docs:
        errors.append("Task index must list common_docs.")
    for path in common_docs:
        errors.extend(require_file(root, path, "common doc"))

    task_docs = [root / raw for raw in task_index.get("docs") or []]
    expected_task_doc_dir = task_path / "docs"
    if len(task_docs) < len(MANDATORY_TASK_DOCS):
        errors.append("Task index must list mandatory task docs.")
    for filename in MANDATORY_TASK_DOCS:
        expected = expected_task_doc_dir / filename
        errors.extend(require_file(root, expected, "task doc"))
        if expected not in task_docs:
            errors.append(f"Task index docs must include {rel(root, expected)}")
    for path in task_docs:
        if not str(path).startswith(str(expected_task_doc_dir)):
            errors.append(f"Task-specific doc must live under {rel(root, expected_task_doc_dir)}: {rel(root, path)}")
        errors.extend(require_file(root, path, "task doc"))

    static_dir = task_path / "context-pack" / "static"
    for filename in MANDATORY_STATIC_FILES:
        errors.extend(require_file(root, static_dir / filename, "static context"))

    phase_count = int(task_index.get("totalPhases") or len(task_index.get("phases") or []))
    phases = task_index.get("phases") or []
    if phase_count != len(phases):
        errors.append("totalPhases must match phases length.")

    runtime_dir = task_path / "context-pack" / "runtime"
    handoff_dir = task_path / "context-pack" / "handoffs"
    for phase in phases:
        phase_number = int(phase["phase"])
        phase_path = task_path / "phases" / f"phase{phase_number}.md"
        errors.extend(require_file(root, phase_path, "phase file"))
        expected_commands = list(phase.get("ac_commands") or [])
        expected_outputs = list(phase.get("required_outputs") or [])
        if phase_path.exists():
            markdown = phase_path.read_text(encoding="utf-8", errors="replace")
            _, contract_errors = validate_phase_contract(
                root,
                task_path,
                phase_number,
                phase.get("name"),
                markdown,
                require_previous_outputs=phase.get("status") == "completed",
            )
            errors.extend([f"Phase {phase_number} contract: {error}" for error in contract_errors])
            expected_commands = expected_ac_commands(phase, markdown)
            expected_outputs = expected_required_outputs(phase, markdown)
            if phase.get("ac_commands") and list(phase.get("ac_commands") or []) != expected_commands:
                errors.append(
                    f"Phase {phase_number} index ac_commands must match Contract.acceptance_commands."
                )
            if phase.get("required_outputs") and list(phase.get("required_outputs") or []) != expected_outputs:
                errors.append(
                    f"Phase {phase_number} index required_outputs must match Contract.required_outputs."
                )
            if not expected_commands:
                errors.append(f"Missing AC commands for phase {phase_number}.")
            if not expected_outputs:
                errors.append(f"Missing required outputs for phase {phase_number}.")

        if phase.get("status") == "completed":
            errors.extend(require_file(root, handoff_dir / f"phase{phase_number}.md", "handoff"))
            errors.extend(
                validate_phase_result(
                    root,
                    task_path,
                    phase_number,
                    expected_commands,
                    expected_outputs,
                )
            )
            errors.extend(require_file(root, runtime_dir / f"phase{phase_number}-prompt.md", "runtime prompt"))
            errors.extend(require_file(root, runtime_dir / f"phase{phase_number}-contract.json", "phase contract"))
            errors.extend(require_file(root, runtime_dir / f"phase{phase_number}-checklist.md", "phase checklist"))
            errors.extend(require_file(root, runtime_dir / f"phase{phase_number}-evidence.json", "phase evidence"))
            errors.extend(
                require_file(root, runtime_dir / f"phase{phase_number}-reconciliation.json", "phase reconciliation")
            )
            errors.extend(
                validate_phase_reconciliation(root, runtime_dir / f"phase{phase_number}-reconciliation.json")
            )
            errors.extend(
                require_file(root, runtime_dir / f"phase{phase_number}-reconciliation.md", "phase reconciliation summary")
            )
            errors.extend(require_file(root, runtime_dir / f"phase{phase_number}-gate.json", "phase gate"))
            errors.extend(validate_phase_gate(root, runtime_dir / f"phase{phase_number}-gate.json"))
            errors.extend(
                validate_runtime_contract_bundle(
                    root,
                    task_path,
                    phase_number,
                    expected_commands,
                    expected_outputs,
                )
            )
            for attempt in phase_attempts(phase):
                errors.extend(
                    require_file(
                        root,
                        runtime_dir / f"phase{phase_number}-output-attempt{attempt}.jsonl",
                        "runtime output",
                        check_placeholder=False,
                    )
                )
                errors.extend(
                    require_file(
                        root,
                        runtime_dir / f"phase{phase_number}-stderr-attempt{attempt}.txt",
                        "runtime stderr",
                        check_placeholder=False,
                        allow_empty=True,
                    )
                )
            if phase_number == 0:
                errors.extend(require_file(root, runtime_dir / "docs-diff.md", "docs diff", check_placeholder=False))

    if require_evaluation:
        errors.extend(
            require_file(root, runtime_dir / "evaluation-command-results.json", "evaluation command results", False)
        )
        errors.extend(require_file(root, runtime_dir / "evaluation-prompt.md", "evaluation prompt"))
        errors.extend(require_file(root, runtime_dir / "evaluation-output.jsonl", "evaluation output", False))

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", help="Task directory name or path.")
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument("--require-evaluation", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    task_path = resolve_task_path(root, args.task)
    errors = verify(root, task_path, args.require_evaluation)
    if errors:
        print("Task verification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Task verification passed: {task_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
