#!/usr/bin/env python3
"""Regression tests for runner-owned artifact writes."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))
SPEC = importlib.util.spec_from_file_location("artifact_io", HARNESS_DIR / "artifact_io.py")
assert SPEC is not None
ARTIFACT_IO = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ARTIFACT_IO)


class ArtifactIOTest(unittest.TestCase):
    def test_atomic_write_json_writes_complete_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "runtime" / "phase0-result.json"

            ARTIFACT_IO.atomic_write_json(path, {"status": "completed", "phase": 0})

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"status": "completed", "phase": 0},
            )
            self.assertEqual(list(path.parent.glob(".*.tmp")), [])

    def test_atomic_write_text_preserves_existing_file_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "runtime" / "phase0-gate.json"
            path.parent.mkdir(parents=True)
            path.write_text("old\n", encoding="utf-8")

            with mock.patch.object(ARTIFACT_IO.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    ARTIFACT_IO.atomic_write_text(path, "new\n")

            self.assertEqual(path.read_text(encoding="utf-8"), "old\n")
            self.assertEqual(list(path.parent.glob(".*.tmp")), [])

    def test_atomic_write_text_rejects_symlink_parent(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            outside = root / "outside"
            outside.mkdir()
            runtime = root / "runtime"
            runtime.symlink_to(outside, target_is_directory=True)

            with self.assertRaises(ARTIFACT_IO.SymlinkPathError):
                ARTIFACT_IO.atomic_write_text(runtime / "phase0-result.json", "{}\n")

            self.assertFalse((outside / "phase0-result.json").exists())

    def test_atomic_write_text_rejects_symlink_parent_outside_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            outside = root / "outside"
            outside.mkdir()
            repo = root / "repo"
            repo.mkdir()
            linked_tasks = repo / "tasks"
            linked_tasks.symlink_to(outside, target_is_directory=True)
            task_index = linked_tasks / "index.json"
            task_index.write_text('{"outside":true}\n', encoding="utf-8")

            with tempfile.TemporaryDirectory() as cwd:
                old_cwd = Path.cwd()
                try:
                    ARTIFACT_IO.os.chdir(cwd)
                    with self.assertRaises(ARTIFACT_IO.SymlinkPathError):
                        ARTIFACT_IO.atomic_write_text(task_index, '{"safe":true}\n', boundary=repo)
                finally:
                    ARTIFACT_IO.os.chdir(old_cwd)

            self.assertEqual(task_index.read_text(encoding="utf-8"), '{"outside":true}\n')

    def test_atomic_write_text_rejects_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            outside = root / "outside.txt"
            outside.write_text("outside\n", encoding="utf-8")
            runtime = root / "runtime"
            runtime.mkdir()
            target = runtime / "phase0-result.json"
            target.symlink_to(outside)

            with self.assertRaises(ARTIFACT_IO.SymlinkPathError):
                ARTIFACT_IO.atomic_write_text(target, "{}\n")

            self.assertEqual(outside.read_text(encoding="utf-8"), "outside\n")

    def test_open_append_text_appends_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "runtime" / "progress.md"

            with ARTIFACT_IO.open_append_text(path) as handle:
                handle.write("one\n")
            with ARTIFACT_IO.open_append_text(path) as handle:
                handle.write("two\n")

            self.assertEqual(path.read_text(encoding="utf-8"), "one\ntwo\n")

    def test_open_append_text_flushes_and_fsyncs_before_close(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "runtime" / "progress.md"

            with mock.patch.object(ARTIFACT_IO.os, "fsync") as fsync:
                with ARTIFACT_IO.open_append_text(path) as handle:
                    handle.write("one\n")

            fsync.assert_called_once()
            self.assertEqual(path.read_text(encoding="utf-8"), "one\n")

    def test_open_append_text_rejects_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            outside = root / "outside.log"
            outside.write_text("outside\n", encoding="utf-8")
            runtime = root / "runtime"
            runtime.mkdir()
            progress = runtime / "progress.md"
            progress.symlink_to(outside)

            with self.assertRaises(ARTIFACT_IO.SymlinkPathError):
                with ARTIFACT_IO.open_append_text(progress) as handle:
                    handle.write("runner\n")

            self.assertEqual(outside.read_text(encoding="utf-8"), "outside\n")


if __name__ == "__main__":
    unittest.main()
