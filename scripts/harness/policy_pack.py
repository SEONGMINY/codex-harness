"""Load harness policy packs used by command, env, and redaction guards."""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_POLICY_PACK_PATH = SCRIPT_DIR / "policy-packs" / "default-security.json"
TRUSTED_POLICY_PACK_DIR = SCRIPT_DIR / "policy-packs"
PROJECT_CONFIG_NAME = "codex-harness.json"
PROJECT_POLICY_CONFIG_KEY = "policy_pack_env_override"
REQUIRED_POLICY_SECTIONS = ("command", "environment", "redaction")
REQUIRED_COMMAND_KEYS = ("shell_control_tokens", "forbidden_executables", "sensitive_path_markers")
REQUIRED_ENVIRONMENT_KEYS = ("allowed_names", "sensitive_name_patterns")
REQUIRED_REDACTION_KEYS = ("replacement", "secret_patterns")
_POLICY_ROOT: Path | None = None


def configure_policy_root(root: str | Path | None) -> None:
    global _POLICY_ROOT
    _POLICY_ROOT = Path(root).resolve() if root is not None else None
    load_policy_pack_snapshot.cache_clear()


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _policy_config_start() -> Path:
    for env_name in ["CODEX_HARNESS_ROOT", "CODEX_HARNESS_LAUNCH_ROOT"]:
        raw_value = os.environ.get(env_name, "").strip()
        if raw_value:
            return Path(raw_value).resolve()
    return _POLICY_ROOT or Path.cwd().resolve()


def _resolve_path(value: str | Path, root: Path | None = None) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = (root or _policy_config_start()) / path
    return path.resolve()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _project_config_path(start: Path | None = None) -> Path | None:
    current = (start or _policy_config_start()).resolve()
    for candidate in [current, *current.parents]:
        config = candidate / PROJECT_CONFIG_NAME
        if config.exists():
            return config
    return None


def _project_allows_policy_pack_env_override(root: Path | None = None) -> bool:
    config_path = _project_config_path(root)
    if config_path is None:
        return False
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    policy_config = config.get(PROJECT_POLICY_CONFIG_KEY) if isinstance(config, dict) else None
    return isinstance(policy_config, dict) and policy_config.get("allow_env_override") is True


def _require_string_list(policy: dict[str, Any], key: str, label: str) -> None:
    if not isinstance(policy.get(key), list) or not all(isinstance(item, str) for item in policy.get(key, [])):
        raise ValueError(f"Policy pack `{label}.{key}` must be a list of strings.")


def _validate_policy_pack(data: dict[str, Any], path: Path) -> None:
    for section in REQUIRED_POLICY_SECTIONS:
        if not isinstance(data.get(section), dict):
            raise ValueError(f"Policy pack must include `{section}` object: {path}")
    command = data["command"]
    environment = data["environment"]
    redaction = data["redaction"]
    for key in REQUIRED_COMMAND_KEYS:
        _require_string_list(command, key, "command")
    for key in REQUIRED_ENVIRONMENT_KEYS:
        _require_string_list(environment, key, "environment")
    if not isinstance(redaction.get("replacement"), str) or not redaction["replacement"]:
        raise ValueError("Policy pack `redaction.replacement` must be a non-empty string.")
    _require_string_list(redaction, "secret_patterns", "redaction")


