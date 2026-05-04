"""Decision registry helpers for codex-harness tasks."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None  # type: ignore[assignment]


BLOCKING_STAGES = {"clarify", "plan", "generate"}
OPEN_DECISION_BLOCKING_STAGES = {"clarify", "plan", "generate", "non_blocking"}
OPEN_DECISION_STATUSES = {"open", "approved", "rejected", "resolved"}
DECISION_STATUSES = {"approved", "rejected"}
DEPENDENCY_MODES = {"forbidden", "approved_only", "allowed"}
PLACEHOLDER_RE = re.compile(
    r"(^|\b)(TODO|PLACEHOLDER|Replace this|Replace with)(\b|$)",
    re.IGNORECASE,
)
DEPENDENCY_MANIFEST_NAMES = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lockb",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "poetry.lock",
    "uv.lock",
    "Pipfile",
    "Pipfile.lock",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
    "Gemfile",
    "Gemfile.lock",
}
SUPPORTED_DEPENDENCY_MANIFEST_NAMES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
}
DEPENDENCY_LOCKFILE_COMPANIONS = {
    "package-lock.json": {"package.json"},
    "pnpm-lock.yaml": {"package.json"},
    "yarn.lock": {"package.json"},
    "bun.lockb": {"package.json"},
    "poetry.lock": {"pyproject.toml"},
    "uv.lock": {"pyproject.toml"},
    "Pipfile.lock": {"Pipfile"},
    "Cargo.lock": {"Cargo.toml"},
    "go.sum": {"go.mod"},
    "Gemfile.lock": {"Gemfile"},
}


def read_json_file(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, [f"Missing JSON file: {path}"]
    except json.JSONDecodeError as exc:
        return None, [f"Invalid JSON file: {path}: {exc}"]
    if not isinstance(value, dict):
        return None, [f"JSON file must contain an object: {path}"]
    return value, []


def task_static_dir(task_path: Path) -> Path:
    return task_path / "context-pack" / "static"


def decision_file_paths(task_path: Path) -> dict[str, Path]:
    static_dir = task_static_dir(task_path)
    return {
        "decisions": static_dir / "decisions.json",
        "open_decisions": static_dir / "open-decisions.json",
        "architecture": static_dir / "architecture.json",
        "dependency_policy": static_dir / "dependency-policy.json",
        "context_budget": static_dir / "context-gathering-budget.json",
    }


def load_decision_registry(task_path: Path) -> tuple[dict[str, Any], list[str]]:
    paths = decision_file_paths(task_path)
    registry: dict[str, Any] = {}
    errors: list[str] = []
    for key, path in paths.items():
        value, file_errors = read_json_file(path)
        errors.extend(file_errors)
        registry[key] = value or {}
    return registry, errors


def _items(value: Any, field: str = "items") -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    raw_items = value.get(field)
    if raw_items is None:
        raw_items = value.get("decisions")
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, dict)]


def _object_list_errors(value: Any, field: str, label: str) -> list[str]:
    if not isinstance(value, dict):
        return []
    raw_items = value.get(field)
    if not isinstance(raw_items, list):
        return []
    return [
        f"{label}[{index}] must be an object."
        for index, item in enumerate(raw_items)
        if not isinstance(item, dict)
    ]


def has_placeholder(value: Any) -> bool:
    return isinstance(value, str) and bool(PLACEHOLDER_RE.search(value))


def _validate_required_string(item: dict[str, Any], file_name: str, field: str) -> list[str]:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        return [f"{file_name} item must include `{field}`."]
    if has_placeholder(value):
        return [f"{file_name} item `{field}` must not contain placeholder text."]
    return []


def _validate_string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return [f"{label} must be a string list."]
    if any(has_placeholder(item) for item in value):
        return [f"{label} must not contain placeholder text."]
    return []


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str)}


def approved_decision_ids(registry: dict[str, Any]) -> set[str]:
    return {
        str(item.get("id"))
        for item in _items(registry.get("decisions"), "decisions")
        if item.get("id") and item.get("status") == "approved"
    }


def architecture_ref_ids(registry: dict[str, Any]) -> set[str]:
    architecture = registry.get("architecture")
    ids = {
        str(item.get("id"))
        for item in _items(architecture, "decisions")
        if item.get("id")
    }
    ids.update(
        str(item.get("id"))
        for item in _items(architecture, "allowed_edges")
        if item.get("id")
    )
    return ids


def validate_open_decisions(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for item in _items(registry.get("open_decisions"), "decisions"):
        status = item.get("status", "open")
        stage = item.get("blocking_stage", "plan")
        if status == "open" and stage in BLOCKING_STAGES:
            decision_id = item.get("id", "(missing id)")
            question = item.get("question", "(missing question)")
            errors.append(
                f"Blocking open decision remains: {decision_id} "
                f"blocking_stage={stage} question={question!r}"
            )
    return errors


def validate_decision_files(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    decisions = registry.get("decisions")
    if not isinstance(decisions.get("decisions") if isinstance(decisions, dict) else None, list):
        errors.append("decisions.json must contain a `decisions` list.")
    errors.extend(_object_list_errors(decisions, "decisions", "decisions.json decisions"))
    for item in _items(decisions, "decisions"):
        for field in ["id", "status", "summary"]:
            errors.extend(_validate_required_string(item, "decisions.json", field))
        if item.get("rationale") is not None:
            errors.extend(_validate_required_string(item, "decisions.json", "rationale"))
        if item.get("status") not in DECISION_STATUSES:
            errors.append(f"Decision {item.get('id', '(missing id)')} status must be approved or rejected.")

    open_decisions = registry.get("open_decisions")
    if not isinstance(open_decisions.get("decisions") if isinstance(open_decisions, dict) else None, list):
        errors.append("open-decisions.json must contain a `decisions` list.")
    errors.extend(_object_list_errors(open_decisions, "decisions", "open-decisions.json decisions"))
    for item in _items(open_decisions, "decisions"):
        for field in ["id", "question", "blocking_stage", "status"]:
            errors.extend(_validate_required_string(item, "open-decisions.json", field))
        if item.get("status") not in OPEN_DECISION_STATUSES:
            errors.append(
                f"Open decision {item.get('id', '(missing id)')} status must be one of "
                "open, approved, rejected, or resolved."
            )
        if item.get("blocking_stage") not in OPEN_DECISION_BLOCKING_STAGES:
            errors.append(
                f"Open decision {item.get('id', '(missing id)')} blocking_stage must be one of "
                "clarify, plan, generate, or non_blocking."
            )

    architecture = registry.get("architecture")
    if not isinstance(architecture.get("nodes") if isinstance(architecture, dict) else None, list):
        errors.append("architecture.json must contain a `nodes` list.")
    if not isinstance(architecture.get("allowed_edges") if isinstance(architecture, dict) else None, list):
        errors.append("architecture.json must contain an `allowed_edges` list.")
    errors.extend(_object_list_errors(architecture, "nodes", "architecture.json nodes"))
    errors.extend(_object_list_errors(architecture, "allowed_edges", "architecture.json allowed_edges"))
    errors.extend(_object_list_errors(architecture, "decisions", "architecture.json decisions"))
    for item in _items(architecture, "nodes"):
        for field in ["id", "name", "responsibility"]:
            errors.extend(_validate_required_string(item, "architecture.json nodes", field))
    for item in _items(architecture, "allowed_edges"):
        for field in ["from", "to", "reason"]:
            errors.extend(_validate_required_string(item, "architecture.json allowed_edges", field))
    for item in _items(architecture, "decisions"):
        for field in ["id", "summary"]:
            errors.extend(_validate_required_string(item, "architecture.json decisions", field))
    if not architecture_ref_ids(registry):
        errors.append("architecture.json must contain at least one ref id in `decisions` or `allowed_edges`.")
    if isinstance(architecture, dict) and not isinstance(architecture.get("forbid_cycles"), bool):
        errors.append("architecture.json must contain boolean `forbid_cycles`.")

    policy = registry.get("dependency_policy")
    mode = policy.get("new_dependencies") if isinstance(policy, dict) else None
    if mode not in DEPENDENCY_MODES:
        errors.append("dependency-policy.json `new_dependencies` must be forbidden, approved_only, or allowed.")
    if isinstance(policy, dict):
        errors.extend(
            _validate_string_list(
                policy.get("approved_new_dependencies"),
                "dependency-policy.json `approved_new_dependencies`",
            )
        )
        errors.extend(
            _validate_string_list(
                policy.get("approved_dependency_manifest_changes"),
                "dependency-policy.json `approved_dependency_manifest_changes`",
            )
        )

    budget = registry.get("context_budget")
    if not isinstance(budget, dict):
        errors.append("context-gathering-budget.json must contain an object.")
    else:
        for field in ["search_batches", "max_files_to_read"]:
            if not isinstance(budget.get(field), int) or budget.get(field) < 1:
                errors.append(f"context-gathering-budget.json `{field}` must be a positive integer.")
        for field in ["stop_when", "escalate_when"]:
            value = budget.get(field)
            if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
                errors.append(f"context-gathering-budget.json `{field}` must be a non-empty string list.")
            elif any(has_placeholder(item) for item in value):
                errors.append(f"context-gathering-budget.json `{field}` must not contain placeholder text.")

    return errors


def validate_contract_refs(contract: dict[str, Any], registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    decision_refs = contract.get("decision_refs")
    if not isinstance(decision_refs, list) or not decision_refs:
        errors.append("`decision_refs` must be a non-empty list.")
    else:
        approved = approved_decision_ids(registry)
        for ref in decision_refs:
            if not isinstance(ref, str) or not ref.strip():
                errors.append("`decision_refs` entries must be non-empty strings.")
            elif ref not in approved:
                errors.append(f"`decision_refs` contains unapproved decision: {ref}")

    architecture_refs = contract.get("architecture_refs")
    if not isinstance(architecture_refs, list) or not architecture_refs:
        errors.append("`architecture_refs` must be a non-empty list.")
    else:
        known_refs = architecture_ref_ids(registry)
        for ref in architecture_refs:
            if not isinstance(ref, str) or not ref.strip():
                errors.append("`architecture_refs` entries must be non-empty strings.")
            elif known_refs and ref not in known_refs:
                errors.append(f"`architecture_refs` contains unknown architecture ref: {ref}")

    policy = contract.get("dependency_policy")
    if not isinstance(policy, dict):
        errors.append("`dependency_policy` must be an object.")
    else:
        mode = policy.get("new_dependencies")
        if mode not in {"forbidden", "approved_only", "allowed"}:
            errors.append("`dependency_policy.new_dependencies` must be forbidden, approved_only, or allowed.")
        approved = policy.get("approved_new_dependencies", [])
        if not isinstance(approved, list) or not all(isinstance(item, str) for item in approved):
            errors.append("`dependency_policy.approved_new_dependencies` must be a string list.")
        approved_manifests = policy.get("approved_dependency_manifest_changes", [])
        if not isinstance(approved_manifests, list) or not all(isinstance(item, str) for item in approved_manifests):
            errors.append("`dependency_policy.approved_dependency_manifest_changes` must be a string list.")
        errors.extend(validate_contract_dependency_policy(policy, registry))
    return errors


def validate_contract_dependency_policy(policy: dict[str, Any], registry: dict[str, Any]) -> list[str]:
    registry_policy = registry.get("dependency_policy")
    if not isinstance(registry_policy, dict):
        return ["dependency-policy.json must contain an object."]

    registry_mode = registry_policy.get("new_dependencies")
    contract_mode = policy.get("new_dependencies")
    if registry_mode not in DEPENDENCY_MODES or contract_mode not in DEPENDENCY_MODES:
        return []

    mode_rank = {"forbidden": 0, "approved_only": 1, "allowed": 2}
    if mode_rank[contract_mode] > mode_rank[registry_mode]:
        return [
            "`dependency_policy.new_dependencies` is more permissive than dependency-policy.json: "
            f"contract={contract_mode}, registry={registry_mode}"
        ]

    if registry_mode == "approved_only" and contract_mode == "approved_only":
        errors: list[str] = []
        registry_deps = _string_set(registry_policy.get("approved_new_dependencies"))
        contract_deps = _string_set(policy.get("approved_new_dependencies"))
        extra_deps = sorted(contract_deps - registry_deps)
        if extra_deps:
            errors.append(
                "`dependency_policy.approved_new_dependencies` contains values not approved in "
                "dependency-policy.json: " + ", ".join(extra_deps)
            )

        registry_manifests = _string_set(registry_policy.get("approved_dependency_manifest_changes"))
        contract_manifests = _string_set(policy.get("approved_dependency_manifest_changes"))
        extra_manifests = sorted(contract_manifests - registry_manifests)
        if extra_manifests:
            errors.append(
                "`dependency_policy.approved_dependency_manifest_changes` contains values not approved in "
                "dependency-policy.json: " + ", ".join(extra_manifests)
            )
        return errors

    return []


def changed_dependency_manifests(changed_files: list[str]) -> list[str]:
    matches = []
    for path in changed_files:
        name = Path(path).name
        if name in DEPENDENCY_MANIFEST_NAMES or name.startswith("requirements"):
            matches.append(path)
    return sorted(matches)


def supported_dependency_manifest(raw_path: str) -> bool:
    name = Path(raw_path).name
    return name in SUPPORTED_DEPENDENCY_MANIFEST_NAMES or name.startswith("requirements")


def lockfile_companion_sources(raw_path: str) -> set[str]:
    name = Path(raw_path).name
    return DEPENDENCY_LOCKFILE_COMPANIONS.get(name, set())


def unsupported_dependency_manifests(manifests: list[str]) -> list[str]:
    manifest_names = {Path(path).name for path in manifests}
    unsupported: list[str] = []
    for path in manifests:
        if supported_dependency_manifest(path):
            continue
        companion_sources = lockfile_companion_sources(path)
        if companion_sources and companion_sources & manifest_names:
            continue
        unsupported.append(path)
    return sorted(unsupported)


def normalize_dependency_name(value: str) -> str:
    return value.strip().lower()


def dependency_name_from_requirement(value: str) -> str | None:
    line = value.strip()
    if not line or line.startswith("#") or line.startswith("-"):
        return None
    line = line.split("#", 1)[0].strip()
    match = re.match(r"([A-Za-z0-9_.@/+:-]+)", line)
    if not match:
        return None
    name = match.group(1).split("[", 1)[0].strip()
    if not name:
        return None
    if "://" in name or name.startswith(("git+", "file:")):
        return None
    return normalize_dependency_name(name)


def read_head_file(root: Path, raw_path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"HEAD:{raw_path}"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def read_worktree_file(root: Path, raw_path: str) -> str:
    try:
        return (root / raw_path).read_text(encoding="utf-8")
    except OSError:
        return ""


def package_json_dependency_names(text: str) -> set[str]:
    if not text.strip():
        return set()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return set()
    if not isinstance(data, dict):
        return set()
    names: set[str] = set()
    for field in [
        "dependencies",
        "devDependencies",
        "peerDependencies",
        "optionalDependencies",
        "bundleDependencies",
        "bundledDependencies",
    ]:
        value = data.get(field)
        if isinstance(value, dict):
            names.update(normalize_dependency_name(str(name)) for name in value)
        elif isinstance(value, list):
            names.update(normalize_dependency_name(str(name)) for name in value)
    return names


def requirements_dependency_names(text: str) -> set[str]:
    names: set[str] = set()
    for line in text.splitlines():
        name = dependency_name_from_requirement(line)
        if name:
            names.add(name)
    return names


def pyproject_dependency_names(text: str) -> set[str]:
    if not text.strip():
        return set()
    if tomllib is None:
        return pyproject_dependency_names_fallback(text)
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return pyproject_dependency_names_fallback(text)
    if not isinstance(data, dict):
        return set()

    names: set[str] = set()
    project = data.get("project")
    if isinstance(project, dict):
        for item in project.get("dependencies") or []:
            if isinstance(item, str):
                name = dependency_name_from_requirement(item)
                if name:
                    names.add(name)
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for group in optional.values():
                if isinstance(group, list):
                    for item in group:
                        if isinstance(item, str):
                            name = dependency_name_from_requirement(item)
                            if name:
                                names.add(name)

    tool = data.get("tool")
    poetry = tool.get("poetry") if isinstance(tool, dict) else None
    if isinstance(poetry, dict):
        for field in ["dependencies", "dev-dependencies"]:
            value = poetry.get(field)
            if isinstance(value, dict):
                names.update(normalize_dependency_name(str(name)) for name in value if str(name) != "python")
        groups = poetry.get("group")
        if isinstance(groups, dict):
            for group in groups.values():
                if not isinstance(group, dict):
                    continue
                dependencies = group.get("dependencies")
                if isinstance(dependencies, dict):
                    names.update(
                        normalize_dependency_name(str(name))
                        for name in dependencies
                        if str(name) != "python"
                    )

    return names


def quoted_requirement_names(value: str) -> set[str]:
    names: set[str] = set()
    for item in re.findall(r'"([^"]+)"|\'([^\']+)\'', value):
        raw = item[0] or item[1]
        name = dependency_name_from_requirement(raw)
        if name:
            names.add(name)
    return names


def pyproject_dependency_names_fallback(text: str) -> set[str]:
    names: set[str] = set()
    section = ""
    in_project_dependency_list = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line.strip("[]")
            in_project_dependency_list = False
            continue

        if section == "project" and line.startswith("dependencies"):
            names.update(quoted_requirement_names(line))
            in_project_dependency_list = "[" in line and "]" not in line
            continue
        if in_project_dependency_list:
            names.update(quoted_requirement_names(line))
            if "]" in line:
                in_project_dependency_list = False
            continue
        if section.startswith("project.optional-dependencies"):
            names.update(quoted_requirement_names(line))
            continue
        if section.startswith("tool.poetry") and section.endswith("dependencies") and "=" in line:
            raw_name = line.split("=", 1)[0].strip().strip('"').strip("'")
            if raw_name and raw_name != "python":
                names.add(normalize_dependency_name(raw_name))
    return names


def manifest_dependency_names(raw_path: str, text: str) -> set[str]:
    name = Path(raw_path).name
    if name == "package.json":
        return package_json_dependency_names(text)
    if name == "pyproject.toml":
        return pyproject_dependency_names(text)
    if name.startswith("requirements"):
        return requirements_dependency_names(text)
    return set()


def added_dependency_names(root: Path, manifests: list[str]) -> dict[str, list[str]]:
    added: dict[str, list[str]] = {}
    for raw_path in manifests:
        before = manifest_dependency_names(raw_path, read_head_file(root, raw_path))
        after = manifest_dependency_names(raw_path, read_worktree_file(root, raw_path))
        names = sorted(after - before)
        if names:
            added[raw_path] = names
    return added


def validate_dependency_changes(
    contract: dict[str, Any],
    changed_files: list[str],
    root: Path | None = None,
) -> list[str]:
    manifests = changed_dependency_manifests(changed_files)
    if not manifests:
        return []

    policy = contract.get("dependency_policy") if isinstance(contract.get("dependency_policy"), dict) else {}
    mode = policy.get("new_dependencies")
    if mode == "allowed":
        return []
    approved_manifests = _string_set(policy.get("approved_dependency_manifest_changes"))
    if mode == "approved_only" and all(path in approved_manifests for path in manifests):
        unsupported = unsupported_dependency_manifests(manifests)
        if unsupported:
            return [
                "Dependency manifest approval requires supported dependency parsing: "
                + ", ".join(unsupported)
            ]
        if root is None:
            return []
        approved_dependencies = _string_set(policy.get("approved_new_dependencies"))
        added_by_manifest = added_dependency_names(root, manifests)
        unapproved = sorted(
            {
                dep
                for names in added_by_manifest.values()
                for dep in names
                if dep not in approved_dependencies
            }
        )
        if not unapproved:
            return []
        return [
            "Dependency manifest added unapproved dependencies: "
            + ", ".join(unapproved)
        ]
    return [
        "Dependency manifest changed without approved dependency policy: "
        + ", ".join(manifests)
    ]
