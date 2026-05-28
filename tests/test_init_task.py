#!/usr/bin/env python3
"""Regression tests for task skeleton creation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INIT_TASK = ROOT / "scripts" / "harness" / "init-task.py"
VERIFY_TASK = ROOT / "scripts" / "harness" / "verify-task.py"


class InitTaskTest(unittest.TestCase):
    def run_init_task(self, repo: Path, name: str = "recording-flow") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(INIT_TASK),
                name,
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

    def test_task_includes_implementation_quality_doc(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            repo = Path(raw_tmp) / "repo"
            repo.mkdir()

            result = self.run_init_task(repo)

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
            result = self.run_init_task(repo)
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
            result = self.run_init_task(repo)
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

    def test_parallel_task_creation_allocates_unique_top_index_entries(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            repo = Path(raw_tmp) / "repo"
            repo.mkdir()
            results: list[subprocess.CompletedProcess[str] | None] = [None] * 4

            def worker(index: int) -> None:
                results[index] = self.run_init_task(repo)

            threads = [threading.Thread(target=worker, args=(index,)) for index in range(len(results))]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            completed = [result for result in results if result is not None]
            self.assertEqual(len(completed), len(results))
            for result in completed:
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

            top_index = json.loads((repo / "tasks" / "index.json").read_text(encoding="utf-8"))
            ids = [task["id"] for task in top_index["tasks"]]
            dirs = [task["dir"] for task in top_index["tasks"]]
            self.assertEqual(sorted(ids), [0, 1, 2, 3])
            self.assertEqual(len(set(dirs)), 4)
            for task_dir in dirs:
                self.assertTrue((repo / "tasks" / task_dir / "index.json").exists())

    def test_task_creation_adopts_unregistered_orphan_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            repo = Path(raw_tmp) / "repo"
            repo.mkdir()
            (repo / "tasks" / "0-recording-flow").mkdir(parents=True)

            result = self.run_init_task(repo)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue((repo / "tasks" / "0-recording-flow" / "index.json").exists())
            top_index = json.loads((repo / "tasks" / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(top_index["tasks"][0]["id"], 0)
            self.assertEqual(top_index["tasks"][0]["dir"], "0-recording-flow")

    def test_task_creation_skips_partial_unregistered_orphan_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            repo = Path(raw_tmp) / "repo"
            repo.mkdir()
            orphan = repo / "tasks" / "0-recording-flow"
            orphan_docs = orphan / "docs"
            orphan_docs.mkdir(parents=True)
            (orphan_docs / "prd.md").write_text("stale partial task\n", encoding="utf-8")

            result = self.run_init_task(repo)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertFalse((orphan / "index.json").exists())
            self.assertEqual((orphan_docs / "prd.md").read_text(encoding="utf-8"), "stale partial task\n")
            self.assertTrue((repo / "tasks" / "1-recording-flow" / "index.json").exists())
            top_index = json.loads((repo / "tasks" / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(top_index["tasks"][0]["id"], 1)
            self.assertEqual(top_index["tasks"][0]["dir"], "1-recording-flow")


if __name__ == "__main__":
    unittest.main()