def _stable_json_bytes(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _merge_string_lists(first: Any, second: Any) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for source in [first, second]:
        if not isinstance(source, list):
            continue
        for item in source:
            if not isinstance(item, str) or item in seen:
                continue
            values.append(item)
            seen.add(item)
    return values


def _read_policy_pack(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Policy pack must be a JSON object: {path}")
    _validate_policy_pack(data, path)
    return data, raw


def _overlay_policy_pack(baseline: dict[str, Any], selected: dict[str, Any]) -> dict[str, Any]:
    policy = dict(selected)
    policy["command"] = {
        "shell_control_tokens": _merge_string_lists(
            baseline["command"].get("shell_control_tokens"),
            selected["command"].get("shell_control_tokens"),
        ),
        "forbidden_executables": _merge_string_lists(
            baseline["command"].get("forbidden_executables"),
            selected["command"].get("forbidden_executables"),
        ),
        "sensitive_path_markers": _merge_string_lists(
            baseline["command"].get("sensitive_path_markers"),
            selected["command"].get("sensitive_path_markers"),
        ),
    }
    policy["environment"] = {
        "allowed_names": _merge_string_lists(
            baseline["environment"].get("allowed_names"),
            selected["environment"].get("allowed_names"),
        ),
        "sensitive_name_patterns": _merge_string_lists(
            baseline["environment"].get("sensitive_name_patterns"),
            selected["environment"].get("sensitive_name_patterns"),
        ),
    }
    policy["redaction"] = {
        "replacement": selected["redaction"].get("replacement") or baseline["redaction"].get("replacement"),
        "secret_patterns": _merge_string_lists(
            baseline["redaction"].get("secret_patterns"),
            selected["redaction"].get("secret_patterns"),
        ),
    }
    return policy


def policy_pack_path(raw_path: str | None = None) -> Path:
    if raw_path is not None:
        return _resolve_path(raw_path)
    env_path = os.environ.get("CODEX_HARNESS_POLICY_PACK", "").strip()
    if not env_path:
        return DEFAULT_POLICY_PACK_PATH.resolve()
    if not _truthy_env("CODEX_HARNESS_ALLOW_POLICY_PACK_OVERRIDE"):
        raise ValueError(
            "CODEX_HARNESS_POLICY_PACK is ignored unless "
            "CODEX_HARNESS_ALLOW_POLICY_PACK_OVERRIDE=1 is set."
        )
    root = _policy_config_start()
    if not _project_allows_policy_pack_env_override(root):
        raise ValueError(
            "CODEX_HARNESS_POLICY_PACK requires codex-harness.json "
            "`policy_pack_env_override.allow_env_override: true`."
        )
    path = _resolve_path(env_path, root)
    trusted_root = TRUSTED_POLICY_PACK_DIR.resolve()
    if not _is_relative_to(path, trusted_root):
        raise ValueError(
            "CODEX_HARNESS_POLICY_PACK must resolve under the harness policy-packs "
            f"directory: {trusted_root}"
        )
    return path


def _string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str) and item.strip()] if isinstance(value, list) else []


@lru_cache(maxsize=4)
def load_policy_pack_snapshot(raw_path: str | None = None) -> dict[str, Any]:
    path = policy_pack_path(raw_path)
    data, raw = _read_policy_pack(path)
    default_path = DEFAULT_POLICY_PACK_PATH.resolve()
    if path == default_path:
        effective = data
        effective_raw = raw
    else:
        baseline, baseline_raw = _read_policy_pack(default_path)
        effective = _overlay_policy_pack(baseline, data)
        _validate_policy_pack(effective, path)
        effective_raw = _stable_json_bytes(effective)
    metadata = {
        "id": str(data.get("id") or "unknown"),
        "schema_version": str(data.get("schema_version") or "unknown"),
        "sha256": hashlib.sha256(effective_raw).hexdigest(),
        "path": str(path),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
    }
    if path != default_path:
        metadata["baseline_id"] = str(data.get("baseline_id") or "default-security")
        metadata["baseline_sha256"] = hashlib.sha256(baseline_raw).hexdigest()
    return {"policy": effective, "metadata": metadata}


def load_policy_pack(raw_path: str | None = None) -> dict[str, Any]:
    data = load_policy_pack_snapshot(raw_path).get("policy")
    if not isinstance(data, dict):
        raise ValueError("Policy pack snapshot is invalid.")
    return data


def policy_pack_metadata(raw_path: str | None = None) -> dict[str, str]:
    metadata = load_policy_pack_snapshot(raw_path).get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("Policy pack snapshot metadata is invalid.")
    return {key: str(value) for key, value in metadata.items()}


def policy_pack_runtime_env(raw_path: str | None = None) -> dict[str, str]:
    path = policy_pack_path(raw_path)
    if path == DEFAULT_POLICY_PACK_PATH.resolve():
        return {}
    return {
        "CODEX_HARNESS_POLICY_PACK": str(path),
        "CODEX_HARNESS_ALLOW_POLICY_PACK_OVERRIDE": "1",
    }


def command_policy() -> dict[str, list[str]]:
    policy = load_policy_pack().get("command")
    return {
        "shell_control_tokens": _string_list(policy.get("shell_control_tokens") if isinstance(policy, dict) else []),
        "forbidden_executables": _string_list(policy.get("forbidden_executables") if isinstance(policy, dict) else []),
        "sensitive_path_markers": _string_list(policy.get("sensitive_path_markers") if isinstance(policy, dict) else []),
    }


def environment_policy() -> dict[str, list[str]]:
    policy = load_policy_pack().get("environment")
    return {
        "allowed_names": _string_list(policy.get("allowed_names") if isinstance(policy, dict) else []),
        "sensitive_name_patterns": _string_list(policy.get("sensitive_name_patterns") if isinstance(policy, dict) else []),
    }


def redaction_policy() -> dict[str, Any]:
    policy = load_policy_pack().get("redaction")
    return {
        "replacement": policy.get("replacement") if isinstance(policy, dict) and isinstance(policy.get("replacement"), str) else "[REDACTED]",
        "secret_patterns": _string_list(policy.get("secret_patterns") if isinstance(policy, dict) else []),
    }
