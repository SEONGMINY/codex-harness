#!/usr/bin/env python3
"""Regression tests for evaluation Codex execution."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))
SPEC = importlib.util.spec_from_file_location("evaluate_task", HARNESS_DIR / "evaluate-task.py")
assert SPEC is not None
EVALUATE_TASK = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(EVALUATE_TASK)


class EvaluateTaskTest(unittest.TestCase):
    def make_fake_codex(self, tmp: Path) -> Path:
        path = tmp / "fake-codex.py"
        path.write_text(
            "#!/usr/bin/env python3\n"
            "from __future__ import annotations\n"
            "import sys\n"
            + textwrap.dedent(
                """
                assert "--output-schema" in sys.argv, sys.argv
                assert sys.argv[sys.argv.index("--output-schema") + 1].endswith("evaluation-final.schema.json")
                sys.stdin.read()
                print('{"event":"done"}', flush=True)
                raise SystemExit(0)
                """
            ),
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | 0o111)
        return path

    def test_evaluation_codex_uses_output_schema(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            fake = self.make_fake_codex(tmp)
            output_path = tmp / "evaluation-output.jsonl"
            stderr_path = tmp / "evaluation-stderr.txt"

            returncode = EVALUATE_TASK.run_codex(
                tmp,
                "prompt",
                output_path,
                stderr_path,
                None,
                str(fake),
                False,
                False,
                10,
                [tmp],
            )

            self.assertEqual(returncode, 0, stderr_path.read_text(encoding="utf-8"))
            self.assertIn('{"event":"done"}', output_path.read_text(encoding="utf-8"))

    def test_dry_run_writes_metadata_object_without_prompting_on_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            static_dir = task_path / "context-pack" / "static"
            static_dir.mkdir(parents=True)
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "project": "demo",
                        "task": "demo",
                        "docs": [],
                        "common_docs": [],
                        "evaluation_commands": ["true"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            active_policy_pack = {
                key: value
                for key, value in EVALUATE_TASK.runtime_policy_pack().items()
                if key in {"id", "schema_version", "sha256"}
            }
            (static_dir / "design-approval.json").write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "active_policy_pack": active_policy_pack,
                        "approved_policy_packs": [active_policy_pack],
                        "approved_bundle_sha256": "bundle-sha",
                        "design_approval_scope_sha256": "scope-sha",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(HARNESS_DIR / "evaluate-task.py"),
                    "demo",
                    "--root",
                    str(root),
                    "--dry-run",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            command_results = json.loads(
                (task_path / "context-pack" / "runtime" / "evaluation-command-results.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(command_results["schema_version"], 1)
            self.assertIn("policy_pack", command_results)
            self.assertIn("harness_attestation", command_results)
            self.assertEqual(command_results["design_approval_scope_sha256"], "scope-sha")
            self.assertEqual(command_results["commands"][0]["command"], "true")
            prompt = (task_path / "context-pack" / "runtime" / "evaluation-prompt.md").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("policy_pack", prompt)
            self.assertIn('"command": "true"', prompt)

    def test_standalone_evaluation_refuses_active_task_runtime_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            (task_path / "context-pack" / "runtime").mkdir(parents=True)
            lock_handle = EVALUATE_TASK.acquire_task_runtime_lock(task_path, "run-phases")
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        str(HARNESS_DIR / "evaluate-task.py"),
                        "demo",
                        "--root",
                        str(root),
                        "--dry-run",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )
            finally:
                EVALUATE_TASK.release_lock(lock_handle)

            self.assertEqual(result.returncode, 1)
            self.assertIn("Another codex-harness task operation is active", result.stderr)
            self.assertFalse((task_path / "context-pack" / "runtime" / "evaluation-prompt.md").exists())

    def test_standalone_evaluation_refuses_active_repo_execution_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            (task_path / "context-pack" / "runtime").mkdir(parents=True)
            lock_handle = EVALUATE_TASK.acquire_repo_execution_lock(
                root,
                "run-phases",
                task_path=task_path,
            )
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        str(HARNESS_DIR / "evaluate-task.py"),
                        "demo",
                        "--root",
                        str(root),
                        "--dry-run",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )
            finally:
                EVALUATE_TASK.release_lock(lock_handle)

            self.assertEqual(result.returncode, 1)
            self.assertIn("Another codex-harness repo execution is active", result.stderr)
            self.assertFalse((task_path / "context-pack" / "runtime" / "evaluation-prompt.md").exists())
            self.assertFalse((task_path / "context-pack" / "runtime" / "run-phases.lock").exists())

    def test_current_policy_lineage_errors_rejects_unapproved_evaluation_policy(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            task_path = Path(raw_tmp) / "tasks" / "demo"
            static_dir = task_path / "context-pack" / "static"
            static_dir.mkdir(parents=True)
            current = {
                key: value
                for key, value in EVALUATE_TASK.runtime_policy_pack().items()
                if key in {"id", "schema_version", "sha256"}
            }
            stale = dict(current)
            stale["sha256"] = "stale"
            (static_dir / "design-approval.json").write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "active_policy_pack": stale,
                        "approved_policy_packs": [stale],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = EVALUATE_TASK.current_policy_lineage_errors(task_path)

            self.assertTrue(any("active_policy_pack" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
