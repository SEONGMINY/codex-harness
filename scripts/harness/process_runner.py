"""Process helpers that clean up child process groups on timeout."""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import NamedTuple


PROCESS_TIMEOUT_EXIT_CODE = 124


class ProcessResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool


def output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        process.terminate()

    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        return


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
        return ProcessResult(process.returncode or 0, output_text(stdout), output_text(stderr), False)
    except subprocess.TimeoutExpired:
        terminate_process_group(process)
        stdout, stderr = process.communicate()
        return ProcessResult(PROCESS_TIMEOUT_EXIT_CODE, output_text(stdout), output_text(stderr), True)


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
            return ProcessResult(returncode or 0, "", "", False)
        except subprocess.TimeoutExpired:
            terminate_process_group(process)
            stderr.write(f"\nTimed out after {timeout or 0} seconds.\n")
            return ProcessResult(PROCESS_TIMEOUT_EXIT_CODE, "", "", True)
