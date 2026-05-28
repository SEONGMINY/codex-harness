#!/usr/bin/env python3
"""Regression tests for harness task path resolution."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))

import task_paths  # noqa: E402


class TaskPathsTest(unittest.TestCase):
    def test_resolves_task_name_under_repo_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            task_path.mkdir(parents=True)

            self.assertEqual(task_paths.resolve_task_path(root, "demo"), task_path.resolve())

    def test_resolves_root_relative_tasks_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            task_path.mkdir(parents=True)

            self.assertEqual(task_paths.resolve_task_path(root, "tasks/demo"), task_path.resolve())

    def test_resolves_absolute_task_path_inside_repo_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            task_path.mkdir(parents=True)

            self.assertEqual(task_paths.resolve_task_path(root, str(task_path)), task_path.resolve())

    def test_rejects_absolute_task_path_outside_repo_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root = tmp / "repo"
            outside_task = tmp / "outside" / "tasks" / "demo"
            outside_task.mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "must be under"):
                task_paths.resolve_task_path(root, str(outside_task))

    def test_rejects_symlink_that_points_outside_repo_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root = tmp / "repo"
            outside_task = tmp / "outside" / "demo"
            outside_task.mkdir(parents=True)
            tasks_root = root / "tasks"
            tasks_root.mkdir(parents=True)
            (tasks_root / "linked").symlink_to(outside_task, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "must be under"):
                task_paths.resolve_task_path(root, "linked")


if __name__ == "__main__":
    unittest.main()
