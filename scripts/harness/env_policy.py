"""Environment minimization policy for harness child processes."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

from policy_pack import environment_policy


HARNESS_POLICY_CONTROL_ENV = {
    "CODEX_HARNESS_ALLOW_POLICY_PACK_OVERRIDE",
    "CODEX_HARNESS_POLICY_PACK",
}
HARNESS_CONTEXT_ENV_ALLOWLIST = {
    "CODEX_HARNESS_ACTIVE",
    "CODEX_HARNESS_CHILD_CODEX_YOLO",
    "CODEX_HARNESS_CONTRACT_PATH",
    "CODEX_HARNESS_LAUNCH_DIR",
    "CODEX_HARNESS_LAUNCH_ROOT",
    "CODEX_HARNESS_PHASE",
    "CODEX_HARNESS_PROJECT_LINT_LEVEL",
    "CODEX_HARNESS_ROOT",
    "CODEX_HARNESS_SESSION",
    "CODEX_HARNESS_TASK",
    "CODEX_HARNESS_TASK_PATH",
}


def default_allowed_env() -> set[str]:
    return set(environment_policy().get("allowed_names") or [])


def sensitive_env_name_res() -> list[re.Pattern[str]]:
    return [
        re.compile(pattern, re.IGNORECASE)
        for pattern in (environment_policy().get("sensitive_name_patterns") or [])
    ]


def additional_allowed_env(raw_value: str | None = None) -> set[str]:
    raw_value = os.environ.get("CODEX_HARNESS_ENV_ALLOW", "") if raw_value is None else raw_value
    return {item.strip() for item in raw_value.split(",") if item.strip()}


def is_sensitive_env_name(name: str) -> bool:
    return any(pattern.search(name) for pattern in sensitive_env_name_res())


def is_allowed_harness_env_name(name: str, allow_harness_policy_controls: bool) -> bool:
    if name in HARNESS_CONTEXT_ENV_ALLOWLIST:
        return True
    if name in HARNESS_POLICY_CONTROL_ENV:
        return allow_harness_policy_controls
    return False


def sanitized_env(
    base: Mapping[str, str] | None = None,
    overrides: Mapping[str, str] | None = None,
    allow_harness_policy_controls: bool = False,
    allow_additional_env_names: bool = False,
) -> dict[str, str]:
    source = os.environ if base is None else base
    allowed = default_allowed_env()
    if allow_additional_env_names:
        allowed |= additional_allowed_env(source.get("CODEX_HARNESS_ENV_ALLOW"))
    env: dict[str, str] = {}
    for key, value in source.items():
        if key.startswith("CODEX_HARNESS_"):
            if is_allowed_harness_env_name(key, allow_harness_policy_controls):
                env[key] = value
            continue
        if key in allowed or key.startswith("LC_"):
            if not is_sensitive_env_name(key):
                env[key] = value
    if overrides:
        for key, value in overrides.items():
            if key.startswith("CODEX_HARNESS_"):
                if is_allowed_harness_env_name(key, allow_harness_policy_controls):
                    env[key] = value
                continue
            if not is_sensitive_env_name(key):
                env[key] = value
    return env
