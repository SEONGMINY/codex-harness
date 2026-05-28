"""Command execution policy for harness-owned validation commands."""

from __future__ import annotations

import shlex
from pathlib import Path

from env_policy import sanitized_env
from policy_pack import command_policy
from process_runner import PROCESS_TIMEOUT_EXIT_CODE, run_process
from redaction import redact_text


INTERPRETER_EVAL_FLAGS = {
    "node": {"-e", "--eval"},
    "perl": {"-e"},
    "python": {"-c"},
    "python3": {"-c"},
    "ruby": {"-e"},
}


def token_references_sensitive_path(token: str) -> bool:
    sensitive_path_markers = set(command_policy().get("sensitive_path_markers") or [])
    lowered = token.lower()
    if lowered in {".env", ".ssh"}:
        return True
    if lowered.startswith(".env.") or "/.env" in lowered or "\\.env" in lowered:
        return True
    if "/.ssh" in lowered or "\\.ssh" in lowered:
        return True
    return any(marker in lowered for marker in sensitive_path_markers - {".env", ".ssh"})


def parse_command(command: str) -> tuple[list[str], list[str]]:
    if not isinstance(command, str) or not command.strip():
        return [], ["Command must be a non-empty string."]
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return [], [f"Command must parse as argv without shell syntax: {exc}"]
    return argv, validate_argv(argv)


def validate_argv(argv: list[str]) -> list[str]:
    if not argv:
        return ["Command must not be empty."]
    errors: list[str] = []
    policy = command_policy()
    shell_control_tokens = set(policy.get("shell_control_tokens") or [])
    forbidden_executables = set(policy.get("forbidden_executables") or [])
    executable = Path(argv[0]).name
    if executable in forbidden_executables:
        errors.append(f"Command executable is not allowed by harness policy: {executable}")
    for token in argv[1:]:
        for flag in INTERPRETER_EVAL_FLAGS.get(executable, set()):
            if token == flag or token.startswith(f"{flag}=") or (
                flag in {"-c", "-e"} and token.startswith(flag) and token != flag
            ):
                errors.append(f"Command interpreter eval mode is not allowed by harness policy: {executable} {token}")
    for token in argv:
        if token in shell_control_tokens:
            errors.append(f"Shell control token is not allowed in harness command: {token}")
        if token_references_sensitive_path(token):
            errors.append(f"Command references a sensitive path marker: {token}")
    return errors


def run_command(command: str, cwd: Path, timeout: int) -> tuple[int, str, bool, list[str]]:
    argv, errors = parse_command(command)
    if errors:
        return 126, "\n".join(f"[command-policy] {error}" for error in errors), False, argv
    try:
        result = run_process(
            argv,
            cwd=cwd,
            env=sanitized_env(overrides={"PWD": str(cwd)}),
            timeout=timeout,
        )
    except OSError as exc:
        return 127, f"[execution-error] {exc}", False, argv
    if result.timed_out:
        output = (result.stdout + result.stderr).strip()
        timeout_message = f"[timeout] command exceeded {timeout} seconds"
        return PROCESS_TIMEOUT_EXIT_CODE, redact_text("\n".join(item for item in [output, timeout_message] if item).strip()), True, argv
    return result.returncode, redact_text((result.stdout + result.stderr).strip()), False, argv
