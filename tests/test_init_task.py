#!/usr/bin/env python3
"""Regression tests for task skeleton creation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INIT_TASK = ROOT / "scripts" / "harness" / "init-task.py"
VERIFY_TASK = ROOT / "scripts" / "harness" / "verify-task.py"


class InitTaskTest(unittest.TestCase):
    def test_task_includes_implementation_quality_doc(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            repo = Path(raw_tmp) / "repo"
            repo.mkdir()

            result = subprocess.run(
                [
                    sys.executable,
                    str(INIT_TASK),
                    "recording-flow",
                    "--project",
                    "demo",
                    "--prompt",
                    "Build recording flow.",
                    "--phase",
                    "implementation",
                    "--root",
                    str(repo),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

            task_path = repo / "tasks" / "0-recording-flow"
            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            quality_doc = repo / "docs" / "harness" / "implementation-quality.md"
            design_review_doc = task_path / "docs" / "implementation-design-review.md"
            phase_text = (task_path / "phases" / "phase0.md").read_text(encoding="utf-8")

            self.assertTrue(quality_doc.exists())
            self.assertTrue(design_review_doc.exists())
            self.assertIn("docs/harness/implementation-quality.md", task_index["common_docs"])
            self.assertIn("tasks/0-recording-flow/docs/implementation-design-review.md", task_index["docs"])
            self.assertIn("docs/harness/implementation-quality.md", phase_text)
            quality_text = quality_doc.read_text(encoding="utf-8")
            self.assertIn("Do not add `useCallback`, `useMemo`, or `memo` by default.", quality_text)
            self.assertIn("Feature folders should contain only the folders they need.", quality_text)

    def test_verify_task_rejects_missing_implementation_quality_doc(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            repo = Path(raw_tmp) / "repo"
            repo.mkdir()
            result = subprocess.run(
                [
                    sys.executable,
                    str(INIT_TASK),
                    "recording-flow",
                    "--project",
                    "demo",
                    "--prompt",
                    "Build recording flow.",
                    "--phase",
                    "implementation",
                    "--root",
                    str(repo),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

            task_path = repo / "tasks" / "0-recording-flow"
            task_index_path = task_path / "index.json"
            task_index = json.loads(task_index_path.read_text(encoding="utf-8"))
            task_index["common_docs"] = [
                path
                for path in task_index["common_docs"]
                if path != "docs/harness/implementation-quality.md"
            ]
            task_index_path.write_text(json.dumps(task_index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            verify = subprocess.run(
                [
                    sys.executable,
                    str(VERIFY_TASK),
                    str(task_path),
                    "--root",
                    str(repo),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(verify.returncode, 0)
            self.assertIn("implementation-quality.md", verify.stdout + verify.stderr)

    def test_verify_task_rejects_missing_design_review_doc(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            repo = Path(raw_tmp) / "repo"
            repo.mkdir()
            result = subprocess.run(
                [
                    sys.executable,
                    str(INIT_TASK),
                    "recording-flow",
                    "--project",
                    "demo",
                    "--prompt",
                    "Build recording flow.",
                    "--phase",
                    "implementation",
                    "--root",
                    str(repo),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

            task_path = repo / "tasks" / "0-recording-flow"
            task_index_path = task_path / "index.json"
            task_index = json.loads(task_index_path.read_text(encoding="utf-8"))
            task_index["docs"] = [
                path
                for path in task_index["docs"]
                if path != "tasks/0-recording-flow/docs/implementation-design-review.md"
            ]
            task_index_path.write_text(json.dumps(task_index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (task_path / "docs" / "implementation-design-review.md").unlink()

            verify = subprocess.run(
                [
                    sys.executable,
                    str(VERIFY_TASK),
                    str(task_path),
                    "--root",
                    str(repo),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(verify.returncode, 0)
            self.assertIn("implementation design review", verify.stdout + verify.stderr)


if __name__ == "__main__":
    unittest.main()
