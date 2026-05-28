#!/usr/bin/env python3
"""Regression tests for harness file locks."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))
SPEC = importlib.util.spec_from_file_location("file_lock", HARNESS_DIR / "file_lock.py")
assert SPEC is not None
FILE_LOCK = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(FILE_LOCK)


class FileLockTest(unittest.TestCase):
    def test_acquire_lock_records_metadata_and_release_removes_owned_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "runtime" / "state.lock"

            handle = FILE_LOCK.acquire_lock(path, {"scope": "tasks/index.json"})

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["pid"], os.getpid())
            self.assertEqual(payload["scope"], "tasks/index.json")

            FILE_LOCK.release_lock(handle)

            self.assertFalse(path.exists())

    def test_release_lock_does_not_delete_replaced_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "runtime" / "state.lock"
            handle = FILE_LOCK.acquire_lock(path)
            path.unlink()
            path.write_text(json.dumps({"pid": os.getpid(), "started_at": "fresh"}) + "\n", encoding="utf-8")

            FILE_LOCK.release_lock(handle)

            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["started_at"], "fresh")

    def test_unlocked_invalid_json_lock_file_is_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "runtime" / "state.lock"
            path.parent.mkdir(parents=True)
            path.write_text("", encoding="utf-8")

            handle = FILE_LOCK.acquire_lock(path)

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["pid"], os.getpid())
            FILE_LOCK.release_lock(handle)

    def test_unlocked_pid_file_for_live_process_is_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "runtime" / "state.lock"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"pid": os.getpid(), "started_at": "old"}) + "\n",
                encoding="utf-8",
            )

            handle = FILE_LOCK.acquire_lock(path)

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["pid"], os.getpid())
            self.assertNotEqual(payload["started_at"], "old")
            FILE_LOCK.release_lock(handle)

    def test_active_advisory_lock_blocks_second_acquire(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "runtime" / "state.lock"
            handle = FILE_LOCK.acquire_lock(path)
            try:
                with self.assertRaisesRegex(RuntimeError, "Another codex-harness process is active"):
                    FILE_LOCK.acquire_lock(path)
            finally:
                FILE_LOCK.release_lock(handle)

            self.assertFalse(path.exists())

    def test_stale_checks_do_not_create_missing_lock_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "runtime" / "state.lock"

            self.assertTrue(FILE_LOCK.lock_is_stale(path))
            self.assertTrue(FILE_LOCK.remove_stale_lock(path))

            self.assertFalse(path.exists())

    def test_lock_rejects_symlink_parent_with_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            outside = Path(raw_tmp) / "outside"
            outside.mkdir()
            root.mkdir()
            linked_harness = root / ".codex" / "harness"
            linked_harness.parent.mkdir(parents=True)
            linked_harness.symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(RuntimeError, "must not be a symlink"):
                FILE_LOCK.acquire_lock(linked_harness / "tasks-index.lock", boundary=root)

            self.assertFalse((outside / "tasks-index.lock").exists())

    def test_task_runtime_lock_uses_canonical_runtime_lock_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            task_path = Path(raw_tmp) / "repo" / "tasks" / "demo"

            handle = FILE_LOCK.acquire_task_runtime_lock(task_path, "evaluate-task")

            lock_path = task_path / "context-pack" / "runtime" / "run-phases.lock"
            payload = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(handle.path, lock_path)
            self.assertEqual(payload["owner"], "evaluate-task")
            self.assertEqual(payload["task_dir"], "demo")

            FILE_LOCK.release_lock(handle)

            self.assertFalse(lock_path.exists())


if __name__ == "__main__":
    unittest.main()
