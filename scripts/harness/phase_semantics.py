"""Derived semantic classification for phase contracts.

This module is intentionally pure: it reads an already-parsed phase contract
and returns canonical meaning for other harness scripts to consume. It should
not load task files, execute commands, or own product-specific policy.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import shlex
from pathlib import Path
from typing import Any


NON_IMPLEMENTATION_LAYERS = {"docs", "documentation", "planning", "test", "tests", "qa"}
VALIDATION_LAYER_TOKENS = {"test", "tests", "validator", "validation", "qa", "검증"}
IMPLEMENTATION_PATH_PREFIXES = (
    "app/",
    "apps/",
    "src/",
    "source/",
    "sources/",
    "modules/",
    "packages/",
    "supapp/sources/",
    "supabase/functions/",
    "supabase/migrations/",
)
NON_IMPLEMENTATION_PATH_PREFIXES = (
    "docs/",
    "tasks/",
    "tests/",
)
IMPLEMENTATION_EXTENSIONS = (".swift", ".ts", ".tsx", ".js", ".jsx", ".py", ".sql", ".rs", ".go", ".kt")
TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__|specs?)/|"
    r"(^|/)[^/]*(?:test|tests|spec)\.(?:swift|ts|tsx|js|jsx|py|kt|go|rs)$",
    re.IGNORECASE,
)
VALIDATOR_PATH_RE = re.compile(
    r"(^|/)(?:validate_[^/]+|[^/]*validator[^/]*)\.(?:py|js|ts|tsx|swift)$",
    re.IGNORECASE,
)
BUGFIX_VALIDATION_RE = re.compile(
    r"\bbug\s*fix\b|\bbugfix\b|\bfix\b|\bvalidation\b|\bvalidate\b|버그|고치|오류|검증",
    re.IGNORECASE,
)
XCODEBUILD_RE = re.compile(r"\bxcodebuild\b")
TEST_SUITE_COMMAND_RE = re.compile(
    r"(^|\s)(pytest|python3?\s+-m\s+unittest|npm\s+test|pnpm\s+test|yarn\s+test|swift\s+test)\b",
    re.IGNORECASE,
)
FIXTURE_OR_META_RE = re.compile(
    r"(^|\s)(--fixture|--fixtures|--meta|--self-test|--contract|--schema)\b|"
    r"(^|\s)(tests/fixtures|fixtures/|golden/)",
    re.IGNORECASE,
)
REPO_SCAN_RE = re.compile(r"(^|\s)(--repo-scan|--repo|--scan-repo)\b", re.IGNORECASE)


@dataclass(frozen=True)
class PhaseSemantics:
    layer: str
    phase_kind: str
    paths: tuple[str, ...]
    product_paths: tuple[str, ...]
    test_or_validator_paths: tuple[str, ...]
    validator_paths: tuple[str, ...]
    has_swift_paths: bool
    has_xcodebuild_acceptance: bool
    writes_product_code: bool
    writes_validator: bool
    validation_only: bool
    needs_verification_evidence: bool


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def normalize_path(path: str) -> str:
    return path.strip().lstrip("./").lower()


def scope_layer(contract: dict[str, Any] | None) -> str:
    if not isinstance(contract, dict):
        return ""
    scope = contract.get("scope")
    if not isinstance(scope, dict):
        return ""
    return str(scope.get("layer") or "").strip().lower()


def allowed_paths(contract: dict[str, Any] | None) -> list[str]:
    if not isinstance(contract, dict):
        return []
    scope = contract.get("scope")
    if not isinstance(scope, dict):
        return []
    return string_list(scope.get("allowed_paths"))


def required_repo_outputs(contract: dict[str, Any] | None) -> list[str]:
    if not isinstance(contract, dict):
        return []
    return string_list(contract.get("required_repo_outputs"))


def acceptance_commands(contract: dict[str, Any] | None) -> list[str]:
    if not isinstance(contract, dict):
        return []
    return string_list(contract.get("acceptance_commands"))


def phase_paths(contract: dict[str, Any] | None) -> list[str]:
    return [
        normalize_path(path)
        for path in [*allowed_paths(contract), *required_repo_outputs(contract)]
        if path.strip()
    ]


def is_validation_or_qa_phase(contract: dict[str, Any], phase_name: str | None = None) -> bool:
    layer = scope_layer(contract)
    text = f"{phase_name or ''} {contract.get('name') or ''} {layer}".lower()
    return any(token in text for token in VALIDATION_LAYER_TOKENS)


def is_implementation_layer(contract: dict[str, Any]) -> bool:
    layer = scope_layer(contract)
    return bool(layer) and layer not in NON_IMPLEMENTATION_LAYERS


def contract_needs_verification_evidence(contract: dict[str, Any], phase_name: str | None = None) -> bool:
    parts: list[str] = [phase_name or "", str(contract.get("name") or ""), scope_layer(contract)]
    for instruction in contract.get("instructions") or []:
        if isinstance(instruction, dict):
            parts.append(str(instruction.get("task") or ""))
    return bool(BUGFIX_VALIDATION_RE.search("\n".join(parts)))


def is_test_or_validator_path(path: str) -> bool:
    lowered = normalize_path(path)
    return bool(TEST_PATH_RE.search(lowered) or VALIDATOR_PATH_RE.search(lowered))


def is_validator_path(path: str) -> bool:
    lowered = normalize_path(path)
    return bool(VALIDATOR_PATH_RE.search(lowered))


def is_non_implementation_path(path: str) -> bool:
    lowered = normalize_path(path)
    return lowered.startswith(NON_IMPLEMENTATION_PATH_PREFIXES) or is_test_or_validator_path(lowered)


def is_product_implementation_path(path: str) -> bool:
    lowered = normalize_path(path)
    if is_non_implementation_path(lowered):
        return False
    if lowered.startswith(IMPLEMENTATION_PATH_PREFIXES):
        return True
    return lowered.endswith(IMPLEMENTATION_EXTENSIONS)


def has_xcodebuild(commands: list[str]) -> bool:
    return any(XCODEBUILD_RE.search(command) for command in commands)


def command_runs_test_suite(command: str) -> bool:
    return bool(TEST_SUITE_COMMAND_RE.search(command) or XCODEBUILD_RE.search(command))


def command_uses_fixture_or_meta(command: str) -> bool:
    return bool(FIXTURE_OR_META_RE.search(command))


def command_uses_repo_scan(command: str) -> bool:
    return bool(REPO_SCAN_RE.search(command)) or not command_uses_fixture_or_meta(command)


def command_mentions_path(command: str, raw_path: str) -> bool:
    path = raw_path.strip().lstrip("./")
    if not path:
        return False
    path_name = Path(path).name
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    normalized_tokens = {token.strip().lstrip("./") for token in tokens}
    if path in normalized_tokens or path_name in normalized_tokens:
        return True
    return path in command


def command_targets_any_path(command: str, paths: list[str] | tuple[str, ...]) -> bool:
    return any(command_mentions_path(command, path) for path in paths)


def analyze_phase(contract: dict[str, Any], phase_name: str | None = None) -> PhaseSemantics:
    paths = tuple(phase_paths(contract))
    product_paths = tuple(path for path in paths if is_product_implementation_path(path))
    test_or_validator_paths = tuple(path for path in paths if is_test_or_validator_path(path))
    validator_paths = tuple(path for path in paths if is_validator_path(path))
    layer = scope_layer(contract)
    validation_or_qa = is_validation_or_qa_phase(contract, phase_name)
    writes_product = bool(product_paths) or (is_implementation_layer(contract) and not test_or_validator_paths)
    writes_validator = bool(validator_paths or test_or_validator_paths)
    if validation_or_qa and not writes_product:
        phase_kind = "validation"
    elif writes_product:
        phase_kind = "implementation"
    elif layer in {"docs", "documentation"}:
        phase_kind = "docs"
    else:
        phase_kind = "other"
    return PhaseSemantics(
        layer=layer,
        phase_kind=phase_kind,
        paths=paths,
        product_paths=product_paths,
        test_or_validator_paths=test_or_validator_paths,
        validator_paths=validator_paths,
        has_swift_paths=any(path.endswith(".swift") or path.startswith("supapp/") for path in paths),
        has_xcodebuild_acceptance=has_xcodebuild(acceptance_commands(contract)),
        writes_product_code=writes_product,
        writes_validator=writes_validator,
        validation_only=phase_kind == "validation" and not writes_product,
        needs_verification_evidence=contract_needs_verification_evidence(contract, phase_name),
    )
