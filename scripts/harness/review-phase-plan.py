#!/usr/bin/env python3
"""Review phase plans for semantic execution risks before Generate."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from phase_contract import (
    contract_acceptance_commands,
    contract_allowed_paths,
    contract_required_repo_outputs,
    parse_phase_contract,
)


IMPLEMENTATION_PATH_PREFIXES = (
    "app/",
    "apps/",
    "src/",
    "source/",
    "sources/",
    "modules/",
    "packages/",
    "supapp/",
    "supabase/functions/",
    "supabase/migrations/",
)
NON_IMPLEMENTATION_PREFIXES = (
    "docs/",
    "tasks/",
    "tests/",
)
SWIFT_BUILD_RE = re.compile(r"\bxcodebuild\b")
PHASE_FILE_RE = re.compile(r"^phase(?P<number>\d+)\.md$")
AMBIGUOUS_IMPLEMENT_OR_PROVE_RE = re.compile(
    r"\b(?:implement|fix|repair)\s+or\s+(?:prove|verify|document)\b|"
    r"(?:구현|수정|보완)\s*(?:또는|or)\s*(?:증명|검증)",
    re.IGNORECASE,
)
DEFERRED_VALIDATOR_RE = re.compile(
    r"phase\s*\d+\s+can\s+enforce|"
    r"future\s+(?:phase|work)\s+can\s+enforce|"
    r"known\s+(?:app\s+)?gaps?.{0,80}(?:documented|not\s+fail|instead\s+of\s+fail)|"
    r"instead\s+of\s+failing|"
    r"현재.{0,80}gap.{0,80}실패.{0,20}않|"
    r"나중에.{0,40}강제",
    re.IGNORECASE | re.DOTALL,
)
DESIGN_NOT_APPROVED_RE = re.compile(r"(?i)design approval status:\s*not approved|설계 승인 상태:\s*미승인")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def repo_relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def phase_files(task_path: Path) -> list[Path]:
    phase_dir = task_path / "phases"
    return sorted(phase_dir.glob("phase*.md"), key=phase_file_sort_key)


def phase_file_sort_key(path: Path) -> tuple[int, int | str, str]:
    match = PHASE_FILE_RE.match(path.name)
    if match:
        return (0, int(match.group("number")), path.name)
    return (1, path.name, path.name)


def phase_number_from_contract(contract: dict[str, Any], fallback: int) -> int:
    value = contract.get("phase")
    return value if isinstance(value, int) else fallback


def text_for_contract(markdown: str, contract: dict[str, Any]) -> str:
    parts = [markdown, str(contract.get("name") or "")]
    scope = contract.get("scope")
    if isinstance(scope, dict):
        parts.append(str(scope.get("layer") or ""))
    for instruction in contract.get("instructions") or []:
        if isinstance(instruction, dict):
            parts.append(str(instruction.get("task") or ""))
    for criterion in contract.get("success_criteria") or []:
        if isinstance(criterion, str):
            parts.append(criterion)
    return "\n".join(parts)


def normalize_paths(paths: list[str]) -> list[str]:
    return [item.strip().lstrip("./").lower() for item in paths if item.strip()]


def is_non_implementation_path(path: str) -> bool:
    lowered = path.lower().lstrip("./")
    return lowered.startswith(NON_IMPLEMENTATION_PREFIXES)


def is_implementation_path(path: str) -> bool:
    lowered = path.lower().lstrip("./")
    if is_non_implementation_path(lowered):
        return False
    if lowered.endswith((".swift", ".ts", ".tsx", ".js", ".jsx", ".py", ".sql", ".rs", ".go", ".kt")):
        return True
    return lowered.startswith(IMPLEMENTATION_PATH_PREFIXES)


def phase_has_implementation_paths(contract: dict[str, Any]) -> bool:
    paths = normalize_paths([
        *contract_allowed_paths(contract),
        *contract_required_repo_outputs(contract),
    ])
    return any(is_implementation_path(path) for path in paths)


def phase_has_swift_paths(contract: dict[str, Any]) -> bool:
    paths = normalize_paths([
        *contract_allowed_paths(contract),
        *contract_required_repo_outputs(contract),
    ])
    return any(path.endswith(".swift") or path.startswith("supapp/") for path in paths)


def acceptance_has_xcodebuild(contract: dict[str, Any]) -> bool:
    return any(SWIFT_BUILD_RE.search(command) for command in contract_acceptance_commands(contract))


def phase_layer(contract: dict[str, Any]) -> str:
    scope = contract.get("scope")
    if not isinstance(scope, dict):
        return ""
    return str(scope.get("layer") or "").strip().lower()


def is_validation_or_qa_phase(contract: dict[str, Any]) -> bool:
    layer = phase_layer(contract)
    text = f"{contract.get('name') or ''} {layer}".lower()
    return any(token in text for token in ["test", "tests", "validator", "validation", "qa", "검증"])


def review_design_approval_text(root: Path, task_path: Path) -> list[str]:
    approval = read_json(task_path / "context-pack" / "static" / "design-approval.json")
    if approval.get("approved") is not True:
        return []
    raw_doc = approval.get("approved_doc")
    if not isinstance(raw_doc, str) or not raw_doc.strip():
        return []
    doc_path = root / raw_doc
    try:
        text = doc_path.read_text(encoding="utf-8")
    except OSError:
        return []
    if DESIGN_NOT_APPROVED_RE.search(text):
        return [
            f"{repo_relative(doc_path, root)} still says design approval is not approved after design approval was recorded."
        ]
    return []


def review_phase_plan(root: Path, task_path: Path) -> list[str]:
    errors: list[str] = []
    parsed: list[tuple[Path, int, str, dict[str, Any]]] = []
    for index, path in enumerate(phase_files(task_path)):
        markdown = path.read_text(encoding="utf-8")
        contract, parse_errors = parse_phase_contract(markdown)
        if parse_errors or contract is None:
            errors.extend(f"{repo_relative(path, root)}: {error}" for error in parse_errors)
            continue
        parsed.append((path, phase_number_from_contract(contract, index), markdown, contract))

    errors.extend(review_design_approval_text(root, task_path))

    previous_xcodebuild_implementation_phases: list[int] = []
    for path, phase_number, markdown, contract in parsed:
        label = repo_relative(path, root)
        contract_text = text_for_contract(markdown, contract)
        has_implementation = phase_has_implementation_paths(contract)
        has_swift = phase_has_swift_paths(contract)
        has_xcodebuild = acceptance_has_xcodebuild(contract)
        validation_or_qa = is_validation_or_qa_phase(contract)

        if has_swift and not has_xcodebuild:
            errors.append(
                f"{label}: Swift implementation paths require an xcodebuild acceptance command in the same phase."
            )

        if has_xcodebuild and not has_implementation and not previous_xcodebuild_implementation_phases:
            errors.append(
                f"{label}: xcodebuild first appears in a non-implementation phase; compile failures may be discovered where implementation repair is out of scope."
            )

        if has_implementation and AMBIGUOUS_IMPLEMENT_OR_PROVE_RE.search(contract_text):
            errors.append(
                f"{label}: implementation contract uses ambiguous 'implement or prove' wording; split implementation from verification evidence."
            )

        if validation_or_qa and not has_implementation and DEFERRED_VALIDATOR_RE.search(contract_text):
            errors.append(
                f"{label}: validator/QA phase defers enforcement of known gaps to a later phase; planned state requires enforceable phase semantics."
            )

        if has_implementation and has_xcodebuild:
            previous_xcodebuild_implementation_phases.append(phase_number)

    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", type=Path, help="Task directory, e.g. tasks/demo")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    task_path = args.task if args.task.is_absolute() else root / args.task
    errors = review_phase_plan(root, task_path)
    result = {
        "status": "passed" if not errors else "failed",
        "task": repo_relative(task_path, root),
        "errors": errors,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif errors:
        print("Phase plan review failed:")
        for error in errors:
            print(f"- {error}")
    else:
        print(f"Phase plan review passed: {repo_relative(task_path, root)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
