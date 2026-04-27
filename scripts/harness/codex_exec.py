"""Shared Codex process runner with streaming logs and idle detection."""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Iterable


CODEX_IDLE_EXIT_CODE = 124
SKIP_ACTIVITY_DIRS = {
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


def stream_pipe_to_file(pipe, output_path: Path, activity_queue: queue.Queue[float]) -> None:
    try:
        with output_path.open("a", encoding="utf-8") as handle:
            while True:
                chunk = pipe.readline()
                if chunk == "":
                    break
                handle.write(chunk)
                handle.flush()
                activity_queue.put(time.monotonic())
    finally:
        pipe.close()


def write_prompt_to_stdin(pipe, prompt: str, activity_queue: queue.Queue[float]) -> None:
    try:
        for index in range(0, len(prompt), 64 * 1024):
            pipe.write(prompt[index : index + 64 * 1024])
            pipe.flush()
            activity_queue.put(time.monotonic())
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        try:
            pipe.close()
        except OSError:
            pass


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
    process.wait(timeout=5)


def nearest_existing_path(path: Path) -> Path | None:
    current = path
    while not current.exists():
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return current


def iter_activity_files(path: Path, max_files: int) -> Iterable[Path]:
    base = nearest_existing_path(path)
    if base is None:
        return
    yield base
    if base != path:
        return
    if not base.is_dir():
        return

    yielded = 0
    for current_root, dirs, files in os.walk(base):
        dirs[:] = [name for name in dirs if name not in SKIP_ACTIVITY_DIRS]
        current = Path(current_root)
        yield current
        for name in files:
            yield current / name
            yielded += 1
            if yielded >= max_files:
                return


def activity_marker(paths: Iterable[Path], max_files: int = 5_000) -> tuple[int, int]:
    count = 0
    latest = 0
    for path in paths:
        for candidate in iter_activity_files(path, max_files):
            try:
                mtime = candidate.stat().st_mtime_ns
            except OSError:
                continue
            count += 1
            latest = max(latest, mtime)
    return count, latest


def drain_activity_queue(activity_queue: queue.Queue[float], fallback: float) -> float:
    latest = fallback
    try:
        while True:
            latest = activity_queue.get_nowait()
    except queue.Empty:
        return latest


def run_codex_exec(
    command: list[str],
    *,
    cwd: Path,
    prompt: str,
    output_path: Path,
    stderr_path: Path,
    env: dict[str, str] | None = None,
    idle_timeout: int = 300,
    activity_paths: Iterable[Path] = (),
) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")

    activity_queue: queue.Queue[float] = queue.Queue()
    last_activity = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    threads = [
        threading.Thread(
            target=stream_pipe_to_file,
            args=(process.stdout, output_path, activity_queue),
            daemon=True,
        ),
        threading.Thread(
            target=stream_pipe_to_file,
            args=(process.stderr, stderr_path, activity_queue),
            daemon=True,
        ),
        threading.Thread(
            target=write_prompt_to_stdin,
            args=(process.stdin, prompt, activity_queue),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()

    idle_timed_out = False
    watched_paths = list(activity_paths)
    last_watched_marker = activity_marker(watched_paths)
    last_mtime_check = 0.0
    mtime_check_interval = min(2.0, max(0.1, idle_timeout / 2)) if idle_timeout > 0 else 2.0
    while process.poll() is None:
        now = time.monotonic()
        last_activity = drain_activity_queue(activity_queue, last_activity)
        if watched_paths and now - last_mtime_check >= mtime_check_interval:
            watched_marker = activity_marker(watched_paths)
            if watched_marker != last_watched_marker:
                last_watched_marker = watched_marker
                last_activity = now
            last_mtime_check = now
        if idle_timeout > 0 and now - last_activity > idle_timeout:
            idle_timed_out = True
            terminate_process_group(process)
            break
        time.sleep(0.5)

    for thread in threads:
        thread.join(timeout=5)

    if idle_timed_out:
        with stderr_path.open("a", encoding="utf-8") as handle:
            handle.write(
                "\n"
                f"[codex-harness] codex exec idle timeout after {idle_timeout} seconds "
                "with no stdout/stderr/stdin or watched file activity.\n"
            )
        return CODEX_IDLE_EXIT_CODE

    return process.returncode or 0
