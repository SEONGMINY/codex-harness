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
            "from pathlib import Path\n"
            "import sys\n"
            + textwrap.dedent(
                """
                assert "--output-schema" in sys.argv, sys.argv
                assert sys.argv[sys.argv.index("--output-schema") + 1].endswith("evaluation-final.schema.json")
                if "--output-last-message" in sys.argv:
                    Path(sys.argv[sys.argv.index("--output-last-message") + 1]).write_text(
                        '{"verdict":"approved","blockers":[],"required_followups":[]}\\n',
                        encoding="utf-8",
                    )
                sys.stdin.read()
                print('{"event":"done"}', flush=True)
                raise SystemExit(0)
                """
            ),
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | 0o111)
        return path

    def test_evaluation_prompt_artifact_redacts_secret_content(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "evaluation-prompt.md"

            EVALUATE_TASK.write_prompt_artifact(path, "Use API_KEY=sk-1234567890abcdefghijklmnop.\n")

            content = path.read_text(encoding="utf-8")
            self.assertIn("[REDACTED]", content)
            self.assertNotIn("sk-1234567890abcdefghijklmnop", content)

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

    def test_evaluation_codex_max_runtime_bounds_active_process(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            fake = tmp / "fake-codex.py"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "from __future__ import annotations\n"
                "import sys\n"
                "import time\n"
                "sys.stdin.read()\n"
                "deadline = time.monotonic() + 5\n"
                "while time.monotonic() < deadline:\n"
                "    print('{\"event\":\"active\"}', flush=True)\n"
                "    time.sleep(0.1)\n",
                encoding="utf-8",
            )
            fake.chmod(fake.stat().st_mode | 0o111)
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
                max_runtime=1,
            )

            self.assertEqual(returncode, EVALUATE_TASK.CODEX_MAX_RUNTIME_EXIT_CODE)
            self.assertIn('{"event":"active"}', output_path.read_text(encoding="utf-8"))
            self.assertIn("max runtime timeout", stderr_path.read_text(encoding="utf-8"))

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

    def test_evaluation_writes_commit_for_artifact_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root = tmp / "repo"
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
                        "phases": [],
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
            fake = self.make_fake_codex(tmp)

            result = subprocess.run(
                [
                    sys.executable,
                    str(HARNESS_DIR / "evaluate-task.py"),
                    "demo",
                    "--root",
                    str(root),
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            commit_path = task_path / "context-pack" / "runtime" / "evaluation-commit.json"
            commit = json.loads(commit_path.read_text(encoding="utf-8"))
            self.assertEqual(commit["commit_scope"], "evaluation_bundle")
            self.assertEqual(commit["verdict"], "approved")
            self.assertEqual(commit["phase_proofs"], [])
            self.assertEqual(commit["repair_proofs"], [])
            by_name = {item["name"]: item for item in commit["evaluation_artifacts"]}
            self.assertEqual(
                by_name["last_message"]["sha256"],
                EVALUATE_TASK.file_sha256(task_path / "context-pack" / "runtime" / "evaluation-last-message.json"),
            )
            self.assertEqual(
                commit["task_index"]["sha256"],
                EVALUATE_TASK.file_sha256(task_path / "index.json"),
            )

    def test_evaluation_commit_seals_existing_repair_results(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root = tmp / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            static_dir = task_path / "context-pack" / "static"
            runtime_dir.mkdir(parents=True)
            static_dir.mkdir(parents=True)
            (runtime_dir / "evaluation-repair1-result.json").write_text(
                '{"schema_version":1,"iteration":1}\n',
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "project": "demo",
                        "task": "demo",
                        "docs": [],
                        "common_docs": [],
                        "evaluation_commands": ["true"],
                        "phases": [],
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
            fake = self.make_fake_codex(tmp)

            result = subprocess.run(
                [
                    sys.executable,
                    str(HARNESS_DIR / "evaluate-task.py"),
                    "demo",
                    "--root",
                    str(root),
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            commit = json.loads((runtime_dir / "evaluation-commit.json").read_text(encoding="utf-8"))
            self.assertEqual(commit["repair_proofs"][0]["iteration"], 1)
            self.assertEqual(
                commit["repair_proofs"][0]["result"]["sha256"],
                EVALUATE_TASK.file_sha256(runtime_dir / "evaluation-repair1-result.json"),
            )

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

    def test_strict_current_harness_blocks_stale_policy_before_writing_evaluation_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            task_path = root / "tasks" / "demo"
            static_dir = task_path / "context-pack" / "static"
            runtime_dir = task_path / "context-pack" / "runtime"
            static_dir.mkdir(parents=True)
            runtime_dir.mkdir(parents=True)
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

            result = subprocess.run(
                [
                    sys.executable,
                    str(HARNESS_DIR / "evaluate-task.py"),
                    "demo",
                    "--root",
                    str(root),
                    "--dry-run",
                    "--strict-current-harness",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("active_policy_pack", result.stderr)
            self.assertFalse((runtime_dir / "evaluation-command-results.json").exists())
            self.assertFalse((runtime_dir / "evaluation-prompt.md").exists())


if __name__ == "__main__":
    unittest.main()
