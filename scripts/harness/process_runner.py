"""Process helpers that clean up child process groups on timeout."""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import NamedTuple


PROCESS_TIMEOUT_EXIT_CODE = 124
PROCESS_TERMINATION_GRACE_SECONDS = 5
PROCESS_OUTPUT_DRAIN_TIMEOUT_SECONDS = 1


class ProcessResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    cleanup_confirmed: bool = True


def output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def signal_process_group(process: subprocess.Popen[str], signal_number: int) -> None:
    if hasattr(os, "killpg"):
        try:
            os.killpg(process.pid, signal_number)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    if process.poll() is not None:
        return
    if signal_number == signal.SIGTERM:
        process.terminate()
    else:
        process.kill()


def wait_process(process: subprocess.Popen[str], timeout: int) -> bool:
    try:
        process.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False


def process_group_exists(process: subprocess.Popen[str]) -> bool:
    if not hasattr(os, "killpg"):
        return process.poll() is None
    try:
        os.killpg(process.pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return process.poll() is None


def terminate_process_group(
    process: subprocess.Popen[str],
    *,
    grace_seconds: int = PROCESS_TERMINATION_GRACE_SECONDS,
) -> bool:
    signal_process_group(process, signal.SIGTERM)
    wait_process(process, grace_seconds)
    signal_process_group(process, signal.SIGKILL)
    wait_process(process, grace_seconds)
    return not process_group_exists(process)


def drain_process_output(process: subprocess.Popen[str]) -> tuple[str, str]:
    try:
        stdout, stderr = process.communicate(timeout=PROCESS_OUTPUT_DRAIN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        stdout, stderr = "", ""
        for pipe in (process.stdout, process.stderr):
            if pipe is None:
                continue
            try:
                pipe.close()
            except OSError:
                pass
    return output_text(stdout), output_text(stderr)


def run_process(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> ProcessResult:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return ProcessResult(process.returncode or 0, output_text(stdout), output_text(stderr), False, True)
    except subprocess.TimeoutExpired:
        cleanup_confirmed = terminate_process_group(process)
        stdout, stderr = drain_process_output(process)
        return ProcessResult(
            PROCESS_TIMEOUT_EXIT_CODE,
            output_text(stdout),
            output_text(stderr),
            True,
            cleanup_confirmed,
        )


def run_process_to_files(
    command: list[str],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> ProcessResult:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=stdout,
            stderr=stderr,
            text=True,
            start_new_session=True,
        )
        try:
            returncode = process.wait(timeout=timeout)
            return ProcessResult(returncode or 0, "", "", False, True)
        except subprocess.TimeoutExpired:
            cleanup_confirmed = terminate_process_group(process)
            stderr.write(f"\nTimed out after {timeout or 0} seconds.\n")
            if not cleanup_confirmed:
                stderr.write("Process cleanup after timeout could not be confirmed.\n")
            return ProcessResult(PROCESS_TIMEOUT_EXIT_CODE, "", "", True, cleanup_confirmed)
