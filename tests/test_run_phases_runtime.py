#!/usr/bin/env python3
"""Runtime tests for run-phases child Codex handling."""

from __future__ import annotations

import importlib.util
import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))
SPEC = importlib.util.spec_from_file_location("run_phases", HARNESS_DIR / "run-phases.py")
assert SPEC is not None
RUN_PHASES = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RUN_PHASES)
import env_policy  # noqa: E402
import file_lock  # noqa: E402


class RunCodexRuntimeTest(unittest.TestCase):
    def test_runner_install_check_requires_runtime_helper_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            scripts = root / ".codex" / "harness" / "scripts"
            (scripts / "schemas").mkdir(parents=True)
            (scripts / "policy-packs").mkdir(parents=True)
            (root / "codex-harness.json").write_text(
                json.dumps({"name": "codex-harness", "version": RUN_PHASES.HARNESS_VERSION}) + "\n",
                encoding="utf-8",
            )
            for raw_path in [
                "artifact_io.py",
                "codex_exec.py",
                "command_policy.py",
                "decision_registry.py",
                "env_policy.py",
                "evidence_obligations.py",
                "evaluate-task.py",
                "file_lock.py",
                "install_preflight.py",
                "obligation_ledger.py",
                "phase_contract.py",
                "phase_semantics.py",
                "policy_pack.py",
                "process_runner.py",
                "reference_resolver.py",
                "redaction.py",
                "run-phases.py",
                "runtime_protocol.py",
                "verify-task.py",
                "run-quality-checks.py",
                "relationship_graph.py",
                "scope_policy.py",
                "task_paths.py",
                "policy-packs/default-security.json",
                "schemas/phase-final.schema.json",
                "schemas/evaluation-final.schema.json",
            ]:
                (scripts / raw_path).parent.mkdir(parents=True, exist_ok=True)
                (scripts / raw_path).write_text("{}\n", encoding="utf-8")
            (root / ".codex" / "harness" / "install-manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "harness_version": RUN_PHASES.HARNESS_VERSION,
                        "runtime_attestation": RUN_PHASES.harness_attestation(scripts),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (scripts / "artifact_io.py").unlink()

            errors = RUN_PHASES.harness_install_errors(root)

        self.assertTrue(any("artifact_io.py" in error for error in errors), errors)

    def test_runner_install_check_rejects_runtime_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            scripts = root / ".codex" / "harness" / "scripts"
            root.mkdir()
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "install-codex-harness.py"),
                    str(root),
                    "--scope",
                    "project",
                    "--force",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            (scripts / "scope_policy.py").write_text("# stale\n", encoding="utf-8")

            errors = RUN_PHASES.harness_install_errors(root)

        self.assertTrue(any("runtime drift" in error for error in errors), errors)

    def test_runner_install_check_rejects_decision_registry_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            scripts = root / ".codex" / "harness" / "scripts"
            root.mkdir()
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "install-codex-harness.py"),
                    str(root),
                    "--scope",
                    "project",
                    "--force",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            (scripts / "decision_registry.py").write_text("# stale\n", encoding="utf-8")

            errors = RUN_PHASES.harness_install_errors(root)

        self.assertTrue(any("runtime drift" in error for error in errors), errors)

    def test_runner_install_check_rejects_schema_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            scripts = root / ".codex" / "harness" / "scripts"
            root.mkdir()
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "install-codex-harness.py"),
                    str(root),
                    "--scope",
                    "project",
                    "--force",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            (scripts / "schemas" / "phase-final.schema.json").write_text('{"stale":true}\n', encoding="utf-8")

            errors = RUN_PHASES.harness_install_errors(root)

        self.assertTrue(any("runtime drift" in error for error in errors), errors)

    def test_write_json_uses_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "runtime" / "phase0-result.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"status":"old"}\n', encoding="utf-8")

            with mock.patch.object(RUN_PHASES, "atomic_write_json", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    RUN_PHASES.write_json(path, {"status": "new"})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"status": "old"})

    def test_stale_lock_reclaim_does_not_delete_replaced_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            lock_path = Path(raw_tmp) / "tasks" / "demo" / "context-pack" / "runtime" / "run-phases.lock"
            lock_path.parent.mkdir(parents=True)
            lock_path.write_text('{"pid":123,"started_at":"old"}\n', encoding="utf-8")
            original_file_identity = file_lock.file_identity

            def replace_lock_before_identity_check(path: Path) -> tuple[int, int, int, int]:
                lock_path.unlink()
                lock_path.write_text(
                    json.dumps({"pid": os.getpid(), "started_at": "fresh"}) + "\n",
                    encoding="utf-8",
                )
                return original_file_identity(path)

            with mock.patch.object(file_lock, "file_identity", side_effect=replace_lock_before_identity_check):
                removed = RUN_PHASES.remove_stale_lock(lock_path)

            self.assertFalse(removed)
            self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8"))["started_at"], "fresh")

    def test_acquire_lock_reclaims_unlocked_partial_lock_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            lock_path = Path(raw_tmp) / "runtime" / "run-phases.lock"
            lock_path.parent.mkdir(parents=True)
            lock_path.write_text("", encoding="utf-8")

            handle = RUN_PHASES.acquire_lock(lock_path)

            payload = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["pid"], os.getpid())
            RUN_PHASES.release_lock(handle)

    def test_acquire_lock_treats_held_partial_lock_as_active(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            lock_path = Path(raw_tmp) / "runtime" / "run-phases.lock"
            handle = RUN_PHASES.acquire_lock(lock_path)
            try:
                with self.assertRaises(RuntimeError):
                    RUN_PHASES.acquire_lock(lock_path)
            finally:
                RUN_PHASES.release_lock(handle)

    def test_acquire_lock_rejects_symlink_parent(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            real_runtime = tmp / "real-runtime"
            real_runtime.mkdir()
            symlink_runtime = tmp / "runtime"
            symlink_runtime.symlink_to(real_runtime, target_is_directory=True)

            with self.assertRaisesRegex(RuntimeError, "must not be a symlink"):
                RUN_PHASES.acquire_lock(symlink_runtime / "run-phases.lock")

            self.assertFalse((real_runtime / "run-phases.lock").exists())

    def test_acquire_lock_rejects_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            runtime = tmp / "runtime"
            runtime.mkdir()
            external_lock = tmp / "external.lock"
            external_lock.write_text('{"pid":-1}\n', encoding="utf-8")
            lock_path = runtime / "run-phases.lock"
            lock_path.symlink_to(external_lock)

            with self.assertRaisesRegex(RuntimeError, "must not be a symlink"):
                RUN_PHASES.acquire_lock(lock_path)

            self.assertTrue(lock_path.is_symlink())
            self.assertEqual(external_lock.read_text(encoding="utf-8"), '{"pid":-1}\n')

    def test_release_lock_does_not_delete_replaced_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            lock_path = Path(raw_tmp) / "runtime" / "run-phases.lock"
            handle = RUN_PHASES.acquire_lock(lock_path)
            lock_path.unlink()
            lock_path.write_text(
                json.dumps({"pid": os.getpid(), "started_at": "fresh"}) + "\n",
                encoding="utf-8",
            )

            RUN_PHASES.release_lock(handle)

            self.assertTrue(lock_path.exists())
            self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8"))["started_at"], "fresh")

    def test_run_shell_records_timeout_instead_of_raising(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            script = Path(raw_tmp) / "sleep.py"
            script.write_text("import time\ntime.sleep(2)\n", encoding="utf-8")
            returncode, output, timed_out = RUN_PHASES.run_shell(
                f"{sys.executable} {script}",
                Path(raw_tmp),
                1,
            )

            self.assertEqual(returncode, 124)
            self.assertTrue(timed_out)
            self.assertIn("timeout", output)

    def test_run_shell_rejects_shell_control_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            returncode, output, timed_out = RUN_PHASES.run_shell(
                "echo ok && echo unsafe",
                Path(raw_tmp),
                10,
            )

            self.assertEqual(returncode, 126)
            self.assertFalse(timed_out)
            self.assertIn("command-policy", output)

    def test_run_shell_redacts_secret_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            script = Path(raw_tmp) / "print_secret.py"
            script.write_text('print("API_KEY=sk-1234567890abcdefghijklmnop")\n', encoding="utf-8")
            returncode, output, timed_out = RUN_PHASES.run_shell(
                f"{sys.executable} {script}",
                Path(raw_tmp),
                10,
            )

            self.assertEqual(returncode, 0)
            self.assertFalse(timed_out)
            self.assertIn("[REDACTED]", output)
            self.assertNotIn("sk-1234567890abcdefghijklmnop", output)

    def test_env_policy_drops_sensitive_env_and_preserves_known_harness_env(self) -> None:
        env = env_policy.sanitized_env(
            {
                "PATH": "/bin",
                "HARNESS_SECRET_TOKEN": "secret",
                "OPENAI_API_KEY": "secret",
                "CODEX_HARNESS_ACTIVE": "1",
                "CODEX_HARNESS_UNKNOWN_CONTROL": "unsafe",
            }
        )

        self.assertEqual(env["PATH"], "/bin")
        self.assertEqual(env["CODEX_HARNESS_ACTIVE"], "1")
        self.assertNotIn("CODEX_HARNESS_UNKNOWN_CONTROL", env)
        self.assertNotIn("HARNESS_SECRET_TOKEN", env)
        self.assertNotIn("OPENAI_API_KEY", env)

    def test_run_shell_does_not_inherit_sensitive_env(self) -> None:
        old_value = os.environ.get("HARNESS_MARKER")
        os.environ["HARNESS_MARKER"] = "secret"
        try:
            with tempfile.TemporaryDirectory() as raw_tmp:
                script = Path(raw_tmp) / "print_env.py"
                script.write_text(
                    'import os\nprint(os.environ.get("HARNESS_MARKER", "missing"))\n',
                    encoding="utf-8",
                )
                returncode, output, timed_out = RUN_PHASES.run_shell(
                    f"{sys.executable} {script}",
                    Path(raw_tmp),
                    10,
                )
        finally:
            if old_value is None:
                os.environ.pop("HARNESS_MARKER", None)
            else:
                os.environ["HARNESS_MARKER"] = old_value

        self.assertEqual(returncode, 0)
        self.assertFalse(timed_out)
        self.assertEqual(output, "missing")

    def test_phase_codex_child_does_not_inherit_sensitive_env(self) -> None:
        old_value = os.environ.get("HARNESS_MARKER")
        os.environ["HARNESS_MARKER"] = "secret"
        try:
            with tempfile.TemporaryDirectory() as raw_tmp:
                tmp = Path(raw_tmp)
                root, task_path = self.make_task(tmp)
                fake = self.make_fake_codex(
                    tmp,
                    textwrap.dedent(
                        """
                        import os
                        assert os.environ.get("CODEX_HARNESS_ACTIVE") == "1"
                        assert "HARNESS_MARKER" not in os.environ
                        sys.stdin.read()
                        raise SystemExit(0)
                        """
                    ),
                )
                output_path = task_path / "context-pack" / "runtime" / "phase1-output-attempt1.jsonl"
                stderr_path = task_path / "context-pack" / "runtime" / "phase1-stderr-attempt1.txt"
                returncode = RUN_PHASES.run_codex(
                    root,
                    task_path,
                    1,
                    "prompt",
                    output_path,
                    stderr_path,
                    str(fake),
                    False,
                    False,
                    10,
                )
                stderr_text = stderr_path.read_text(encoding="utf-8")
        finally:
            if old_value is None:
                os.environ.pop("HARNESS_MARKER", None)
            else:
                os.environ["HARNESS_MARKER"] = old_value

        self.assertEqual(returncode, 0, stderr_text)

    def test_phase_attempt_commit_records_result_and_artifact_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            handoffs = task_path / "context-pack" / "handoffs"
            runtime.mkdir(parents=True, exist_ok=True)
            handoffs.mkdir(parents=True, exist_ok=True)
            paths = {
                "contract": RUN_PHASES.phase_contract_path(task_path, 0),
                "checklist": RUN_PHASES.phase_checklist_path(task_path, 0),
                "prompt": runtime / "phase0-prompt.md",
                "stdout": runtime / "phase0-output-attempt1.jsonl",
                "stderr": runtime / "phase0-stderr-attempt1.txt",
                "ac": RUN_PHASES.ac_results_path(task_path, 0, 1),
                "quality": RUN_PHASES.phase_quality_path(task_path, 0),
                "handoff": RUN_PHASES.phase_handoff_path(task_path, 0),
                "evidence": RUN_PHASES.phase_evidence_path(task_path, 0),
                "gate": RUN_PHASES.phase_gate_path(task_path, 0),
                "reconciliation": RUN_PHASES.phase_reconciliation_path(task_path, 0),
                "reconciliation_summary": RUN_PHASES.phase_reconciliation_summary_path(task_path, 0),
            }
            for name, path in paths.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{name}\n", encoding="utf-8")
            (task_path / "context-pack" / "static").mkdir(parents=True, exist_ok=True)
            (task_path / "context-pack" / "static" / "design-approval.json").write_text(
                '{"approved_bundle_sha256":"approved-bundle"}\n',
                encoding="utf-8",
            )
            repo_output = root / "src" / "generated.py"
            repo_output.parent.mkdir(parents=True, exist_ok=True)
            repo_output.write_text("before\n", encoding="utf-8")
            before_repo_outputs = RUN_PHASES.required_repo_output_content_results(
                root,
                ["src/generated.py"],
            )
            before_snapshot = {"src/generated.py": RUN_PHASES.file_digest(repo_output)}
            repo_output.write_text("after\n", encoding="utf-8")
            after_snapshot = {"src/generated.py": RUN_PHASES.file_digest(repo_output)}

            result_path = RUN_PHASES.write_phase_result(
                root,
                task_path,
                0,
                1,
                0,
                [],
                [{"command": "true", "exit_code": 0}],
                ["context-pack/handoffs/phase0.md"],
                ["src/generated.py"],
                paths["prompt"],
                paths["stdout"],
                paths["stderr"],
                paths["ac"],
                before_repo_outputs,
                before_snapshot,
                after_snapshot,
            )
            commit_path = RUN_PHASES.write_phase_attempt_commit(task_path, 0, 1, result_path)

            result = json.loads(result_path.read_text(encoding="utf-8"))
            commit = json.loads(commit_path.read_text(encoding="utf-8"))
            self.assertEqual(result["artifacts"]["attempt_commit"], "context-pack/runtime/phase0-attempt1-commit.json")
            self.assertEqual(commit["schema_version"], 1)
            self.assertEqual(commit["commit_scope"], "runtime_attempt_bundle")
            self.assertEqual(commit["status"], "committed")
            self.assertEqual(result["design_approval_bundle_sha256"], "approved-bundle")
            self.assertEqual(commit["design_approval_bundle_sha256"], "approved-bundle")
            self.assertEqual(commit["result"]["path"], "context-pack/runtime/phase0-result-attempt1.json")
            self.assertEqual(commit["result"]["sha256"], RUN_PHASES.file_sha256(result_path))
            self.assertEqual(
                json.loads(RUN_PHASES.phase_result_path(task_path, 0).read_text(encoding="utf-8")),
                result,
            )
            self.assertEqual(commit["artifact_count"], len(commit["artifacts"]))
            by_name = {item["name"]: item for item in commit["artifacts"]}
            self.assertEqual(by_name["gate"]["sha256"], RUN_PHASES.file_sha256(paths["gate"]))
            self.assertEqual(commit["repo_content"], result["repo_content"])
            self.assertEqual(
                commit["repo_content"]["required_repo_outputs"][0]["before"]["sha256"],
                before_repo_outputs[0]["sha256"],
            )
            self.assertEqual(
                commit["repo_content"]["required_repo_outputs"][0]["after"]["sha256"],
                RUN_PHASES.file_sha256(repo_output),
            )
            self.assertEqual(
                commit["repo_content"]["changed_files_digest"],
                RUN_PHASES.stable_json_sha256(commit["repo_content"]["changed_files"]),
            )

    def test_ac_results_records_runtime_metadata_and_command_digest(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            _root, task_path = self.make_task(Path(raw_tmp))
            commands = [
                {
                    "command": "python3 -m unittest",
                    "exit_code": 0,
                    "output": "ok\n",
                    "timed_out": False,
                }
            ]

            path = RUN_PHASES.write_ac_results(task_path, 0, 1, commands)
            data = json.loads(path.read_text(encoding="utf-8"))

            identities = [RUN_PHASES.command_result_identity(item) for item in commands]
            self.assertEqual(data["schema_version"], 1)
            self.assertEqual(data["runner_version"], RUN_PHASES.HARNESS_VERSION)
            self.assertEqual(data["policy_pack"], RUN_PHASES.runtime_policy_pack())
            self.assertEqual(data["harness_attestation"], RUN_PHASES.RUNTIME_HARNESS_ATTESTATION)
            self.assertEqual(data["commands_digest"], RUN_PHASES.stable_json_sha256(identities))
            self.assertEqual(data["commands"], commands)

    def test_attempt_result_keeps_old_commit_valid_after_phase_result_alias_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            handoffs = task_path / "context-pack" / "handoffs"
            runtime.mkdir(parents=True, exist_ok=True)
            handoffs.mkdir(parents=True, exist_ok=True)
            shared_paths = {
                "contract": RUN_PHASES.phase_contract_path(task_path, 0),
                "checklist": RUN_PHASES.phase_checklist_path(task_path, 0),
                "quality": RUN_PHASES.phase_quality_path(task_path, 0),
                "handoff": RUN_PHASES.phase_handoff_path(task_path, 0),
                "evidence": RUN_PHASES.phase_evidence_path(task_path, 0),
                "gate": RUN_PHASES.phase_gate_path(task_path, 0),
                "reconciliation": RUN_PHASES.phase_reconciliation_path(task_path, 0),
                "reconciliation_summary": RUN_PHASES.phase_reconciliation_summary_path(task_path, 0),
            }
            for name, path in shared_paths.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{name}\n", encoding="utf-8")

            def write_attempt(attempt: int) -> tuple[Path, Path]:
                RUN_PHASES.phase_handoff_path(task_path, 0).write_text(
                    f"handoff attempt {attempt}\n",
                    encoding="utf-8",
                )
                prompt = RUN_PHASES.phase_attempt_prompt_path(task_path, 0, attempt)
                stdout = runtime / f"phase0-output-attempt{attempt}.jsonl"
                stderr = runtime / f"phase0-stderr-attempt{attempt}.txt"
                ac = RUN_PHASES.ac_results_path(task_path, 0, attempt)
                for path in [prompt, stdout, stderr, ac]:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(f"attempt {attempt}\n", encoding="utf-8")
                result_path = RUN_PHASES.write_phase_result(
                    root,
                    task_path,
                    0,
                    attempt,
                    0,
                    [f"src/attempt{attempt}.py"],
                    [{"command": "true", "exit_code": 0}],
                    ["context-pack/handoffs/phase0.md"],
                    [],
                    prompt,
                    stdout,
                    stderr,
                    ac,
                )
                return result_path, RUN_PHASES.write_phase_attempt_commit(task_path, 0, attempt, result_path)

            result1, commit1 = write_attempt(1)
            result2, commit2 = write_attempt(2)
            alias_result = json.loads(RUN_PHASES.phase_result_path(task_path, 0).read_text(encoding="utf-8"))
            self.assertEqual(alias_result["attempt"], 2)
            self.assertEqual(json.loads(result1.read_text(encoding="utf-8"))["attempt"], 1)
            self.assertEqual(json.loads(result2.read_text(encoding="utf-8"))["attempt"], 2)
            commit2.unlink()

            latest = RUN_PHASES.latest_valid_phase_attempt_commit(task_path, 0)

            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertEqual(latest["attempt"], 1)
            self.assertEqual(latest["result"]["path"], "context-pack/runtime/phase0-result-attempt1.json")
            self.assertEqual(latest["result"]["sha256"], RUN_PHASES.file_sha256(result1))
            latest_artifacts = {item["name"]: item for item in latest["artifacts"]}
            self.assertEqual(
                latest_artifacts["handoff"]["path"],
                "context-pack/runtime/phase0-handoff-attempt1.md",
            )
            self.assertEqual(json.loads(commit1.read_text(encoding="utf-8"))["attempt"], 1)

    def test_runtime_projection_does_not_recover_stale_runner_metadata_commit(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            handoffs = task_path / "context-pack" / "handoffs"
            runtime.mkdir(parents=True, exist_ok=True)
            handoffs.mkdir(parents=True, exist_ok=True)
            for path in [
                RUN_PHASES.phase_contract_path(task_path, 0),
                RUN_PHASES.phase_checklist_path(task_path, 0),
                RUN_PHASES.phase_quality_path(task_path, 0),
                RUN_PHASES.phase_evidence_path(task_path, 0),
                RUN_PHASES.phase_gate_path(task_path, 0),
                RUN_PHASES.phase_reconciliation_path(task_path, 0),
                RUN_PHASES.phase_reconciliation_summary_path(task_path, 0),
                RUN_PHASES.phase_handoff_path(task_path, 0),
            ]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("artifact\n", encoding="utf-8")
            prompt = RUN_PHASES.phase_attempt_prompt_path(task_path, 0, 1)
            stdout = runtime / "phase0-output-attempt1.jsonl"
            stderr = runtime / "phase0-stderr-attempt1.txt"
            ac = RUN_PHASES.write_ac_results(task_path, 0, 1, [{"command": "true", "exit_code": 0}])
            for path in [prompt, stdout, stderr]:
                path.write_text("attempt 1\n", encoding="utf-8")
            result_path = RUN_PHASES.write_phase_result(
                root,
                task_path,
                0,
                1,
                0,
                [],
                [{"command": "true", "exit_code": 0}],
                ["context-pack/handoffs/phase0.md"],
                [],
                prompt,
                stdout,
                stderr,
                ac,
            )
            commit_path = RUN_PHASES.write_phase_attempt_commit(task_path, 0, 1, result_path)
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["runner_version"] = "0.0.0"
            result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
            commit = json.loads(commit_path.read_text(encoding="utf-8"))
            commit["runner_version"] = "0.0.0"
            commit["result"]["sha256"] = RUN_PHASES.file_sha256(result_path)
            commit_path.write_text(json.dumps(commit) + "\n", encoding="utf-8")

            self.assertIsNone(RUN_PHASES.latest_valid_phase_attempt_commit(task_path, 0))

    def test_running_projection_does_not_recover_old_commit_after_new_result_before_commit_crash(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            handoffs = task_path / "context-pack" / "handoffs"
            runtime.mkdir(parents=True, exist_ok=True)
            handoffs.mkdir(parents=True, exist_ok=True)
            shared_paths = {
                "contract": RUN_PHASES.phase_contract_path(task_path, 0),
                "checklist": RUN_PHASES.phase_checklist_path(task_path, 0),
                "quality": RUN_PHASES.phase_quality_path(task_path, 0),
                "handoff": RUN_PHASES.phase_handoff_path(task_path, 0),
                "evidence": RUN_PHASES.phase_evidence_path(task_path, 0),
                "gate": RUN_PHASES.phase_gate_path(task_path, 0),
                "reconciliation": RUN_PHASES.phase_reconciliation_path(task_path, 0),
                "reconciliation_summary": RUN_PHASES.phase_reconciliation_summary_path(task_path, 0),
            }
            for name, path in shared_paths.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{name}\n", encoding="utf-8")

            def attempt_paths(attempt: int) -> tuple[Path, Path, Path, Path]:
                prompt = RUN_PHASES.phase_attempt_prompt_path(task_path, 0, attempt)
                stdout = runtime / f"phase0-output-attempt{attempt}.jsonl"
                stderr = runtime / f"phase0-stderr-attempt{attempt}.txt"
                ac = RUN_PHASES.ac_results_path(task_path, 0, attempt)
                for path in [prompt, stdout, stderr, ac]:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(f"attempt {attempt}\n", encoding="utf-8")
                return prompt, stdout, stderr, ac

            prompt1, stdout1, stderr1, ac1 = attempt_paths(1)
            result1 = RUN_PHASES.write_phase_result(
                root,
                task_path,
                0,
                1,
                0,
                ["src/attempt1.py"],
                [{"command": "true", "exit_code": 0}],
                ["context-pack/handoffs/phase0.md"],
                [],
                prompt1,
                stdout1,
                stderr1,
                ac1,
            )
            RUN_PHASES.write_phase_attempt_commit(task_path, 0, 1, result1)
            prompt2, stdout2, stderr2, ac2 = attempt_paths(2)
            RUN_PHASES.write_phase_result(
                root,
                task_path,
                0,
                2,
                0,
                ["src/attempt2.py"],
                [{"command": "true", "exit_code": 0}],
                ["context-pack/handoffs/phase0.md"],
                [],
                prompt2,
                stdout2,
                stderr2,
                ac2,
            )
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "running", "attempts": 2}]}) + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(changes[0]["reason"], "interrupted_running_phase")
            self.assertEqual(task_index["phases"][0]["status"], "error")

    def test_running_projection_marks_started_attempt_without_terminal_proof_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            prompt = RUN_PHASES.phase_attempt_prompt_path(task_path, 0, 1)
            stdout = task_path / "context-pack" / "runtime" / "phase0-output-attempt1.jsonl"
            stderr = task_path / "context-pack" / "runtime" / "phase0-stderr-attempt1.txt"
            for path in [prompt, stdout, stderr]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("started\n", encoding="utf-8")
            RUN_PHASES.append_attempt_manifest_record(
                task_path,
                0,
                1,
                "attempt_started",
                status="running",
                artifacts=[
                    RUN_PHASES.artifact_ref(task_path, "prompt", prompt),
                    RUN_PHASES.artifact_ref(task_path, "stdout", stdout),
                    RUN_PHASES.artifact_ref(task_path, "stderr", stderr),
                ],
            )
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "running", "attempts": 1}]}) + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            manifest = self.read_attempt_manifest(task_path, 0)
            self.assertEqual(changes[0]["reason"], "interrupted_running_attempt")
            self.assertEqual(task_index["phases"][0]["status"], "error")
            self.assertIn("terminal runtime proof", task_index["phases"][0]["error_message"])
            self.assertEqual([item["record_type"] for item in manifest], ["attempt_started", "attempt_interrupted"])
            self.assertTrue(RUN_PHASES.phase_attempt_repair_packet_path(task_path, 0, 1).exists())
            packet = json.loads(RUN_PHASES.phase_attempt_repair_packet_path(task_path, 0, 1).read_text(encoding="utf-8"))
            self.assertEqual(packet["failure"]["type"], "interrupted_running_attempt")
            self.assertFalse(packet["failure"]["retryable"])

    def test_pending_projection_recovers_valid_attempt_commit(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            handoffs = task_path / "context-pack" / "handoffs"
            runtime.mkdir(parents=True, exist_ok=True)
            handoffs.mkdir(parents=True, exist_ok=True)
            shared_paths = [
                RUN_PHASES.phase_contract_path(task_path, 0),
                RUN_PHASES.phase_checklist_path(task_path, 0),
                RUN_PHASES.phase_quality_path(task_path, 0),
                RUN_PHASES.phase_evidence_path(task_path, 0),
                RUN_PHASES.phase_gate_path(task_path, 0),
                RUN_PHASES.phase_reconciliation_path(task_path, 0),
                RUN_PHASES.phase_reconciliation_summary_path(task_path, 0),
            ]
            for path in shared_paths:
                path.write_text("shared\n", encoding="utf-8")
            handoff = handoffs / "phase0.md"
            handoff.write_text("handoff\n", encoding="utf-8")
            prompt = RUN_PHASES.phase_attempt_prompt_path(task_path, 0, 1)
            stdout = runtime / "phase0-output-attempt1.jsonl"
            stderr = runtime / "phase0-stderr-attempt1.txt"
            ac = RUN_PHASES.ac_results_path(task_path, 0, 1)
            for path in [prompt, stdout, stderr, ac]:
                path.write_text("attempt 1\n", encoding="utf-8")
            result_path = RUN_PHASES.write_phase_result(
                root,
                task_path,
                0,
                1,
                0,
                ["src/demo.py"],
                [{"command": "true", "exit_code": 0}],
                ["context-pack/handoffs/phase0.md"],
                [],
                prompt,
                stdout,
                stderr,
                ac,
            )
            RUN_PHASES.write_phase_attempt_commit(task_path, 0, 1, result_path)
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "pending", "attempts": 0}]}) + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(changes[0]["reason"], "valid_attempt_commit")
            self.assertEqual(task_index["phases"][0]["status"], "completed")
            self.assertEqual(task_index["phases"][0]["attempts"], 1)

    def test_pending_projection_marks_started_attempt_without_terminal_proof_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            RUN_PHASES.append_attempt_manifest_record(
                task_path,
                0,
                1,
                "attempt_started",
                status="running",
                artifacts=[],
            )
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "pending", "attempts": 0}]}) + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            manifest = self.read_attempt_manifest(task_path, 0)
            self.assertEqual(changes[0]["reason"], "interrupted_pending_attempt")
            self.assertEqual(task_index["phases"][0]["status"], "error")
            self.assertEqual(task_index["phases"][0]["attempts"], 1)
            self.assertEqual([item["record_type"] for item in manifest], ["attempt_started", "attempt_interrupted"])
            self.assertTrue(RUN_PHASES.phase_attempt_repair_packet_path(task_path, 0, 1).exists())

    def test_running_projection_rejects_invalid_attempt_manifest_before_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            phase = {"phase": 0, "name": "demo", "status": "running", "attempts": 1}
            packet = RUN_PHASES.build_repair_packet(
                task_path,
                0,
                phase,
                1,
                "acceptance_commands",
                "AC command failed.",
                retryable=True,
            )
            RUN_PHASES.write_repair_packet(task_path, 0, packet, attempt=1)
            with RUN_PHASES.open_append_text(RUN_PHASES.phase_attempt_manifest_path(task_path, 0)) as handle:
                handle.write("{not-json}\n")
            (task_path / "index.json").write_text(
                json.dumps({"phases": [phase]}) + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(changes[0]["reason"], "invalid_attempt_manifest")
            self.assertEqual(task_index["phases"][0]["status"], "error")
            self.assertIn("attempt manifest is invalid", task_index["phases"][0]["error_message"])
            self.assertTrue(RUN_PHASES.phase_repair_packet_path(task_path, 0).exists())

    def test_running_projection_marks_result_without_commit_as_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            handoffs = task_path / "context-pack" / "handoffs"
            runtime.mkdir(parents=True, exist_ok=True)
            handoffs.mkdir(parents=True, exist_ok=True)
            for name, path in {
                "contract": RUN_PHASES.phase_contract_path(task_path, 0),
                "checklist": RUN_PHASES.phase_checklist_path(task_path, 0),
                "quality": RUN_PHASES.phase_quality_path(task_path, 0),
                "handoff": RUN_PHASES.phase_handoff_path(task_path, 0),
                "evidence": RUN_PHASES.phase_evidence_path(task_path, 0),
                "gate": RUN_PHASES.phase_gate_path(task_path, 0),
                "reconciliation": RUN_PHASES.phase_reconciliation_path(task_path, 0),
                "reconciliation_summary": RUN_PHASES.phase_reconciliation_summary_path(task_path, 0),
            }.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{name}\n", encoding="utf-8")
            prompt = RUN_PHASES.phase_attempt_prompt_path(task_path, 0, 1)
            stdout = runtime / "phase0-output-attempt1.jsonl"
            stderr = runtime / "phase0-stderr-attempt1.txt"
            ac = RUN_PHASES.ac_results_path(task_path, 0, 1)
            for path in [prompt, stdout, stderr, ac]:
                path.write_text("attempt 1\n", encoding="utf-8")
            RUN_PHASES.write_phase_result(
                root,
                task_path,
                0,
                1,
                0,
                [],
                [{"command": "true", "exit_code": 0}],
                ["context-pack/handoffs/phase0.md"],
                [],
                prompt,
                stdout,
                stderr,
                ac,
            )
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "running", "attempts": 1}]}) + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            manifest = self.read_attempt_manifest(task_path, 0)
            self.assertEqual(changes[0]["reason"], "interrupted_running_phase")
            self.assertEqual(task_index["phases"][0]["status"], "error")
            self.assertEqual([item["record_type"] for item in manifest], ["attempt_interrupted"])
            self.assertTrue(RUN_PHASES.phase_attempt_repair_packet_path(task_path, 0, 1).exists())
            packet = json.loads(RUN_PHASES.phase_attempt_repair_packet_path(task_path, 0, 1).read_text(encoding="utf-8"))
            self.assertFalse(packet["failure"]["retryable"])

    def test_running_projection_recovers_clean_retryable_failed_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            (task_path / "phases").mkdir(parents=True, exist_ok=True)
            contract = {
                "phase": 0,
                "name": "demo",
                "validation_budget": {"max_attempts": 2, "command_timeout_seconds": 600},
                "required_outputs": [],
                "acceptance_commands": [],
            }
            (task_path / "phases" / "phase0.md").write_text(
                "# Phase 0\n\n## Contract\n```json\n" + json.dumps(contract) + "\n```\n",
                encoding="utf-8",
            )
            phase = {"phase": 0, "name": "demo", "status": "running", "attempts": 1}
            packet = RUN_PHASES.build_repair_packet(
                task_path,
                0,
                phase,
                1,
                "acceptance_commands",
                "AC command failed.",
                retryable=True,
                contract=contract,
                required_outputs=[],
                required_repo_outputs=[],
            )
            RUN_PHASES.write_repair_packet(task_path, 0, packet, attempt=1)
            (task_path / "index.json").write_text(
                json.dumps({"phases": [phase]}) + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(changes[0]["reason"], "retryable_attempt_failed")
            self.assertEqual(task_index["phases"][0]["status"], "pending")
            self.assertEqual(task_index["phases"][0]["attempts"], 1)
            self.assertTrue(RUN_PHASES.phase_repair_packet_path(task_path, 0).exists())

    def test_running_projection_rejects_contaminated_retryable_failed_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            (task_path / "phases").mkdir(parents=True, exist_ok=True)
            contract = {
                "phase": 0,
                "name": "demo",
                "validation_budget": {"max_attempts": 2, "command_timeout_seconds": 600},
                "required_outputs": [],
                "acceptance_commands": [],
            }
            (task_path / "phases" / "phase0.md").write_text(
                "# Phase 0\n\n## Contract\n```json\n" + json.dumps(contract) + "\n```\n",
                encoding="utf-8",
            )
            phase = {"phase": 0, "name": "demo", "status": "running", "attempts": 1}
            packet = RUN_PHASES.build_repair_packet(
                task_path,
                0,
                phase,
                1,
                "acceptance_commands",
                "AC command failed.",
                retryable=True,
                contract=contract,
                required_outputs=[],
                required_repo_outputs=[],
                contaminating_changes=["outside.txt"],
            )
            RUN_PHASES.write_repair_packet(task_path, 0, packet, attempt=1)
            (task_path / "index.json").write_text(
                json.dumps({"phases": [phase]}) + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(changes[0]["reason"], "interrupted_running_phase")
            self.assertEqual(task_index["phases"][0]["status"], "error")
            self.assertEqual(task_index["phases"][0]["attempts"], 1)

    def test_phase_result_records_runner_owned_obligation_assertion_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            static = task_path / "context-pack" / "static"
            handoffs = task_path / "context-pack" / "handoffs"
            runtime.mkdir(parents=True, exist_ok=True)
            static.mkdir(parents=True, exist_ok=True)
            handoffs.mkdir(parents=True, exist_ok=True)
            paths = {
                "contract": RUN_PHASES.phase_contract_path(task_path, 0),
                "checklist": RUN_PHASES.phase_checklist_path(task_path, 0),
                "prompt": runtime / "phase0-prompt.md",
                "stdout": runtime / "phase0-output-attempt1.jsonl",
                "stderr": runtime / "phase0-stderr-attempt1.txt",
                "ac": RUN_PHASES.ac_results_path(task_path, 0, 1),
                "quality": RUN_PHASES.phase_quality_path(task_path, 0),
                "handoff": RUN_PHASES.phase_handoff_path(task_path, 0),
                "evidence": RUN_PHASES.phase_evidence_path(task_path, 0),
                "gate": RUN_PHASES.phase_gate_path(task_path, 0),
                "reconciliation": RUN_PHASES.phase_reconciliation_path(task_path, 0),
                "reconciliation_summary": RUN_PHASES.phase_reconciliation_summary_path(task_path, 0),
            }
            for name, path in paths.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{name}\n", encoding="utf-8")
            paths["contract"].write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "closes_obligations": ["obl.acceptance"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (static / "design-contract.json").write_text(
                json.dumps(
                    {
                        "obligations": [
                            {
                                "id": "obl.acceptance",
                                "class": "acceptance_validity",
                                "trigger": "Acceptance command required.",
                                "closure_condition": "Boundary command emits exact proof line.",
                                "required_command_roles": ["acceptance"],
                                "closure_command_refs": ["unit-tests"],
                                "closure_output_assertions": [
                                    {"type": "exact_line", "value": "BOUNDARY_OK"}
                                ],
                            }
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result_path = RUN_PHASES.write_phase_result(
                root,
                task_path,
                0,
                1,
                0,
                [],
                [
                    {
                        "id": "unit-tests",
                        "role": "acceptance",
                        "command": "python3 -m unittest",
                        "exit_code": 0,
                        "output": "setup\nBOUNDARY_OK\nteardown",
                    }
                ],
                ["context-pack/handoffs/phase0.md"],
                [],
                paths["prompt"],
                paths["stdout"],
                paths["stderr"],
                paths["ac"],
            )

            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["schema_version"], 1)
            self.assertEqual(result["runner_version"], RUN_PHASES.HARNESS_VERSION)
            self.assertNotIn("obligation_closure_assertions", result)
            self.assertEqual(
                result["artifacts"]["obligation_closure"],
                "context-pack/runtime/phase0-obligation-closure-attempt1.json",
            )
            ledger = json.loads(
                (task_path / result["artifacts"]["obligation_closure"]).read_text(encoding="utf-8")
            )
            assertion = ledger["assertions"][0]
            self.assertEqual(ledger["phase"], 0)
            self.assertEqual(ledger["attempt"], 1)
            self.assertEqual(assertion["obligation_id"], "obl.acceptance")
            self.assertEqual(assertion["command_ref"], "unit-tests")
            self.assertEqual(assertion["attempt"], 1)
            self.assertEqual(assertion["runner_version"], RUN_PHASES.HARNESS_VERSION)
            self.assertEqual(
                assertion["phase_contract_sha256"],
                RUN_PHASES.file_sha256(paths["contract"]),
            )
            self.assertEqual(
                assertion["design_contract_sha256"],
                RUN_PHASES.file_sha256(static / "design-contract.json"),
            )
            self.assertIn("command_output_sha256", assertion)
            self.assertTrue(assertion["passed"])
            self.assertNotIn("BOUNDARY_OK", json.dumps(ledger))

    def test_runtime_projection_reconciles_running_phase_with_valid_commit(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            handoffs = task_path / "context-pack" / "handoffs"
            runtime.mkdir(parents=True, exist_ok=True)
            handoffs.mkdir(parents=True, exist_ok=True)
            paths = {
                "contract": RUN_PHASES.phase_contract_path(task_path, 0),
                "checklist": RUN_PHASES.phase_checklist_path(task_path, 0),
                "prompt": runtime / "phase0-prompt.md",
                "stdout": runtime / "phase0-output-attempt1.jsonl",
                "stderr": runtime / "phase0-stderr-attempt1.txt",
                "ac": RUN_PHASES.ac_results_path(task_path, 0, 1),
                "quality": RUN_PHASES.phase_quality_path(task_path, 0),
                "handoff": RUN_PHASES.phase_handoff_path(task_path, 0),
                "evidence": RUN_PHASES.phase_evidence_path(task_path, 0),
                "gate": RUN_PHASES.phase_gate_path(task_path, 0),
                "reconciliation": RUN_PHASES.phase_reconciliation_path(task_path, 0),
                "reconciliation_summary": RUN_PHASES.phase_reconciliation_summary_path(task_path, 0),
            }
            for name, path in paths.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{name}\n", encoding="utf-8")
            result_path = RUN_PHASES.write_phase_result(
                root,
                task_path,
                0,
                1,
                0,
                [],
                [{"command": "true", "exit_code": 0}],
                ["context-pack/handoffs/phase0.md"],
                [],
                paths["prompt"],
                paths["stdout"],
                paths["stderr"],
                paths["ac"],
            )
            RUN_PHASES.write_phase_attempt_commit(task_path, 0, 1, result_path)
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "running", "attempts": 1}]}) + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(changes[0]["reason"], "valid_attempt_commit")
            self.assertEqual(task_index["phases"][0]["status"], "completed")
            self.assertEqual(task_index["phases"][0]["attempts"], 1)
            manifest = self.read_attempt_manifest(task_path, 0)
            self.assertEqual(manifest[-1]["record_type"], "attempt_committed")
            self.assertEqual(manifest[-1]["recovery_action"], "recovered_from_valid_attempt_commit")

    def test_runtime_projection_terminalizes_recovered_commit_and_clears_repair_alias(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            handoffs = task_path / "context-pack" / "handoffs"
            runtime.mkdir(parents=True, exist_ok=True)
            handoffs.mkdir(parents=True, exist_ok=True)
            for name, path in {
                "contract": RUN_PHASES.phase_contract_path(task_path, 0),
                "checklist": RUN_PHASES.phase_checklist_path(task_path, 0),
                "quality": RUN_PHASES.phase_quality_path(task_path, 0),
                "handoff": RUN_PHASES.phase_handoff_path(task_path, 0),
                "evidence": RUN_PHASES.phase_evidence_path(task_path, 0),
                "gate": RUN_PHASES.phase_gate_path(task_path, 0),
                "reconciliation": RUN_PHASES.phase_reconciliation_path(task_path, 0),
                "reconciliation_summary": RUN_PHASES.phase_reconciliation_summary_path(task_path, 0),
            }.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{name}\n", encoding="utf-8")
            packet = RUN_PHASES.build_repair_packet(
                task_path,
                0,
                {"phase": 0, "name": "demo"},
                1,
                "acceptance_commands",
                "Attempt one failed.",
                retryable=True,
            )
            RUN_PHASES.write_repair_packet(task_path, 0, packet, attempt=1)
            RUN_PHASES.append_attempt_manifest_record(task_path, 0, 2, "attempt_started", status="running", artifacts=[])
            prompt = RUN_PHASES.phase_attempt_prompt_path(task_path, 0, 2)
            stdout = runtime / "phase0-output-attempt2.jsonl"
            stderr = runtime / "phase0-stderr-attempt2.txt"
            ac = RUN_PHASES.ac_results_path(task_path, 0, 2)
            for path in [prompt, stdout, stderr, ac]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("attempt 2\n", encoding="utf-8")
            result_path = RUN_PHASES.write_phase_result(
                root,
                task_path,
                0,
                2,
                0,
                [],
                [{"command": "true", "exit_code": 0}],
                ["context-pack/handoffs/phase0.md"],
                [],
                prompt,
                stdout,
                stderr,
                ac,
            )
            RUN_PHASES.write_phase_attempt_commit(task_path, 0, 2, result_path)
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "running", "attempts": 2}]}) + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            manifest = self.read_attempt_manifest(task_path, 0)
            self.assertEqual(changes[0]["reason"], "valid_attempt_commit")
            self.assertEqual(task_index["phases"][0]["status"], "completed")
            self.assertEqual([item["record_type"] for item in manifest], ["attempt_failed", "attempt_started", "attempt_committed"])
            self.assertFalse(RUN_PHASES.phase_repair_packet_path(task_path, 0).exists())
            self.assertFalse(RUN_PHASES.phase_repair_packet_summary_path(task_path, 0).exists())

    def test_runtime_projection_recovered_commit_terminalization_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            handoffs = task_path / "context-pack" / "handoffs"
            runtime.mkdir(parents=True, exist_ok=True)
            handoffs.mkdir(parents=True, exist_ok=True)
            for name, path in {
                "contract": RUN_PHASES.phase_contract_path(task_path, 0),
                "checklist": RUN_PHASES.phase_checklist_path(task_path, 0),
                "quality": RUN_PHASES.phase_quality_path(task_path, 0),
                "handoff": RUN_PHASES.phase_handoff_path(task_path, 0),
                "evidence": RUN_PHASES.phase_evidence_path(task_path, 0),
                "gate": RUN_PHASES.phase_gate_path(task_path, 0),
                "reconciliation": RUN_PHASES.phase_reconciliation_path(task_path, 0),
                "reconciliation_summary": RUN_PHASES.phase_reconciliation_summary_path(task_path, 0),
            }.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{name}\n", encoding="utf-8")
            prompt = RUN_PHASES.phase_attempt_prompt_path(task_path, 0, 1)
            stdout = runtime / "phase0-output-attempt1.jsonl"
            stderr = runtime / "phase0-stderr-attempt1.txt"
            ac = RUN_PHASES.ac_results_path(task_path, 0, 1)
            for path in [prompt, stdout, stderr, ac]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("attempt 1\n", encoding="utf-8")
            result_path = RUN_PHASES.write_phase_result(
                root,
                task_path,
                0,
                1,
                0,
                [],
                [{"command": "true", "exit_code": 0}],
                ["context-pack/handoffs/phase0.md"],
                [],
                prompt,
                stdout,
                stderr,
                ac,
            )
            commit_path = RUN_PHASES.write_phase_attempt_commit(task_path, 0, 1, result_path)
            RUN_PHASES.append_attempt_manifest_record(
                task_path,
                0,
                1,
                "attempt_committed",
                status="committed",
                result=RUN_PHASES.artifact_ref(task_path, "result", result_path),
                attempt_commit=RUN_PHASES.artifact_ref(task_path, "attempt_commit", commit_path),
            )
            packet = RUN_PHASES.build_repair_packet(
                task_path,
                0,
                {"phase": 0, "name": "demo"},
                1,
                "acceptance_commands",
                "stale alias",
                retryable=True,
            )
            RUN_PHASES.write_json(RUN_PHASES.phase_repair_packet_path(task_path, 0), packet)
            RUN_PHASES.phase_repair_packet_summary_path(task_path, 0).write_text(
                RUN_PHASES.repair_packet_markdown(packet),
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "running", "attempts": 1}]}) + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            manifest = self.read_attempt_manifest(task_path, 0)
            self.assertEqual(changes[0]["reason"], "valid_attempt_commit")
            self.assertEqual([item["record_type"] for item in manifest], ["attempt_committed"])
            self.assertFalse(RUN_PHASES.phase_repair_packet_path(task_path, 0).exists())
            self.assertFalse(RUN_PHASES.phase_repair_packet_summary_path(task_path, 0).exists())

    def test_runtime_projection_rejects_valid_commit_with_conflicting_terminal_record(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            handoffs = task_path / "context-pack" / "handoffs"
            runtime.mkdir(parents=True, exist_ok=True)
            handoffs.mkdir(parents=True, exist_ok=True)
            for name, path in {
                "contract": RUN_PHASES.phase_contract_path(task_path, 0),
                "checklist": RUN_PHASES.phase_checklist_path(task_path, 0),
                "quality": RUN_PHASES.phase_quality_path(task_path, 0),
                "handoff": RUN_PHASES.phase_handoff_path(task_path, 0),
                "evidence": RUN_PHASES.phase_evidence_path(task_path, 0),
                "gate": RUN_PHASES.phase_gate_path(task_path, 0),
                "reconciliation": RUN_PHASES.phase_reconciliation_path(task_path, 0),
                "reconciliation_summary": RUN_PHASES.phase_reconciliation_summary_path(task_path, 0),
            }.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{name}\n", encoding="utf-8")
            prompt = RUN_PHASES.phase_attempt_prompt_path(task_path, 0, 1)
            stdout = runtime / "phase0-output-attempt1.jsonl"
            stderr = runtime / "phase0-stderr-attempt1.txt"
            ac = RUN_PHASES.ac_results_path(task_path, 0, 1)
            for path in [prompt, stdout, stderr, ac]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("attempt 1\n", encoding="utf-8")
            result_path = RUN_PHASES.write_phase_result(
                root,
                task_path,
                0,
                1,
                0,
                [],
                [{"command": "true", "exit_code": 0}],
                ["context-pack/handoffs/phase0.md"],
                [],
                prompt,
                stdout,
                stderr,
                ac,
            )
            RUN_PHASES.write_phase_attempt_commit(task_path, 0, 1, result_path)
            packet = RUN_PHASES.build_repair_packet(
                task_path,
                0,
                {"phase": 0, "name": "demo"},
                1,
                "gate",
                "Conflicting failure.",
                retryable=False,
            )
            RUN_PHASES.write_repair_packet(task_path, 0, packet, attempt=1)
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "running", "attempts": 1}]}) + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            manifest = self.read_attempt_manifest(task_path, 0)
            self.assertEqual(changes[0]["reason"], "conflicting_attempt_terminal_record")
            self.assertEqual(task_index["phases"][0]["status"], "error")
            self.assertIn("conflicts", task_index["phases"][0]["error_message"])
            self.assertEqual([item["record_type"] for item in manifest], ["attempt_failed"])

    def test_runtime_projection_rejects_duplicate_terminal_manifest_before_commit_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            handoffs = task_path / "context-pack" / "handoffs"
            runtime.mkdir(parents=True, exist_ok=True)
            handoffs.mkdir(parents=True, exist_ok=True)
            for name, path in {
                "contract": RUN_PHASES.phase_contract_path(task_path, 0),
                "checklist": RUN_PHASES.phase_checklist_path(task_path, 0),
                "quality": RUN_PHASES.phase_quality_path(task_path, 0),
                "handoff": RUN_PHASES.phase_handoff_path(task_path, 0),
                "evidence": RUN_PHASES.phase_evidence_path(task_path, 0),
                "gate": RUN_PHASES.phase_gate_path(task_path, 0),
                "reconciliation": RUN_PHASES.phase_reconciliation_path(task_path, 0),
                "reconciliation_summary": RUN_PHASES.phase_reconciliation_summary_path(task_path, 0),
            }.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{name}\n", encoding="utf-8")
            prompt = RUN_PHASES.phase_attempt_prompt_path(task_path, 0, 1)
            stdout = runtime / "phase0-output-attempt1.jsonl"
            stderr = runtime / "phase0-stderr-attempt1.txt"
            ac = RUN_PHASES.ac_results_path(task_path, 0, 1)
            for path in [prompt, stdout, stderr, ac]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("attempt 1\n", encoding="utf-8")
            result_path = RUN_PHASES.write_phase_result(
                root,
                task_path,
                0,
                1,
                0,
                [],
                [{"command": "true", "exit_code": 0}],
                ["context-pack/handoffs/phase0.md"],
                [],
                prompt,
                stdout,
                stderr,
                ac,
            )
            commit_path = RUN_PHASES.write_phase_attempt_commit(task_path, 0, 1, result_path)
            packet = RUN_PHASES.build_repair_packet(
                task_path,
                0,
                {"phase": 0, "name": "demo"},
                1,
                "gate",
                "Failed terminal.",
                retryable=False,
            )
            RUN_PHASES.write_repair_packet(task_path, 0, packet, attempt=1)
            RUN_PHASES.append_attempt_manifest_record(
                task_path,
                0,
                1,
                "attempt_committed",
                status="committed",
                result=RUN_PHASES.artifact_ref(task_path, "result", result_path),
                attempt_commit=RUN_PHASES.artifact_ref(task_path, "attempt_commit", commit_path),
            )
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "running", "attempts": 1}]}) + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(changes[0]["reason"], "invalid_attempt_manifest")
            self.assertEqual(task_index["phases"][0]["status"], "error")
            self.assertIn("multiple terminal manifest records", task_index["phases"][0]["error_message"])
            self.assertTrue(RUN_PHASES.phase_repair_packet_path(task_path, 0).exists())

    def test_runtime_projection_rejects_commit_with_tampered_artifact_hash(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            handoffs = task_path / "context-pack" / "handoffs"
            runtime.mkdir(parents=True, exist_ok=True)
            handoffs.mkdir(parents=True, exist_ok=True)
            paths = {
                "contract": RUN_PHASES.phase_attempt_contract_path(task_path, 0, 1),
                "checklist": RUN_PHASES.phase_attempt_checklist_path(task_path, 0, 1),
                "prompt": RUN_PHASES.phase_attempt_prompt_path(task_path, 0, 1),
                "stdout": runtime / "phase0-output-attempt1.jsonl",
                "stderr": runtime / "phase0-stderr-attempt1.txt",
                "ac": RUN_PHASES.ac_results_path(task_path, 0, 1),
                "quality": RUN_PHASES.phase_quality_path(task_path, 0),
                "handoff": RUN_PHASES.phase_handoff_path(task_path, 0),
                "evidence": RUN_PHASES.phase_evidence_path(task_path, 0),
                "gate": RUN_PHASES.phase_gate_path(task_path, 0),
                "reconciliation": RUN_PHASES.phase_reconciliation_path(task_path, 0),
                "reconciliation_summary": RUN_PHASES.phase_reconciliation_summary_path(task_path, 0),
            }
            for name, path in paths.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{name}\n", encoding="utf-8")
            result_path = RUN_PHASES.write_phase_result(
                root,
                task_path,
                0,
                1,
                0,
                [],
                [{"command": "true", "exit_code": 0}],
                ["context-pack/handoffs/phase0.md"],
                [],
                paths["prompt"],
                paths["stdout"],
                paths["stderr"],
                paths["ac"],
                contract_path=paths["contract"],
                checklist_path=paths["checklist"],
            )
            RUN_PHASES.write_phase_attempt_commit(task_path, 0, 1, result_path)
            paths["prompt"].write_text("tampered\n", encoding="utf-8")
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "running", "attempts": 1}]}) + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(changes[0]["reason"], "interrupted_running_phase")
            self.assertEqual(task_index["phases"][0]["status"], "error")

    def test_runtime_projection_ignores_attempt_commit_before_reset_marker(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            handoffs = task_path / "context-pack" / "handoffs"
            runtime.mkdir(parents=True, exist_ok=True)
            handoffs.mkdir(parents=True, exist_ok=True)
            paths = {
                "contract": RUN_PHASES.phase_contract_path(task_path, 0),
                "checklist": RUN_PHASES.phase_checklist_path(task_path, 0),
                "prompt": runtime / "phase0-prompt.md",
                "stdout": runtime / "phase0-output-attempt1.jsonl",
                "stderr": runtime / "phase0-stderr-attempt1.txt",
                "ac": RUN_PHASES.ac_results_path(task_path, 0, 1),
                "quality": RUN_PHASES.phase_quality_path(task_path, 0),
                "handoff": RUN_PHASES.phase_handoff_path(task_path, 0),
                "evidence": RUN_PHASES.phase_evidence_path(task_path, 0),
                "gate": RUN_PHASES.phase_gate_path(task_path, 0),
                "reconciliation": RUN_PHASES.phase_reconciliation_path(task_path, 0),
                "reconciliation_summary": RUN_PHASES.phase_reconciliation_summary_path(task_path, 0),
            }
            for name, path in paths.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{name}\n", encoding="utf-8")
            result_path = RUN_PHASES.write_phase_result(
                root,
                task_path,
                0,
                1,
                0,
                [],
                [{"command": "true", "exit_code": 0}],
                ["context-pack/handoffs/phase0.md"],
                [],
                paths["prompt"],
                paths["stdout"],
                paths["stderr"],
                paths["ac"],
            )
            RUN_PHASES.write_phase_attempt_commit(task_path, 0, 1, result_path)
            RUN_PHASES.write_phase_reset_marker(task_path, 0, "9999-01-01T00:00:00+00:00", 0)
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "phases": [
                            {
                                "phase": 0,
                                "name": "demo",
                                "status": "pending",
                                "attempts": 0,
                                "reset_at": "9999-01-01T00:00:00+00:00",
                            }
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(changes, [])
            self.assertEqual(task_index["phases"][0]["status"], "pending")
            self.assertEqual(RUN_PHASES.latest_valid_phase_attempt_commit(task_path, 0), None)

    def test_runtime_projection_ignores_legacy_commit_at_same_second_as_reset(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            result_path = RUN_PHASES.phase_result_path(task_path, 0)
            result = {"phase": 0, "attempt": 1, "status": "completed", "artifacts": {}}
            result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
            reset_at = "2026-01-01T00:00:00+09:00"
            RUN_PHASES.phase_attempt_commit_path(task_path, 0, 1).write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "committed_at": reset_at,
                        "result": {
                            "path": "context-pack/runtime/phase0-result.json",
                            "sha256": RUN_PHASES.file_sha256(result_path),
                        },
                        "artifacts": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            RUN_PHASES.phase_reset_marker_path(task_path, 0).write_text(
                json.dumps({"schema_version": 1, "phase": 0, "reset_at": reset_at}) + "\n",
                encoding="utf-8",
            )

            self.assertIsNone(RUN_PHASES.latest_valid_phase_attempt_commit(task_path, 0))

    def test_runtime_projection_uses_reset_generation_over_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            reset_at = "2026-01-01T00:00:00+09:00"
            RUN_PHASES.write_phase_reset_marker(task_path, 0, reset_at, 0)
            result_path = RUN_PHASES.phase_result_path(task_path, 0)
            result = {
                "schema_version": 1,
                "runner_version": RUN_PHASES.HARNESS_VERSION,
                "phase": 0,
                "attempt": 1,
                "status": "completed",
                "reset_generation": 1,
                "codex_exit_code": 0,
                "tests_passed": True,
                "policy_pack": RUN_PHASES.runtime_policy_pack(),
                "harness_attestation": RUN_PHASES.RUNTIME_HARNESS_ATTESTATION,
                "artifacts": {},
            }
            result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
            RUN_PHASES.phase_attempt_commit_path(task_path, 0, 1).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "runner_version": RUN_PHASES.HARNESS_VERSION,
                        "commit_scope": "runtime_attempt_bundle",
                        "phase": 0,
                        "attempt": 1,
                        "reset_generation": 1,
                        "status": "committed",
                        "policy_pack": RUN_PHASES.runtime_policy_pack(),
                        "harness_attestation": RUN_PHASES.RUNTIME_HARNESS_ATTESTATION,
                        "committed_at": reset_at,
                        "result": {
                            "path": "context-pack/runtime/phase0-result.json",
                            "sha256": RUN_PHASES.file_sha256(result_path),
                        },
                        "artifacts": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            commit = RUN_PHASES.latest_valid_phase_attempt_commit(task_path, 0)

            self.assertIsNotNone(commit)
            self.assertEqual(commit["reset_generation"], 1)

    def test_runtime_projection_rejects_commit_from_previous_reset_generation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            RUN_PHASES.write_phase_reset_marker(task_path, 0, "2026-01-01T00:00:00+09:00", 0)
            RUN_PHASES.write_phase_reset_marker(task_path, 0, "2026-01-01T00:00:01+09:00", 0)
            result_path = RUN_PHASES.phase_result_path(task_path, 0)
            result = {"phase": 0, "attempt": 1, "status": "completed", "reset_generation": 1, "artifacts": {}}
            result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
            RUN_PHASES.phase_attempt_commit_path(task_path, 0, 1).write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "reset_generation": 1,
                        "committed_at": "2026-01-01T00:00:02+09:00",
                        "result": {
                            "path": "context-pack/runtime/phase0-result.json",
                            "sha256": RUN_PHASES.file_sha256(result_path),
                        },
                        "artifacts": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertIsNone(RUN_PHASES.latest_valid_phase_attempt_commit(task_path, 0))

    def test_runtime_projection_rejects_legacy_commit_when_generation_marker_exists(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            reset_at = "2026-01-01T00:00:00+09:00"
            RUN_PHASES.write_phase_reset_marker(task_path, 0, reset_at, 0)
            result_path = RUN_PHASES.phase_result_path(task_path, 0)
            result = {"phase": 0, "attempt": 1, "status": "completed", "artifacts": {}}
            result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
            RUN_PHASES.phase_attempt_commit_path(task_path, 0, 1).write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "committed_at": "9999-01-01T00:00:00+09:00",
                        "result": {
                            "path": "context-pack/runtime/phase0-result.json",
                            "sha256": RUN_PHASES.file_sha256(result_path),
                        },
                        "artifacts": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertIsNone(RUN_PHASES.latest_valid_phase_attempt_commit(task_path, 0))

    def test_runtime_projection_rejects_generated_commit_after_partial_propagated_reset_marker(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            RUN_PHASES.write_phase_reset_marker(task_path, 1, "2026-01-01T00:00:00+09:00", 1)
            result_path = RUN_PHASES.phase_result_path(task_path, 1)
            result = {"phase": 1, "attempt": 1, "status": "completed", "reset_generation": 1, "artifacts": {}}
            result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
            RUN_PHASES.phase_attempt_commit_path(task_path, 1, 1).write_text(
                json.dumps(
                    {
                        "phase": 1,
                        "attempt": 1,
                        "reset_generation": 1,
                        "committed_at": "9999-01-01T00:00:00+09:00",
                        "result": {
                            "path": "context-pack/runtime/phase1-result.json",
                            "sha256": RUN_PHASES.file_sha256(result_path),
                        },
                        "artifacts": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            propagated_reset_at = "2026-01-01T00:00:01+09:00"
            RUN_PHASES.write_phase_reset_marker(task_path, 0, propagated_reset_at, 0)
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "phases": [
                            {"phase": 0, "name": "docs", "status": "pending", "attempts": 0},
                            {"phase": 1, "name": "api", "status": "completed", "attempts": 1},
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertIsNone(RUN_PHASES.latest_valid_phase_attempt_commit(task_path, 1))
            self.assertEqual(changes[0]["reason"], "reset_marker_without_projection")
            self.assertEqual(task_index["phases"][1]["status"], "pending")
            self.assertEqual(task_index["phases"][1]["reset_at"], propagated_reset_at)

    def test_runtime_projection_rejects_legacy_future_commit_after_partial_propagated_reset_marker(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            result_path = RUN_PHASES.phase_result_path(task_path, 1)
            result = {"phase": 1, "attempt": 1, "status": "completed", "artifacts": {}}
            result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
            RUN_PHASES.phase_attempt_commit_path(task_path, 1, 1).write_text(
                json.dumps(
                    {
                        "phase": 1,
                        "attempt": 1,
                        "committed_at": "9999-01-01T00:00:00+09:00",
                        "result": {
                            "path": "context-pack/runtime/phase1-result.json",
                            "sha256": RUN_PHASES.file_sha256(result_path),
                        },
                        "artifacts": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            propagated_reset_at = "2026-01-01T00:00:01+09:00"
            RUN_PHASES.write_phase_reset_marker(task_path, 0, propagated_reset_at, 0)
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "phases": [
                            {"phase": 0, "name": "docs", "status": "pending", "attempts": 0},
                            {"phase": 1, "name": "api", "status": "completed", "attempts": 1},
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertIsNone(RUN_PHASES.latest_valid_phase_attempt_commit(task_path, 1))
            self.assertEqual(changes[0]["reason"], "reset_marker_without_projection")
            self.assertEqual(task_index["phases"][1]["status"], "pending")

    def test_runtime_projection_rejects_commit_result_reset_generation_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            RUN_PHASES.write_phase_reset_marker(task_path, 0, "2026-01-01T00:00:00+09:00", 0)
            result_path = RUN_PHASES.phase_result_path(task_path, 0)
            result = {"phase": 0, "attempt": 1, "status": "completed", "reset_generation": 1, "artifacts": {}}
            result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
            RUN_PHASES.phase_attempt_commit_path(task_path, 0, 1).write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "reset_generation": 2,
                        "committed_at": "2026-01-01T00:00:01+09:00",
                        "result": {
                            "path": "context-pack/runtime/phase0-result.json",
                            "sha256": RUN_PHASES.file_sha256(result_path),
                        },
                        "artifacts": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertIsNone(RUN_PHASES.latest_valid_phase_attempt_commit(task_path, 0))

    def test_runtime_projection_rejects_commit_result_attempt_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            result_path = RUN_PHASES.phase_result_path(task_path, 0)
            result = {"phase": 0, "attempt": 2, "status": "completed", "artifacts": {}}
            result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
            RUN_PHASES.phase_attempt_commit_path(task_path, 0, 1).write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "result": {
                            "path": "context-pack/runtime/phase0-result.json",
                            "sha256": RUN_PHASES.file_sha256(result_path),
                        },
                        "artifacts": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertIsNone(RUN_PHASES.latest_valid_phase_attempt_commit(task_path, 0))

    def test_runtime_projection_rejects_attempt_commit_paths_escaping_task(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            escaped = root / "outside-proof.json"
            escaped.write_text("outside\n", encoding="utf-8")
            RUN_PHASES.phase_attempt_commit_path(task_path, 0, 1).write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "result": {
                            "path": "../../outside-proof.json",
                            "sha256": RUN_PHASES.file_sha256(escaped),
                        },
                        "artifacts": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertIsNone(RUN_PHASES.latest_valid_phase_attempt_commit(task_path, 0))

    def test_phase_reset_writes_marker_to_invalidate_previous_attempt_commit(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            (root / "tasks").mkdir(parents=True, exist_ok=True)
            (root / "tasks" / "index.json").write_text(
                json.dumps({"tasks": [{"dir": "demo", "status": "completed"}]}) + "\n",
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "completed", "attempts": 1}]}) + "\n",
                encoding="utf-8",
            )
            RUN_PHASES.phase_baseline_path(task_path, 0).write_text('{"schema_version":1}\n', encoding="utf-8")

            RUN_PHASES.apply_phase_reset(root, task_path, from_phase=0, dry_run=False)

            marker = json.loads(RUN_PHASES.phase_reset_marker_path(task_path, 0).read_text(encoding="utf-8"))
            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(marker["phase"], 0)
            self.assertEqual(marker["from_phase"], 0)
            self.assertEqual(marker["reset_generation"], 1)
            self.assertEqual(marker["reset_id"], "phase0-reset1")
            self.assertEqual(task_index["phases"][0]["status"], "pending")
            self.assertEqual(task_index["phases"][0]["reset_at"], marker["reset_at"])
            self.assertFalse(RUN_PHASES.phase_baseline_path(task_path, 0).exists())

    def test_update_top_index_uses_global_index_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, _task_path = self.make_task(Path(raw_tmp))
            (root / "tasks" / "index.json").write_text(
                json.dumps({"tasks": [{"dir": "demo", "status": "pending"}]}) + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                RUN_PHASES,
                "acquire_lock",
                side_effect=RuntimeError("Another codex-harness process is active"),
            ) as acquire_lock:
                with self.assertRaisesRegex(RuntimeError, "Another codex-harness process is active"):
                    RUN_PHASES.update_top_index(root, "demo", "completed")

            acquire_lock.assert_called_once_with(
                RUN_PHASES.top_index_lock_path(root),
                wait_timeout_seconds=30,
                boundary=root,
            )

            top_index = json.loads((root / "tasks" / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(top_index["tasks"][0]["status"], "pending")

    def test_repo_execution_lock_blocks_concurrent_phase_execution(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            lock_path = RUN_PHASES.repo_execution_lock_path(root)
            held = file_lock.acquire_lock(lock_path, boundary=root)
            args = argparse.Namespace(dry_run=False, repo_lock_timeout=0)
            try:
                with self.assertRaisesRegex(RuntimeError, "repo execution is active"):
                    RUN_PHASES.acquire_repo_execution_lock(root, task_path, args)
            finally:
                file_lock.release_lock(held)

            self.assertFalse(lock_path.exists())

    def test_main_releases_task_lock_when_repo_execution_lock_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            held = file_lock.acquire_lock(RUN_PHASES.repo_execution_lock_path(root), boundary=root)
            try:
                with (
                    mock.patch.object(sys, "argv", ["run-phases.py", "demo", "--root", str(root)]),
                    mock.patch.object(RUN_PHASES, "harness_install_errors", return_value=[]),
                    mock.patch.object(RUN_PHASES, "execute_phase") as execute_phase,
                ):
                    self.assertEqual(RUN_PHASES.main(), 1)
                    execute_phase.assert_not_called()
            finally:
                file_lock.release_lock(held)

            self.assertFalse(RUN_PHASES.runner_lock_path(task_path).exists())

    def test_parallel_top_index_updates_preserve_unrelated_entries(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, _task_path = self.make_task(Path(raw_tmp))
            (root / "tasks" / "index.json").write_text(
                json.dumps(
                    {
                        "tasks": [
                            {"dir": "api", "status": "pending"},
                            {"dir": "web", "status": "pending"},
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            threads = [
                threading.Thread(target=RUN_PHASES.update_top_index, args=(root, "api", "completed")),
                threading.Thread(target=RUN_PHASES.update_top_index, args=(root, "web", "error")),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            top_index = json.loads((root / "tasks" / "index.json").read_text(encoding="utf-8"))
            by_dir = {task["dir"]: task for task in top_index["tasks"]}
            self.assertEqual(by_dir["api"]["status"], "completed")
            self.assertIn("completed_at", by_dir["api"])
            self.assertEqual(by_dir["web"]["status"], "error")
            self.assertIn("failed_at", by_dir["web"])

    def test_runtime_projection_marks_completed_phase_without_commit_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            (root / "tasks").mkdir(parents=True, exist_ok=True)
            (root / "tasks" / "index.json").write_text(
                json.dumps({"tasks": [{"dir": "demo", "status": "running"}]}) + "\n",
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "completed", "attempts": 1}]}) + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(changes[0]["reason"], "missing_attempt_commit")
            self.assertEqual(task_index["phases"][0]["status"], "error")
            self.assertIn("attempt commit", task_index["phases"][0]["error_message"])

    def test_runtime_projection_marks_completed_phase_with_stale_attempt_commit_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            result_path = RUN_PHASES.phase_attempt_result_path(task_path, 0, 1)
            result = {"phase": 0, "attempt": 1, "status": "completed", "artifacts": {}}
            result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
            RUN_PHASES.phase_attempt_commit_path(task_path, 0, 1).write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "result": {
                            "path": "context-pack/runtime/phase0-result-attempt1.json",
                            "sha256": RUN_PHASES.file_sha256(result_path),
                        },
                        "artifacts": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "completed", "attempts": 2}]}) + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(changes[0]["reason"], "stale_attempt_commit")
            self.assertEqual(task_index["phases"][0]["status"], "error")

    def test_reconcile_before_execution_repairs_stale_running_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "completed", "attempts": 1}]}) + "\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(dry_run=False, from_phase=None, resume_repair=False)

            changes = RUN_PHASES.reconcile_before_execution(root, task_path, args)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            progress = (task_path / "context-pack" / "runtime" / "progress.md").read_text(encoding="utf-8")
            self.assertEqual(changes[0]["reason"], "missing_attempt_commit")
            self.assertEqual(task_index["phases"][0]["status"], "error")
            self.assertIn("runtime projection reconciled before execution", progress)

    def test_collect_files_rejects_symlink_context_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root = tmp / "repo"
            root.mkdir()
            outside = tmp / "secret.md"
            outside.write_text("SECRET\n", encoding="utf-8")
            context = root / "tasks" / "demo" / "context-pack" / "static" / "original-prompt.md"
            context.parent.mkdir(parents=True)
            context.symlink_to(outside)

            with self.assertRaisesRegex(RuntimeError, "Unsafe context file symlink") as raised:
                RUN_PHASES.collect_files(root, [context], 10_000)

            self.assertNotIn("SECRET", str(raised.exception))

    def test_main_fails_closed_after_interrupted_running_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            (root / "tasks").mkdir(parents=True, exist_ok=True)
            (root / "tasks" / "index.json").write_text(
                json.dumps({"tasks": [{"dir": "demo", "status": "running"}]}) + "\n",
                encoding="utf-8",
            )
            RUN_PHASES.append_attempt_manifest_record(
                task_path,
                0,
                1,
                "attempt_started",
                status="running",
                artifacts=[],
            )
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "running", "attempts": 1}]}) + "\n",
                encoding="utf-8",
            )

            with (
                mock.patch.object(sys, "argv", ["run-phases.py", "demo", "--root", str(root)]),
                mock.patch.object(RUN_PHASES, "harness_install_errors", return_value=[]),
                mock.patch.object(RUN_PHASES, "verify_task", side_effect=AssertionError("verify should not run")),
                mock.patch.object(RUN_PHASES, "run_codex", side_effect=AssertionError("started attempt N+1")) as run_codex,
            ):
                self.assertEqual(RUN_PHASES.main(), 1)

            run_codex.assert_not_called()
            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            top_index = json.loads((root / "tasks" / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(task_index["phases"][0]["status"], "error")
            self.assertEqual(top_index["tasks"][0]["status"], "error")

    def test_main_fails_closed_after_interrupted_pending_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            (root / "tasks").mkdir(parents=True, exist_ok=True)
            (root / "tasks" / "index.json").write_text(
                json.dumps({"tasks": [{"dir": "demo", "status": "running"}]}) + "\n",
                encoding="utf-8",
            )
            RUN_PHASES.append_attempt_manifest_record(
                task_path,
                0,
                1,
                "attempt_started",
                status="running",
                artifacts=[],
            )
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "pending", "attempts": 0}]}) + "\n",
                encoding="utf-8",
            )

            with (
                mock.patch.object(sys, "argv", ["run-phases.py", "demo", "--root", str(root)]),
                mock.patch.object(RUN_PHASES, "harness_install_errors", return_value=[]),
                mock.patch.object(RUN_PHASES, "verify_task", side_effect=AssertionError("verify should not run")),
                mock.patch.object(RUN_PHASES, "run_codex", side_effect=AssertionError("reused pending attempt")) as run_codex,
            ):
                self.assertEqual(RUN_PHASES.main(), 1)

            run_codex.assert_not_called()
            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            top_index = json.loads((root / "tasks" / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(task_index["phases"][0]["status"], "error")
            self.assertEqual(task_index["phases"][0]["attempts"], 1)
            self.assertEqual(top_index["tasks"][0]["status"], "error")

    def static_content(self, filename: str) -> str:
        values = {
            "decisions.json": {"decisions": [{"id": "D-001", "status": "approved", "summary": "Approved."}]},
            "open-decisions.json": {"decisions": []},
            "architecture.json": {
                "nodes": [{"id": "A-001", "name": "docs", "responsibility": "docs"}],
                "allowed_edges": [],
                "decisions": [{"id": "A-001", "summary": "Approved architecture."}],
                "forbid_cycles": True,
            },
            "dependency-policy.json": {
                "new_dependencies": "forbidden",
                "approved_new_dependencies": [],
                "approved_dependency_manifest_changes": [],
            },
            "context-gathering-budget.json": {
                "search_batches": 1,
                "max_files_to_read": 1,
                "stop_when": ["target files are known"],
                "escalate_when": ["scope boundary is unclear"],
            },
        }
        if filename in values:
            return json.dumps(values[filename]) + "\n"
        return "content\n"

    def make_fake_codex(self, tmp: Path, body: str) -> Path:
        path = tmp / "fake-codex.py"
        path.write_text(
            "#!/usr/bin/env python3\n"
            "from __future__ import annotations\n"
            "import sys\n"
            "import time\n"
            + body,
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | 0o111)
        return path

    def make_task(self, tmp: Path) -> tuple[Path, Path]:
        root = tmp / "repo"
        task_path = root / "tasks" / "demo"
        (task_path / "context-pack" / "runtime").mkdir(parents=True)
        return root, task_path

    def read_attempt_manifest(self, task_path: Path, phase: int) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in RUN_PHASES.phase_attempt_manifest_path(task_path, phase).read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]

    def write_contract(self, root: Path, task_path: Path, allowed_paths: list[str]) -> None:
        contract_path = task_path / "context-pack" / "runtime" / "phase1-contract.json"
        contract_path.write_text(
            (
                '{"phase":1,"scope":{"allowed_paths":'
                + repr(allowed_paths).replace("'", '"')
                + '}}\n'
            ),
            encoding="utf-8",
        )

    def test_codex_output_symlink_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            outside = tmp / "outside-output.jsonl"
            outside.write_text("outside\n", encoding="utf-8")
            output_path = task_path / "context-pack" / "runtime" / "phase1-output-attempt1.jsonl"
            output_path.symlink_to(outside)
            stderr_path = task_path / "context-pack" / "runtime" / "phase1-stderr-attempt1.txt"
            fake = self.make_fake_codex(tmp, "raise SystemExit(0)\n")

            with self.assertRaisesRegex(RuntimeError, "symlink"):
                RUN_PHASES.run_codex(
                    root,
                    task_path,
                    1,
                    "prompt",
                    output_path,
                    stderr_path,
                    str(fake),
                    False,
                    False,
                    10,
                )

            self.assertEqual(outside.read_text(encoding="utf-8"), "outside\n")

    def test_codex_output_streams_before_process_exits(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    assert "--output-schema" in sys.argv, sys.argv
                    assert sys.argv[sys.argv.index("--output-schema") + 1].endswith("phase-final.schema.json")
                    sys.stdin.read()
                    print('{"event":"first"}', flush=True)
                    time.sleep(1.5)
                    print('{"event":"second"}', flush=True)
                    raise SystemExit(0)
                    """
                ),
            )
            output_path = task_path / "context-pack" / "runtime" / "phase1-output-attempt1.jsonl"
            stderr_path = task_path / "context-pack" / "runtime" / "phase1-stderr-attempt1.txt"
            result: dict[str, int] = {}

            thread = threading.Thread(
                target=lambda: result.setdefault(
                    "returncode",
                    RUN_PHASES.run_codex(
                        root,
                        task_path,
                        1,
                        "prompt",
                        output_path,
                        stderr_path,
                        str(fake),
                        False,
                        False,
                        10,
                    ),
                )
            )
            thread.start()

            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                if output_path.exists() and '{"event":"first"}' in output_path.read_text(encoding="utf-8"):
                    break
                time.sleep(0.05)
            self.assertTrue(output_path.exists())
            self.assertIn('{"event":"first"}', output_path.read_text(encoding="utf-8"))
            self.assertTrue(thread.is_alive())

            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result["returncode"], 0)
            self.assertIn('{"event":"second"}', output_path.read_text(encoding="utf-8"))

    def test_codex_idle_timeout_kills_silent_process(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    sys.stdin.read()
                    time.sleep(5)
                    raise SystemExit(0)
                    """
                ),
            )
            output_path = task_path / "context-pack" / "runtime" / "phase1-output-attempt1.jsonl"
            stderr_path = task_path / "context-pack" / "runtime" / "phase1-stderr-attempt1.txt"

            returncode = RUN_PHASES.run_codex(
                root,
                task_path,
                1,
                "prompt",
                output_path,
                stderr_path,
                str(fake),
                False,
                False,
                1,
            )

            self.assertEqual(returncode, RUN_PHASES.CODEX_IDLE_EXIT_CODE)
            self.assertIn("idle timeout", stderr_path.read_text(encoding="utf-8"))

    def test_codex_max_runtime_bounds_continuous_stdout_process(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    sys.stdin.read()
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        print('still active', flush=True)
                        time.sleep(0.1)
                    raise SystemExit(0)
                    """
                ),
            )
            output_path = task_path / "context-pack" / "runtime" / "phase1-output-attempt1.jsonl"
            stderr_path = task_path / "context-pack" / "runtime" / "phase1-stderr-attempt1.txt"

            started = time.monotonic()
            returncode = RUN_PHASES.run_codex(
                root,
                task_path,
                1,
                "prompt",
                output_path,
                stderr_path,
                str(fake),
                False,
                False,
                1,
                2,
            )
            elapsed = time.monotonic() - started

            self.assertEqual(returncode, RUN_PHASES.CODEX_MAX_RUNTIME_EXIT_CODE)
            self.assertLess(elapsed, 4.0)
            self.assertIn("still active", output_path.read_text(encoding="utf-8"))
            stderr = stderr_path.read_text(encoding="utf-8")
            self.assertIn("max runtime timeout", stderr)
            self.assertNotIn("idle timeout", stderr)

    def test_codex_max_runtime_bounds_continuous_watched_file_activity(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            self.write_contract(root, task_path, ["src/**"])
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    sys.stdin.read()
                    from pathlib import Path
                    target = Path.cwd() / "src" / "out.txt"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        target.write_text(str(time.monotonic()) + "\\n", encoding="utf-8")
                        time.sleep(0.2)
                    raise SystemExit(0)
                    """
                ),
            )
            output_path = task_path / "context-pack" / "runtime" / "phase1-output-attempt1.jsonl"
            stderr_path = task_path / "context-pack" / "runtime" / "phase1-stderr-attempt1.txt"

            started = time.monotonic()
            returncode = RUN_PHASES.run_codex(
                root,
                task_path,
                1,
                "prompt",
                output_path,
                stderr_path,
                str(fake),
                False,
                False,
                1,
                2,
            )
            elapsed = time.monotonic() - started

            self.assertEqual(returncode, RUN_PHASES.CODEX_MAX_RUNTIME_EXIT_CODE)
            self.assertLess(elapsed, 4.0)
            self.assertTrue((root / "src" / "out.txt").exists())
            stderr = stderr_path.read_text(encoding="utf-8")
            self.assertIn("max runtime timeout", stderr)
            self.assertNotIn("idle timeout", stderr)

    @unittest.skipIf(sys.platform == "win32", "process group cleanup is POSIX-specific")
    def test_codex_idle_timeout_kills_sigterm_ignoring_child_process(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            marker = tmp / "codex-child-heartbeat.txt"
            child = tmp / "codex_child.py"
            child.write_text(
                textwrap.dedent(
                    """
                    import signal
                    import sys
                    import time
                    from pathlib import Path

                    signal.signal(signal.SIGTERM, signal.SIG_IGN)
                    marker = Path(sys.argv[1])
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        with marker.open("a", encoding="utf-8") as handle:
                            handle.write("tick\\n")
                            handle.flush()
                        time.sleep(0.1)
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    f"""
                    import subprocess
                    from pathlib import Path
                    subprocess.Popen([sys.executable, {str(child)!r}, {str(marker)!r}])
                    deadline = time.monotonic() + 5
                    while not Path({str(marker)!r}).exists() and time.monotonic() < deadline:
                        time.sleep(0.05)
                    sys.stdin.read()
                    time.sleep(5)
                    raise SystemExit(0)
                    """
                ),
            )
            output_path = task_path / "context-pack" / "runtime" / "phase1-output-attempt1.jsonl"
            stderr_path = task_path / "context-pack" / "runtime" / "phase1-stderr-attempt1.txt"

            started = time.monotonic()
            returncode = RUN_PHASES.run_codex(
                root,
                task_path,
                1,
                "prompt",
                output_path,
                stderr_path,
                str(fake),
                False,
                False,
                1,
            )
            elapsed = time.monotonic() - started

            self.assertEqual(returncode, RUN_PHASES.CODEX_IDLE_EXIT_CODE)
            self.assertLess(elapsed, 4.0)
            self.assertIn("idle timeout", stderr_path.read_text(encoding="utf-8"))
            self.assertTrue(marker.exists())
            before = marker.read_text(encoding="utf-8")
            time.sleep(0.5)
            self.assertEqual(marker.read_text(encoding="utf-8"), before)

    def test_inherited_yolo_env_enables_phase_codex_yolo(self) -> None:
        args = argparse.Namespace(yolo=False)
        old_value = os.environ.get("CODEX_HARNESS_CHILD_CODEX_YOLO")
        os.environ["CODEX_HARNESS_CHILD_CODEX_YOLO"] = "1"
        try:
            RUN_PHASES.apply_inherited_yolo(args)
        finally:
            if old_value is None:
                os.environ.pop("CODEX_HARNESS_CHILD_CODEX_YOLO", None)
            else:
                os.environ["CODEX_HARNESS_CHILD_CODEX_YOLO"] = old_value

        self.assertTrue(args.yolo)
        self.assertTrue(args.yolo_inherited)

    def test_nested_codex_preflight_blocks_without_yolo(self) -> None:
        args = argparse.Namespace(dry_run=False, yolo=False)
        old_session = os.environ.get("CODEX_HARNESS_SESSION")
        old_child_yolo = os.environ.get("CODEX_HARNESS_CHILD_CODEX_YOLO")
        os.environ["CODEX_HARNESS_SESSION"] = "1"
        os.environ.pop("CODEX_HARNESS_CHILD_CODEX_YOLO", None)
        try:
            errors = RUN_PHASES.nested_codex_preflight_errors(args)
        finally:
            if old_session is None:
                os.environ.pop("CODEX_HARNESS_SESSION", None)
            else:
                os.environ["CODEX_HARNESS_SESSION"] = old_session
            if old_child_yolo is None:
                os.environ.pop("CODEX_HARNESS_CHILD_CODEX_YOLO", None)
            else:
                os.environ["CODEX_HARNESS_CHILD_CODEX_YOLO"] = old_child_yolo

        self.assertEqual(len(errors), 1)
        self.assertIn("phase child codex exec is not configured with --yolo", errors[0])

    def test_phase_gate_fails_on_quality_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            contract = {
                "scope": {"allowed_paths": ["src/**"]},
                "dependency_policy": {"new_dependencies": "forbidden"},
            }

            gate = RUN_PHASES.build_gate(
                root=root,
                task_path=task_path,
                phase_number=0,
                contract=contract,
                changed_files=["src/demo.py"],
                command_results=[],
                required_outputs=[],
                required_repo_outputs=[],
                handoff_reasons=[],
                handoff_trace_errors=[],
                quality_result={
                    "status": "failed",
                    "source": "harness",
                    "blocking_reasons": ["Quality check failed: harness-baseline-style"],
                },
            )

            self.assertEqual(gate["status"], "failed")
            self.assertIn("Quality check failed: harness-baseline-style", gate["blocking_reasons"])
            quality_check = [item for item in gate["checks"] if item["name"] == "quality"][0]
            self.assertEqual(quality_check["status"], "failed")

    def test_phase_gate_fails_on_missing_expected_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            contract = {
                "scope": {"allowed_paths": ["src/**"]},
                "dependency_policy": {"new_dependencies": "forbidden"},
                "instructions": [
                    {
                        "id": "I-1",
                        "task": "Create implementation file",
                        "expected_evidence": ["src/created.py"],
                    }
                ],
            }
            evidence = RUN_PHASES.build_evidence(
                root=root,
                phase_number=0,
                attempt=1,
                changed_files=[],
                command_results=[{"command": "true", "exit_code": 0}],
                required_outputs=[],
                required_repo_outputs=[],
                task_path=task_path,
            )

            gate = RUN_PHASES.build_gate(
                root=root,
                task_path=task_path,
                phase_number=0,
                contract=contract,
                changed_files=[],
                command_results=[{"command": "true", "exit_code": 0}],
                required_outputs=[],
                required_repo_outputs=[],
                handoff_reasons=[],
                handoff_trace_errors=[],
                evidence=evidence,
            )
            reconciliation = RUN_PHASES.build_reconciliation(contract, evidence, gate)

            self.assertEqual(gate["status"], "failed")
            self.assertIn(
                "One or more instruction expected_evidence entries were not observed.",
                gate["blocking_reasons"],
            )
            evidence_check = [item for item in gate["checks"] if item["name"] == "expected_evidence"][0]
            self.assertEqual(evidence_check["status"], "failed")
            self.assertEqual(evidence_check["failures"][0]["missing_expected_evidence"], ["src/created.py"])
            self.assertEqual(reconciliation["status"], "blocked")

    def test_expected_evidence_matches_command_id_and_required_repo_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            repo_output = root / "src" / "existing.py"
            repo_output.parent.mkdir(parents=True)
            repo_output.write_text("ok\n", encoding="utf-8")
            contract = {
                "scope": {"allowed_paths": ["src/**"]},
                "dependency_policy": {"new_dependencies": "forbidden"},
                "instructions": [
                    {
                        "id": "I-1",
                        "task": "Validate with named command and required output",
                        "expected_evidence": ["unit-tests", "src/existing.py"],
                    }
                ],
            }
            evidence = RUN_PHASES.build_evidence(
                root=root,
                phase_number=0,
                attempt=1,
                changed_files=[],
                command_results=[{"command": "python3 -m unittest", "id": "unit-tests", "exit_code": 0}],
                required_outputs=[],
                required_repo_outputs=["src/existing.py"],
                task_path=task_path,
            )

            gate = RUN_PHASES.build_gate(
                root=root,
                task_path=task_path,
                phase_number=0,
                contract=contract,
                changed_files=[],
                command_results=[{"command": "python3 -m unittest", "id": "unit-tests", "exit_code": 0}],
                required_outputs=[],
                required_repo_outputs=["src/existing.py"],
                handoff_reasons=[],
                handoff_trace_errors=[],
                evidence=evidence,
            )
            reconciliation = RUN_PHASES.build_reconciliation(contract, evidence, gate)

            self.assertEqual(gate["status"], "passed")
            evidence_check = [item for item in gate["checks"] if item["name"] == "expected_evidence"][0]
            self.assertEqual(evidence_check["status"], "passed")
            self.assertEqual(reconciliation["status"], "satisfied")
            self.assertEqual(reconciliation["instruction_results"][0]["status"], "satisfied")

    def test_execute_phase_blocks_when_task_verification_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "project": "demo",
                        "task": "demo",
                        "docs": [],
                        "common_docs": [],
                        "phases": [{"phase": 0, "name": "demo", "status": "pending"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                dry_run=False,
                max_attempts=1,
                ac_timeout=600,
                codex_bin=str(tmp / "unused-codex"),
                full_auto=False,
                yolo=False,
                codex_idle_timeout=10,
                failed=False,
                subprocess_timeout=1800,
            )

            with (
                mock.patch.object(RUN_PHASES, "verify_task", return_value=1) as verify_task,
                mock.patch.object(RUN_PHASES, "nested_codex_preflight_errors", return_value=[]),
                mock.patch.object(RUN_PHASES, "preflight_phase", return_value=[]),
            ):
                self.assertFalse(RUN_PHASES.execute_phase(root, task_path, args))

            verify_task.assert_called_once_with(root, task_path, strict_current_harness=False, timeout=1800)
            self.assertTrue(args.failed)
            last_error = (
                task_path / "context-pack" / "runtime" / "phase0-last-error.md"
            ).read_text(encoding="utf-8")
            self.assertIn("Task verification failed before phase execution.", last_error)

    def test_execute_phase_forwards_strict_current_harness_to_verification(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "project": "demo",
                        "task": "demo",
                        "docs": [],
                        "common_docs": [],
                        "phases": [{"phase": 0, "name": "demo", "status": "pending"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                dry_run=False,
                max_attempts=1,
                ac_timeout=600,
                codex_bin=str(tmp / "unused-codex"),
                full_auto=False,
                yolo=False,
                codex_idle_timeout=10,
                failed=False,
                subprocess_timeout=1800,
                strict_current_harness=True,
            )

            with (
                mock.patch.object(RUN_PHASES, "verify_task", return_value=1) as verify_task,
                mock.patch.object(RUN_PHASES, "nested_codex_preflight_errors", return_value=[]),
                mock.patch.object(RUN_PHASES, "preflight_phase", return_value=[]),
            ):
                self.assertFalse(RUN_PHASES.execute_phase(root, task_path, args))

            verify_task.assert_called_once_with(root, task_path, strict_current_harness=True, timeout=1800)

    def test_execute_phase_blocks_when_current_policy_lineage_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "project": "demo",
                        "task": "demo",
                        "docs": [],
                        "common_docs": [],
                        "phases": [{"phase": 0, "name": "demo", "status": "pending"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                dry_run=False,
                max_attempts=1,
                ac_timeout=600,
                codex_bin=str(tmp / "unused-codex"),
                full_auto=False,
                yolo=False,
                codex_idle_timeout=10,
                failed=False,
                subprocess_timeout=1800,
                strict_current_harness=False,
            )

            with (
                mock.patch.object(RUN_PHASES, "verify_task", return_value=0),
                mock.patch.object(RUN_PHASES, "current_policy_lineage_errors", return_value=["Current policy pack is stale."]),
                mock.patch.object(RUN_PHASES, "nested_codex_preflight_errors", return_value=[]),
                mock.patch.object(RUN_PHASES, "preflight_phase", return_value=[]),
                mock.patch.object(RUN_PHASES, "run_install_preflight") as install_preflight,
            ):
                self.assertFalse(RUN_PHASES.execute_phase(root, task_path, args))

            install_preflight.assert_not_called()
            self.assertTrue(args.failed)
            last_error = (
                task_path / "context-pack" / "runtime" / "phase0-last-error.md"
            ).read_text(encoding="utf-8")
            self.assertIn("Current policy pack is stale.", last_error)

    def test_execute_phase_marks_install_lock_contention_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "project": "demo",
                        "task": "demo",
                        "docs": [],
                        "common_docs": [],
                        "phases": [{"phase": 0, "name": "demo", "status": "pending"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                dry_run=False,
                max_attempts=1,
                ac_timeout=600,
                codex_bin=str(tmp / "unused-codex"),
                full_auto=False,
                yolo=False,
                codex_idle_timeout=10,
                failed=False,
            )

            def install_contention(_root: Path, _task_path: Path, _args: argparse.Namespace) -> list[str]:
                RUN_PHASES.install_preflight_path(task_path).write_text(
                    json.dumps(
                        {
                            "command": ["pnpm", "install"],
                            "exit_code": RUN_PHASES.INSTALL_PREFLIGHT_LOCK_EXIT_CODE,
                            "lock_error": "Another codex-harness process is active.",
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return ["Install preflight failed: pnpm install exited 125."]

            with (
                mock.patch.object(RUN_PHASES, "verify_task", return_value=0),
                mock.patch.object(RUN_PHASES, "nested_codex_preflight_errors", return_value=[]),
                mock.patch.object(RUN_PHASES, "preflight_phase", return_value=[]),
                mock.patch.object(RUN_PHASES, "build_prompt", return_value="prompt"),
                mock.patch.object(RUN_PHASES, "runtime_phase_contract", return_value={}),
                mock.patch.object(RUN_PHASES, "run_install_preflight", side_effect=install_contention),
            ):
                self.assertFalse(RUN_PHASES.execute_phase(root, task_path, args))

            repair_packet = json.loads(
                (task_path / "context-pack" / "runtime" / "phase0-repair-packet.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(repair_packet["failure"]["type"], "install_preflight")
            self.assertTrue(repair_packet["failure"]["retryable"])

    def test_execute_phase_dry_run_does_not_mutate_runtime_proof_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            (task_path / "phases").mkdir(parents=True)
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "project": "demo",
                        "task": "demo",
                        "docs": [],
                        "common_docs": [],
                        "phases": [{"phase": 0, "name": "demo", "status": "pending"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            contract = {
                "phase": 0,
                "name": "demo",
                "read_first": {"docs": [], "previous_outputs": []},
                "scope": {"layer": "docs", "allowed_paths": ["docs/**"]},
                "interfaces": [],
                "decision_refs": ["D-001"],
                "architecture_refs": ["A-001"],
                "dependency_policy": {"new_dependencies": "forbidden"},
                "instructions": [{"id": "P0-001", "task": "Preview prompt."}],
                "success_criteria": ["Prompt can be built."],
                "stop_rules": ["Stop if context is missing."],
                "fallback_behavior": {"if_blocked": "Report blocker."},
                "missing_evidence_behavior": "Treat missing evidence as unresolved.",
                "acceptance_commands": ["true"],
                "required_outputs": [],
            }
            (task_path / "phases" / "phase0.md").write_text(
                "# Phase 0: demo\n\n## Contract\n\n```json\n"
                + json.dumps(contract, indent=2)
                + "\n```\n",
                encoding="utf-8",
            )
            runtime_files = {
                task_path / "context-pack" / "runtime" / "phase0-prompt.md": "active prompt\n",
                RUN_PHASES.phase_contract_path(task_path, 0): '{"active":true}\n',
                RUN_PHASES.phase_checklist_path(task_path, 0): "active checklist\n",
            }
            for path, content in runtime_files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            args = argparse.Namespace(
                dry_run=True,
                max_attempts=1,
                ac_timeout=600,
                codex_bin=str(tmp / "unused-codex"),
                full_auto=False,
                yolo=False,
                codex_idle_timeout=10,
                failed=False,
            )

            with (
                mock.patch.object(RUN_PHASES, "verify_task", return_value=0),
                mock.patch.object(RUN_PHASES, "nested_codex_preflight_errors", return_value=[]),
                mock.patch.object(RUN_PHASES, "preflight_phase", return_value=[]),
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                self.assertFalse(RUN_PHASES.execute_phase(root, task_path, args))

            self.assertIn("# Harness Phase Execution Contract", stdout.getvalue())
            for path, content in runtime_files.items():
                self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_execute_phase_dry_run_preflight_failure_does_not_write_last_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "project": "demo",
                        "task": "demo",
                        "docs": [],
                        "common_docs": [],
                        "phases": [{"phase": 0, "name": "demo", "status": "pending"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                dry_run=True,
                max_attempts=1,
                ac_timeout=600,
                codex_bin=str(tmp / "unused-codex"),
                full_auto=False,
                yolo=False,
                codex_idle_timeout=10,
                failed=False,
            )

            with (
                mock.patch.object(RUN_PHASES, "verify_task", return_value=1),
                mock.patch.object(RUN_PHASES, "nested_codex_preflight_errors", return_value=[]),
                mock.patch.object(RUN_PHASES, "preflight_phase", return_value=[]),
            ):
                self.assertFalse(RUN_PHASES.execute_phase(root, task_path, args))

            self.assertTrue(args.failed)
            self.assertFalse(
                (task_path / "context-pack" / "runtime" / "phase0-last-error.md").exists()
            )

    def test_gate_fails_when_handoff_change_trace_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = {
                "scope": {"allowed_paths": ["src/app.py"]},
                "dependency_policy": {"new_dependencies": "forbidden"},
            }

            gate = RUN_PHASES.build_gate(
                root,
                task_path,
                0,
                contract,
                ["src/app.py"],
                [{"command": "true", "exit_code": 0}],
                ["context-pack/handoffs/phase0.md"],
                ["src/app.py"],
                [],
                ["Handoff must include `## Change Trace`."],
            )

            self.assertEqual(gate["status"], "failed")
            self.assertTrue(
                any(check["name"] == "handoff_change_trace" for check in gate["checks"])
            )

    def test_traceable_changed_files_ignores_required_task_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            _, task_path = self.make_task(Path(raw_tmp))

            self.assertEqual(
                RUN_PHASES.traceable_changed_files(
                    task_path,
                    [
                        "tasks/demo/context-pack/handoffs/phase0.md",
                        "src/app.py",
                    ],
                    ["context-pack/handoffs/phase0.md"],
                ),
                ["src/app.py"],
            )

    def test_runner_uses_installed_script_dir_for_verify_and_evaluate(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root = tmp / "repo"
            task_path = root / "tasks" / "demo"
            task_path.mkdir(parents=True)
            installed_scripts = root / ".codex" / "harness" / "scripts"
            installed_scripts.mkdir(parents=True)
            original_script_dir = RUN_PHASES.SCRIPT_DIR
            calls: list[list[str]] = []

            def fake_run_process(command, **kwargs):
                calls.append([str(item) for item in command])
                return RUN_PHASES.ProcessResult(0, "", "", False)

            args = argparse.Namespace(
                eval_command=["npm test"],
                full_auto=True,
                yolo=True,
                strict_current_harness=True,
                codex_max_runtime=1800,
                subprocess_timeout=1800,
            )

            try:
                RUN_PHASES.SCRIPT_DIR = installed_scripts
                with mock.patch.object(RUN_PHASES, "run_process", side_effect=fake_run_process):
                    self.assertEqual(RUN_PHASES.verify_task(root, task_path), 0)
                    self.assertEqual(RUN_PHASES.verify_task(root, task_path, require_evaluation=True), 0)
                    self.assertEqual(
                        RUN_PHASES.verify_task(root, task_path, strict_current_harness=True),
                        0,
                    )
                    self.assertEqual(RUN_PHASES.run_evaluation(root, task_path, args), 0)
            finally:
                RUN_PHASES.SCRIPT_DIR = original_script_dir

            self.assertEqual(calls[0][1], str(installed_scripts / "verify-task.py"))
            self.assertEqual(calls[1][1], str(installed_scripts / "verify-task.py"))
            self.assertIn("--require-design-approval", calls[0])
            self.assertIn("--require-design-approval", calls[1])
            self.assertIn("--require-evaluation", calls[1])
            self.assertIn("--require-design-approval", calls[2])
            self.assertIn("--strict-current-harness", calls[2])
            self.assertEqual(calls[3][1], str(installed_scripts / "evaluate-task.py"))
            self.assertIn("--command", calls[3])
            self.assertIn("npm test", calls[3])
            self.assertIn("--full-auto", calls[3])
            self.assertIn("--yolo", calls[3])
            self.assertIn("--strict-current-harness", calls[3])
            self.assertIn("--codex-max-runtime", calls[3])
            self.assertEqual(calls[3][calls[3].index("--codex-max-runtime") + 1], "1800")
            self.assertIn("--task-lock-held", calls[3])
            self.assertIn("--repo-lock-held", calls[3])

    def test_install_preflight_spawn_failure_writes_structured_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            (root / "package.json").write_text('{"packageManager":"pnpm@9.0.0"}\n', encoding="utf-8")
            (root / "pnpm-workspace.yaml").write_text("packages: []\n", encoding="utf-8")
            args = argparse.Namespace(skip_install=False, install_preflight_done=False, install_timeout=10)

            with mock.patch.object(RUN_PHASES, "run_process", side_effect=FileNotFoundError("pnpm")):
                errors = RUN_PHASES.run_install_preflight(root, task_path, args)

            self.assertTrue(any("exited 127" in error for error in errors), errors)
            payload = json.loads(RUN_PHASES.install_preflight_path(task_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["exit_code"], 127)
            self.assertIn("Failed to start install preflight command", payload["output_tail"])
            self.assertFalse(RUN_PHASES.install_preflight_lock_path(root).exists())

    def test_runner_verify_task_timeout_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            task_path.mkdir(parents=True)
            installed_scripts = root / ".codex" / "harness" / "scripts"
            installed_scripts.mkdir(parents=True)
            original_script_dir = RUN_PHASES.SCRIPT_DIR

            try:
                RUN_PHASES.SCRIPT_DIR = installed_scripts
                with mock.patch.object(
                    RUN_PHASES,
                    "run_process",
                    return_value=RUN_PHASES.ProcessResult(124, "", "", True),
                ):
                    self.assertEqual(RUN_PHASES.verify_task(root, task_path, timeout=1), 124)
            finally:
                RUN_PHASES.SCRIPT_DIR = original_script_dir

    def test_runner_evaluation_timeout_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            task_path.mkdir(parents=True)
            installed_scripts = root / ".codex" / "harness" / "scripts"
            installed_scripts.mkdir(parents=True)
            original_script_dir = RUN_PHASES.SCRIPT_DIR
            args = argparse.Namespace(
                eval_command=[],
                full_auto=False,
                yolo=False,
                codex_max_runtime=1800,
                subprocess_timeout=1,
            )

            try:
                RUN_PHASES.SCRIPT_DIR = installed_scripts
                with mock.patch.object(
                    RUN_PHASES,
                    "run_process",
                    return_value=RUN_PHASES.ProcessResult(124, "", "", True),
                ):
                    self.assertEqual(RUN_PHASES.run_evaluation(root, task_path, args), 124)
            finally:
                RUN_PHASES.SCRIPT_DIR = original_script_dir

    def test_runner_rejects_negative_subprocess_timeout(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            RUN_PHASES.non_negative_int("-1")

    def test_current_policy_lineage_errors_rejects_unapproved_current_policy(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            _, task_path = self.make_task(Path(raw_tmp))
            static_dir = task_path / "context-pack" / "static"
            static_dir.mkdir(parents=True, exist_ok=True)
            current = RUN_PHASES.policy_pack_fingerprint(RUN_PHASES.runtime_policy_pack())
            self.assertIsNotNone(current)
            assert current is not None
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

            errors = RUN_PHASES.current_policy_lineage_errors(task_path)

            self.assertTrue(any("active_policy_pack" in error for error in errors), errors)

    def test_runtime_projection_does_not_recover_revoked_policy_commit(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            static_dir = task_path / "context-pack" / "static"
            runtime_dir = task_path / "context-pack" / "runtime"
            static_dir.mkdir(parents=True, exist_ok=True)
            runtime_dir.mkdir(parents=True, exist_ok=True)
            current = RUN_PHASES.policy_pack_fingerprint(RUN_PHASES.runtime_policy_pack())
            self.assertIsNotNone(current)
            assert current is not None
            (static_dir / "design-approval.json").write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "active_policy_pack": current,
                        "approved_policy_packs": [
                            {**current, "status": "revoked", "revocation_reason": "policy withdrawn"}
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "project": "demo",
                        "task": "demo",
                        "phases": [{"phase": 0, "name": "demo", "status": "running", "attempts": 1}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            result_path = runtime_dir / "phase0-result.json"
            result = {
                "phase": 0,
                "status": "completed",
                "attempt": 1,
                "policy_pack": RUN_PHASES.runtime_policy_pack(),
                "repo_content": {
                    "changed_files": [],
                    "changed_files_digest": RUN_PHASES.stable_json_sha256([]),
                    "required_repo_outputs": [],
                    "required_repo_outputs_digest": RUN_PHASES.stable_json_sha256([]),
                },
                "artifacts": {"attempt_commit": "context-pack/runtime/phase0-attempt1-commit.json"},
            }
            result["repo_content"]["digest"] = RUN_PHASES.stable_json_sha256(result["repo_content"])
            result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
            RUN_PHASES.write_phase_attempt_commit(task_path, 0, 1, result_path)

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            self.assertEqual(changes[0]["to_status"], "error")
            self.assertEqual(changes[0]["reason"], "interrupted_running_phase")

    def test_evaluation_review_loop_improves_until_approved(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            finals = [
                {"verdict": "rejected", "required_followups": ["Fix drift."], "blockers": []},
                {"verdict": "approved", "required_followups": [], "blockers": []},
            ]
            args = argparse.Namespace(review_iterations=2, failed=False)

            def fake_run_evaluation(root_arg: Path, task_arg: Path, args_arg: argparse.Namespace) -> int:
                RUN_PHASES.write_json(RUN_PHASES.evaluation_final_path(task_arg), finals.pop(0))
                return 0

            with (
                mock.patch.object(RUN_PHASES, "run_evaluation", side_effect=fake_run_evaluation),
                mock.patch.object(RUN_PHASES, "run_evaluation_improvement", return_value=0) as improve,
            ):
                self.assertEqual(RUN_PHASES.run_evaluation_review_loop(root, task_path, args), 0)

            improve.assert_called_once()
            self.assertFalse(args.failed)

    def test_evaluation_review_loop_fails_when_rejected_after_iteration_budget(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            args = argparse.Namespace(review_iterations=1, failed=False)

            def fake_run_evaluation(root_arg: Path, task_arg: Path, args_arg: argparse.Namespace) -> int:
                RUN_PHASES.write_json(
                    RUN_PHASES.evaluation_final_path(task_arg),
                    {"verdict": "rejected", "required_followups": ["Still failing."], "blockers": []},
                )
                return 0

            with (
                mock.patch.object(RUN_PHASES, "run_evaluation", side_effect=fake_run_evaluation),
                mock.patch.object(RUN_PHASES, "run_evaluation_improvement", return_value=0) as improve,
            ):
                self.assertEqual(RUN_PHASES.run_evaluation_review_loop(root, task_path, args), 1)

            improve.assert_called_once()
            self.assertTrue(args.failed)

    def test_finalize_completed_task_marks_error_when_evaluation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            (root / "tasks" / "index.json").write_text(
                json.dumps({"tasks": [{"dir": "demo", "status": "running"}]}) + "\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(evaluate=True, failed=False)

            with (
                mock.patch.object(RUN_PHASES, "generate_relationship_graph"),
                mock.patch.object(RUN_PHASES, "verify_task", return_value=0),
                mock.patch.object(RUN_PHASES, "run_evaluation_review_loop", return_value=1),
            ):
                self.assertEqual(RUN_PHASES.finalize_completed_task(root, task_path, args), 1)

            top_index = json.loads((root / "tasks" / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(top_index["tasks"][0]["status"], "error")
            self.assertIn("failed_at", top_index["tasks"][0])
            self.assertNotIn("completed_at", top_index["tasks"][0])
            self.assertTrue(args.failed)

    def test_main_marks_top_index_error_when_completed_task_evaluation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            (root / "tasks" / "index.json").write_text(
                json.dumps({"tasks": [{"dir": "demo", "status": "running"}]}) + "\n",
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "completed"}]})
                + "\n",
                encoding="utf-8",
            )

            with (
                mock.patch.object(sys, "argv", ["run-phases.py", "demo", "--root", str(root), "--evaluate"]),
                mock.patch.object(RUN_PHASES, "harness_install_errors", return_value=[]),
                mock.patch.object(RUN_PHASES, "reconcile_before_execution"),
                mock.patch.object(RUN_PHASES, "execute_phase", return_value=False),
                mock.patch.object(RUN_PHASES, "generate_relationship_graph"),
                mock.patch.object(RUN_PHASES, "verify_task", return_value=0),
                mock.patch.object(RUN_PHASES, "run_evaluation_review_loop", return_value=1),
            ):
                self.assertEqual(RUN_PHASES.main(), 1)

            top_index = json.loads((root / "tasks" / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(top_index["tasks"][0]["status"], "error")
            self.assertIn("failed_at", top_index["tasks"][0])
            self.assertNotIn("completed_at", top_index["tasks"][0])

    def test_finalize_completed_task_requires_evaluation_artifact_verification_before_completed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            (root / "tasks" / "index.json").write_text(
                json.dumps({"tasks": [{"dir": "demo", "status": "running"}]}) + "\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(evaluate=True, failed=False)

            with (
                mock.patch.object(RUN_PHASES, "generate_relationship_graph"),
                mock.patch.object(RUN_PHASES, "verify_task", side_effect=[0, 1]) as verify,
                mock.patch.object(RUN_PHASES, "run_evaluation_review_loop", return_value=0),
            ):
                self.assertEqual(RUN_PHASES.finalize_completed_task(root, task_path, args), 1)

            self.assertEqual(verify.call_count, 2)
            self.assertEqual(
                verify.call_args_list[1].kwargs,
                {"require_evaluation": True, "strict_current_harness": False, "timeout": 1800},
            )
            top_index = json.loads((root / "tasks" / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(top_index["tasks"][0]["status"], "error")
            self.assertIn("failed_at", top_index["tasks"][0])
            self.assertNotIn("completed_at", top_index["tasks"][0])
            self.assertTrue(args.failed)

    def test_finalize_completed_task_marks_completed_after_evaluation_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            (root / "tasks" / "index.json").write_text(
                json.dumps({"tasks": [{"dir": "demo", "status": "running"}]}) + "\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(evaluate=True, failed=False)

            with (
                mock.patch.object(RUN_PHASES, "generate_relationship_graph"),
                mock.patch.object(RUN_PHASES, "verify_task", side_effect=[0, 0]) as verify,
                mock.patch.object(RUN_PHASES, "run_evaluation_review_loop", return_value=0),
            ):
                self.assertEqual(RUN_PHASES.finalize_completed_task(root, task_path, args), 0)

            self.assertEqual(verify.call_count, 2)
            self.assertEqual(
                verify.call_args_list[1].kwargs,
                {"require_evaluation": True, "strict_current_harness": False, "timeout": 1800},
            )
            top_index = json.loads((root / "tasks" / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(top_index["tasks"][0]["status"], "completed")
            self.assertIn("completed_at", top_index["tasks"][0])
            self.assertNotIn("failed_at", top_index["tasks"][0])
            self.assertFalse(args.failed)

    def test_finalize_completed_task_forwards_strict_current_harness_to_verification(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            (root / "tasks" / "index.json").write_text(
                json.dumps({"tasks": [{"dir": "demo", "status": "running"}]}) + "\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(evaluate=True, failed=False, strict_current_harness=True)

            with (
                mock.patch.object(RUN_PHASES, "generate_relationship_graph"),
                mock.patch.object(RUN_PHASES, "verify_task", side_effect=[0, 0]) as verify,
                mock.patch.object(RUN_PHASES, "run_evaluation_review_loop", return_value=0),
            ):
                self.assertEqual(RUN_PHASES.finalize_completed_task(root, task_path, args), 0)

            self.assertEqual(verify.call_count, 2)
            self.assertEqual(
                verify.call_args_list[0].kwargs,
                {"strict_current_harness": True, "timeout": 1800},
            )
            self.assertEqual(
                verify.call_args_list[1].kwargs,
                {"require_evaluation": True, "strict_current_harness": True, "timeout": 1800},
            )

    def test_evaluation_improvement_records_repo_content_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            source = root / "src" / "app.py"
            source.parent.mkdir(parents=True)
            source.write_text("before\n", encoding="utf-8")
            (task_path / "phases").mkdir(parents=True)
            (task_path / "phases" / "phase0.md").write_text(
                "# Phase 0\n\n## Contract\n\n```json\n"
                + json.dumps(
                    {
                        "phase": 0,
                        "scope": {"layer": "app", "allowed_paths": ["src/**"]},
                        "required_repo_outputs": ["src/app.py"],
                    }
                )
                + "\n```\n",
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps({"task": "demo", "phases": [{"phase": 0, "name": "app"}]}) + "\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                codex_bin="codex",
                yolo=False,
                full_auto=False,
                codex_idle_timeout=30,
            )

            def fake_run_codex_exec(*_items: object, **_kwargs: object) -> int:
                source.write_text("after\n", encoding="utf-8")
                handoff = RUN_PHASES.evaluation_repair_handoff_path(task_path, 1)
                handoff.parent.mkdir(parents=True, exist_ok=True)
                handoff.write_text(
                    "# Evaluation Repair\n\nUpdated app.\n",
                    encoding="utf-8",
                )
                return 0

            with mock.patch.object(RUN_PHASES, "run_codex_exec", side_effect=fake_run_codex_exec):
                self.assertEqual(
                    RUN_PHASES.run_evaluation_improvement(
                        root,
                        task_path,
                        args,
                        1,
                        {"verdict": "rejected", "required_followups": ["Update app."], "blockers": []},
                    ),
                    0,
                )

            result = json.loads(RUN_PHASES.evaluation_repair_result_path(task_path, 1).read_text(encoding="utf-8"))
            repo_content = result["repo_content"]
            self.assertEqual(result["status"], "completed")
            self.assertEqual(repo_content["changed_files"][0]["path"], "src/app.py")
            self.assertEqual(repo_content["changed_files"][0]["after_digest"], RUN_PHASES.file_sha256(source))
            self.assertEqual(repo_content["required_repo_outputs"], [])
            self.assertEqual(result["policy_pack"], RUN_PHASES.runtime_policy_pack())
            self.assertEqual(result["harness_attestation"], RUN_PHASES.RUNTIME_HARNESS_ATTESTATION)

    def test_codex_idle_timeout_covers_blocked_stdin_write(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    time.sleep(5)
                    raise SystemExit(0)
                    """
                ),
            )
            output_path = task_path / "context-pack" / "runtime" / "phase1-output-attempt1.jsonl"
            stderr_path = task_path / "context-pack" / "runtime" / "phase1-stderr-attempt1.txt"

            returncode = RUN_PHASES.run_codex(
                root,
                task_path,
                1,
                "x" * (1024 * 1024),
                output_path,
                stderr_path,
                str(fake),
                False,
                False,
                1,
            )

            self.assertEqual(returncode, RUN_PHASES.CODEX_IDLE_EXIT_CODE)
            self.assertIn("idle timeout", stderr_path.read_text(encoding="utf-8"))

    def test_allowed_path_file_change_counts_as_activity(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            self.write_contract(root, task_path, ["src"])
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    sys.stdin.read()
                    time.sleep(0.7)
                    from pathlib import Path
                    target = Path.cwd() / "src" / "out.txt"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("ok\\n", encoding="utf-8")
                    time.sleep(1.2)
                    raise SystemExit(0)
                    """
                ),
            )
            output_path = task_path / "context-pack" / "runtime" / "phase1-output-attempt1.jsonl"
            stderr_path = task_path / "context-pack" / "runtime" / "phase1-stderr-attempt1.txt"

            returncode = RUN_PHASES.run_codex(
                root,
                task_path,
                1,
                "prompt",
                output_path,
                stderr_path,
                str(fake),
                False,
                False,
                2,
            )

            self.assertEqual(returncode, 0, stderr_path.read_text(encoding="utf-8"))
            self.assertEqual((root / "src" / "out.txt").read_text(encoding="utf-8"), "ok\n")

    def test_contract_validation_budget_overrides_cli_defaults(self) -> None:
        args = argparse.Namespace(max_attempts=3, ac_timeout=600)
        contract = {
            "validation_budget": {
                "max_attempts": 1,
                "command_timeout_seconds": 5,
            }
        }

        self.assertEqual(RUN_PHASES.contract_validation_budget(contract, args), (1, 5))

    def test_contract_validation_budget_falls_back_to_cli_defaults(self) -> None:
        args = argparse.Namespace(max_attempts=3, ac_timeout=600)

        self.assertEqual(RUN_PHASES.contract_validation_budget({}, args), (3, 600))

    def test_gate_rejects_task_index_changes_after_phase_start(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            handoff = task_path / "context-pack" / "handoffs" / "phase0.md"
            handoff.parent.mkdir(parents=True, exist_ok=True)
            handoff.write_text("handoff\n", encoding="utf-8")
            gate = RUN_PHASES.build_gate(
                root,
                task_path,
                0,
                {"scope": {"allowed_paths": ["src/**"]}, "dependency_policy": {"new_dependencies": "allowed"}},
                [f"tasks/{task_path.name}/index.json"],
                [{"command": "true", "exit_code": 0}],
                ["context-pack/handoffs/phase0.md"],
                [],
                [],
                [],
            )

            scope_check = next(check for check in gate["checks"] if check["name"] == "scope")
            self.assertEqual(gate["status"], "failed", gate)
            self.assertIn(f"tasks/{task_path.name}/index.json", scope_check["violations"])

    def test_phase_changed_paths_uses_attempt_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            _, task_path = self.make_task(tmp)
            before = {
                "docs/product/dependency-policy.md": "existing-contamination",
            }
            after = {
                "docs/product/dependency-policy.md": "existing-contamination",
                "tasks/demo/context-pack/handoffs/phase0.md": "new-handoff",
            }

            self.assertEqual(
                RUN_PHASES.phase_changed_paths(task_path, before, after),
                ["tasks/demo/context-pack/handoffs/phase0.md"],
            )

    def test_phase_baseline_is_reused_across_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            src = root / "src" / "demo.py"
            src.parent.mkdir(parents=True)
            baseline = RUN_PHASES.load_or_create_phase_baseline(root, task_path, 0, ["src/demo.py"])

            src.write_text("print('attempt one')\n", encoding="utf-8")
            reused = RUN_PHASES.load_or_create_phase_baseline(root, task_path, 0, ["src/demo.py"])
            final_snapshot = RUN_PHASES.worktree_snapshot(root)

            self.assertEqual(reused["created_at"], baseline["created_at"])
            self.assertEqual(
                RUN_PHASES.phase_changed_paths(task_path, RUN_PHASES.baseline_snapshot(reused), final_snapshot),
                ["src/demo.py"],
            )
            self.assertEqual(
                RUN_PHASES.baseline_required_repo_outputs(reused)[0]["exists"],
                False,
            )

    def test_repair_packet_records_cleanup_required_changes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            _, task_path = self.make_task(tmp)
            packet = RUN_PHASES.build_repair_packet(
                task_path,
                0,
                {"name": "docs"},
                1,
                "gate",
                "Phase gate failed.",
                retryable=False,
                contaminating_changes=["docs/product/dependency-policy.md"],
            )
            markdown = RUN_PHASES.repair_packet_markdown(packet)

            self.assertEqual(packet["contaminating_changes"], ["docs/product/dependency-policy.md"])
            self.assertIn("## Cleanup Required", markdown)
            self.assertIn("docs/product/dependency-policy.md", markdown)

    def test_execute_phase_rejects_tampered_repair_packet_alias_before_retry(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "project": "demo",
                        "task": "demo",
                        "docs": [],
                        "common_docs": [],
                        "phases": [{"phase": 0, "name": "demo", "status": "pending", "attempts": 1}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            phase = {"phase": 0, "name": "demo"}
            packet = RUN_PHASES.build_repair_packet(
                task_path,
                0,
                phase,
                1,
                "acceptance_commands",
                "AC command failed.",
                retryable=True,
                required_outputs=[],
                required_repo_outputs=[],
            )
            RUN_PHASES.write_repair_packet(task_path, 0, packet, attempt=1)
            RUN_PHASES.phase_repair_packet_summary_path(task_path, 0).write_text(
                "tampered summary\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                dry_run=False,
                max_attempts=2,
                ac_timeout=600,
                codex_bin=str(Path(raw_tmp) / "unused-codex"),
                full_auto=False,
                yolo=False,
                codex_idle_timeout=10,
                failed=False,
                subprocess_timeout=1800,
                strict_current_harness=False,
            )

            with (
                mock.patch.object(RUN_PHASES, "verify_task", return_value=0),
                mock.patch.object(RUN_PHASES, "preflight_phase", return_value=[]),
                mock.patch.object(RUN_PHASES, "nested_codex_preflight_errors", return_value=[]),
                mock.patch.object(RUN_PHASES, "run_codex", side_effect=AssertionError("repair prompt should not start")),
            ):
                self.assertFalse(RUN_PHASES.execute_phase(root, task_path, args))

            self.assertTrue(args.failed)
            last_error = (
                task_path / "context-pack" / "runtime" / "phase0-last-error.md"
            ).read_text(encoding="utf-8")
            self.assertIn("repair packet summary", last_error)

    def test_gate_fails_when_required_repo_output_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            gate = RUN_PHASES.build_gate(
                root,
                task_path,
                0,
                {"scope": {"allowed_paths": ["apps/api/src/**"]}, "dependency_policy": {"new_dependencies": "allowed"}},
                [],
                [{"command": "true", "exit_code": 0}],
                [],
                ["apps/api/src/server.ts"],
                [],
                [],
            )

            self.assertEqual(gate["status"], "failed")
            self.assertIn("One or more required repo outputs are missing.", gate["blocking_reasons"])

    def test_gate_fails_when_handoff_reports_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            gate = RUN_PHASES.build_gate(
                root,
                task_path,
                0,
                {"scope": {"allowed_paths": ["src/**"]}, "dependency_policy": {"new_dependencies": "allowed"}},
                [],
                [{"command": "true", "exit_code": 0}],
                [],
                [],
                ["handoff matched blocked/partial marker: Status: blocked"],
                [],
            )

            self.assertEqual(gate["status"], "failed")
            self.assertIn("Handoff reports blocked, partial, skipped, or workaround status.", gate["blocking_reasons"])

    def test_resume_repair_resets_from_earliest_repair_packet_without_deleting_packet(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            (root / "tasks").mkdir(parents=True, exist_ok=True)
            (root / "tasks" / "index.json").write_text(
                json.dumps({"tasks": [{"dir": "demo", "status": "error"}]}) + "\n",
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "phases": [
                            {"phase": 0, "name": "docs", "status": "completed", "attempts": 1},
                            {"phase": 1, "name": "api", "status": "error", "attempts": 1},
                            {"phase": 2, "name": "web", "status": "pending", "attempts": 0},
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            repair_packet = task_path / "context-pack" / "runtime" / "phase1-repair-packet.json"
            repair_packet.write_text('{"phase":1}\n', encoding="utf-8")

            RUN_PHASES.apply_repair_resume(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(task_index["phases"][0]["status"], "completed")
            self.assertEqual(task_index["phases"][1]["status"], "pending")
            self.assertEqual(task_index["phases"][1]["attempts"], 0)
            self.assertEqual(task_index["phases"][2]["status"], "pending")
            self.assertTrue(RUN_PHASES.phase_reset_marker_path(task_path, 1).exists())
            self.assertTrue(RUN_PHASES.phase_reset_marker_path(task_path, 2).exists())
            self.assertTrue(repair_packet.exists())

    def test_resume_repair_ignores_attempt_scoped_repair_packet_without_alias(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            (root / "tasks").mkdir(parents=True, exist_ok=True)
            (root / "tasks" / "index.json").write_text(
                json.dumps({"tasks": [{"dir": "demo", "status": "error"}]}) + "\n",
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "phases": [
                            {"phase": 0, "name": "docs", "status": "completed", "attempts": 1},
                            {"phase": 1, "name": "api", "status": "pending", "attempts": 0},
                            {"phase": 2, "name": "web", "status": "pending", "attempts": 0},
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            repair_packet = RUN_PHASES.phase_attempt_repair_packet_path(task_path, 1, 1)
            repair_packet.parent.mkdir(parents=True, exist_ok=True)
            repair_packet.write_text('{"phase":1,"attempt":1}\n', encoding="utf-8")

            result = RUN_PHASES.apply_repair_resume(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertIsNone(result)
            self.assertEqual(task_index["phases"][0]["status"], "completed")
            self.assertEqual(task_index["phases"][1]["status"], "pending")
            self.assertFalse(RUN_PHASES.phase_reset_marker_path(task_path, 1).exists())
            self.assertTrue(repair_packet.exists())

    def test_resume_repair_ignores_stale_alias_for_completed_phase_with_valid_commit(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            handoffs = task_path / "context-pack" / "handoffs"
            runtime.mkdir(parents=True, exist_ok=True)
            handoffs.mkdir(parents=True, exist_ok=True)
            for path in [
                RUN_PHASES.phase_contract_path(task_path, 0),
                RUN_PHASES.phase_checklist_path(task_path, 0),
                RUN_PHASES.phase_quality_path(task_path, 0),
                RUN_PHASES.phase_evidence_path(task_path, 0),
                RUN_PHASES.phase_gate_path(task_path, 0),
                RUN_PHASES.phase_reconciliation_path(task_path, 0),
                RUN_PHASES.phase_reconciliation_summary_path(task_path, 0),
                RUN_PHASES.phase_handoff_path(task_path, 0),
            ]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("artifact\n", encoding="utf-8")
            prompt = RUN_PHASES.phase_attempt_prompt_path(task_path, 0, 1)
            stdout = runtime / "phase0-output-attempt1.jsonl"
            stderr = runtime / "phase0-stderr-attempt1.txt"
            ac = RUN_PHASES.write_ac_results(task_path, 0, 1, [{"command": "true", "exit_code": 0}])
            for path in [prompt, stdout, stderr]:
                path.write_text("attempt 1\n", encoding="utf-8")
            result_path = RUN_PHASES.write_phase_result(
                root,
                task_path,
                0,
                1,
                0,
                [],
                [{"command": "true", "exit_code": 0}],
                ["context-pack/handoffs/phase0.md"],
                [],
                prompt,
                stdout,
                stderr,
                ac,
            )
            RUN_PHASES.write_phase_attempt_commit(task_path, 0, 1, result_path)
            RUN_PHASES.phase_repair_packet_path(task_path, 0).write_text('{"phase":0,"attempt":1}\n', encoding="utf-8")
            (root / "tasks").mkdir(parents=True, exist_ok=True)
            (root / "tasks" / "index.json").write_text(
                json.dumps({"tasks": [{"dir": "demo", "status": "completed"}]}) + "\n",
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "completed", "attempts": 1}]}) + "\n",
                encoding="utf-8",
            )

            RUN_PHASES.apply_repair_resume(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(task_index["phases"][0]["status"], "completed")
            self.assertFalse(RUN_PHASES.phase_reset_marker_path(task_path, 0).exists())

    def test_reconcile_projection_recovers_marker_first_reset_crash_to_pending(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            result_path = RUN_PHASES.phase_result_path(task_path, 0)
            result = {"phase": 0, "attempt": 1, "status": "completed", "reset_generation": 0, "artifacts": {}}
            result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
            RUN_PHASES.phase_attempt_commit_path(task_path, 0, 1).write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "reset_generation": 0,
                        "committed_at": "2026-01-01T00:00:00+09:00",
                        "result": {
                            "path": "context-pack/runtime/phase0-result.json",
                            "sha256": RUN_PHASES.file_sha256(result_path),
                        },
                        "artifacts": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            reset_at = "2026-01-01T00:00:01+09:00"
            RUN_PHASES.write_phase_reset_marker(task_path, 0, reset_at, 0)
            (task_path / "index.json").write_text(
                json.dumps({"phases": [{"phase": 0, "name": "demo", "status": "completed", "attempts": 1}]}) + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(changes[0]["reason"], "reset_marker_without_projection")
            self.assertEqual(task_index["phases"][0]["status"], "pending")
            self.assertEqual(task_index["phases"][0]["attempts"], 0)
            self.assertEqual(task_index["phases"][0]["reset_at"], reset_at)

    def test_reconcile_projection_applies_partial_multi_phase_reset_marker_to_later_phases(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime = task_path / "context-pack" / "runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            result_path = RUN_PHASES.phase_result_path(task_path, 1)
            result = {"phase": 1, "attempt": 1, "status": "completed", "reset_generation": 0, "artifacts": {}}
            result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
            RUN_PHASES.phase_attempt_commit_path(task_path, 1, 1).write_text(
                json.dumps(
                    {
                        "phase": 1,
                        "attempt": 1,
                        "reset_generation": 0,
                        "committed_at": "2026-01-01T00:00:00+09:00",
                        "result": {
                            "path": "context-pack/runtime/phase1-result.json",
                            "sha256": RUN_PHASES.file_sha256(result_path),
                        },
                        "artifacts": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            reset_at = "2026-01-01T00:00:01+09:00"
            RUN_PHASES.write_phase_reset_marker(task_path, 0, reset_at, 0)
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "phases": [
                            {"phase": 0, "name": "docs", "status": "pending", "attempts": 0},
                            {"phase": 1, "name": "api", "status": "completed", "attempts": 1},
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            changes = RUN_PHASES.reconcile_runtime_projection(root, task_path, dry_run=False)

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            by_phase = {item["phase"]: item for item in changes}
            self.assertEqual(by_phase[1]["reason"], "reset_marker_without_projection")
            self.assertEqual(task_index["phases"][1]["status"], "pending")
            self.assertEqual(task_index["phases"][1]["reset_at"], reset_at)
            self.assertIsNone(RUN_PHASES.latest_valid_phase_attempt_commit(task_path, 1))

    def test_phase_reset_state_does_not_propagate_later_phase_marker_backward(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            reset_at = "2026-01-01T00:00:00+09:00"
            RUN_PHASES.write_phase_reset_marker(task_path, 0, reset_at, 0)
            RUN_PHASES.write_phase_reset_marker(task_path, 1, reset_at, 0)

            self.assertEqual(RUN_PHASES.phase_reset_state(task_path, 0), (1, reset_at))
            self.assertEqual(RUN_PHASES.phase_reset_state(task_path, 1), (1, reset_at))

    def test_phase_reset_marker_generation_uses_own_phase_marker(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            RUN_PHASES.write_phase_reset_marker(task_path, 1, "2026-01-01T00:00:00+09:00", 1)
            RUN_PHASES.write_phase_reset_marker(task_path, 0, "2026-01-01T00:00:01+09:00", 0)

            marker_path = RUN_PHASES.write_phase_reset_marker(task_path, 1, "2026-01-01T00:00:01+09:00", 0)

            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            self.assertEqual(marker["reset_generation"], 2)
            self.assertEqual(marker["reset_id"], "phase1-reset2")

    def test_runner_relationship_graph_generation_is_non_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)

            RUN_PHASES.generate_relationship_graph(root, task_path)

            self.assertTrue((task_path / "context-pack" / "runtime" / "relationship-graph.json").exists())
            self.assertTrue((task_path / "context-pack" / "runtime" / "relationship-graph.mmd").exists())

    def test_runner_relationship_graph_warning_is_recorded_in_progress(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)

            with mock.patch("relationship_graph.graph_from_task", side_effect=ValueError("boom")):
                RUN_PHASES.generate_relationship_graph(root, task_path)

            progress = task_path / "context-pack" / "runtime" / "progress.md"
            warning = task_path / "context-pack" / "runtime" / "relationship-graph-warning.json"
            self.assertTrue(warning.exists())
            self.assertIn("relationship graph warning:", progress.read_text(encoding="utf-8"))

    def test_runner_relationship_graph_warning_without_file_is_recorded_as_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)

            with mock.patch(
                "relationship_graph.write_relationship_graph_outputs",
                return_value={
                    "status": "warning",
                    "json": None,
                    "mermaid": None,
                    "warning": None,
                    "error": "mkdir failed",
                    "warning_error": "runtime path is not a directory",
                },
            ):
                RUN_PHASES.generate_relationship_graph(root, task_path)

            progress_text = (task_path / "context-pack" / "runtime" / "progress.md").read_text(encoding="utf-8")
            self.assertIn("relationship graph warning file unavailable: runtime path is not a directory", progress_text)
            self.assertNotIn("relationship-graph-warning.json", progress_text)

    def test_install_preflight_runs_once_even_when_node_modules_exists(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            (root / "package.json").write_text('{"packageManager":"pnpm@9.0.0"}\n', encoding="utf-8")
            (root / "pnpm-workspace.yaml").write_text("packages: []\n", encoding="utf-8")
            (root / "node_modules").mkdir()
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            marker = tmp / "pnpm-runs.txt"
            pnpm = fake_bin / "pnpm"
            pnpm.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('run\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            pnpm.chmod(pnpm.stat().st_mode | 0o111)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{fake_bin}:{old_path}"
            try:
                args = argparse.Namespace(skip_install=False, install_preflight_done=False, install_timeout=10)
                self.assertEqual(RUN_PHASES.run_install_preflight(root, task_path, args), [])
                self.assertEqual(RUN_PHASES.run_install_preflight(root, task_path, args), [])
            finally:
                os.environ["PATH"] = old_path

            self.assertEqual(marker.read_text(encoding="utf-8"), "run\n")
            self.assertFalse(RUN_PHASES.install_preflight_lock_path(root).exists())

    def test_install_preflight_rejects_concurrent_repo_install(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            (root / "package.json").write_text('{"packageManager":"pnpm@9.0.0"}\n', encoding="utf-8")
            (root / "pnpm-workspace.yaml").write_text("packages: []\n", encoding="utf-8")
            lock_path = RUN_PHASES.install_preflight_lock_path(root)
            lock_handle = file_lock.acquire_lock(lock_path, wait_timeout_seconds=0.0)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            marker = tmp / "pnpm-runs.txt"
            pnpm = fake_bin / "pnpm"
            pnpm.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('run\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            pnpm.chmod(pnpm.stat().st_mode | 0o111)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{fake_bin}:{old_path}"
            try:
                args = argparse.Namespace(skip_install=False, install_preflight_done=False, install_timeout=10)
                errors = RUN_PHASES.run_install_preflight(root, task_path, args)
            finally:
                os.environ["PATH"] = old_path
                file_lock.release_lock(lock_handle)

            self.assertTrue(any("exited 125" in error for error in errors), errors)
            self.assertFalse(marker.exists())
            payload = json.loads(RUN_PHASES.install_preflight_path(task_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["exit_code"], 125)
            self.assertIn("lock_error", payload)

    def test_install_preflight_reclaims_stale_repo_install_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            (root / "package.json").write_text('{"packageManager":"pnpm@9.0.0"}\n', encoding="utf-8")
            (root / "pnpm-workspace.yaml").write_text("packages: []\n", encoding="utf-8")
            lock_path = RUN_PHASES.install_preflight_lock_path(root)
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.write_text(json.dumps({"pid": -1, "started_at": "stale"}) + "\n", encoding="utf-8")
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            marker = tmp / "pnpm-runs.txt"
            pnpm = fake_bin / "pnpm"
            pnpm.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('run\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            pnpm.chmod(pnpm.stat().st_mode | 0o111)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{fake_bin}:{old_path}"
            try:
                args = argparse.Namespace(skip_install=False, install_preflight_done=False, install_timeout=10)
                errors = RUN_PHASES.run_install_preflight(root, task_path, args)
            finally:
                os.environ["PATH"] = old_path

            self.assertEqual(errors, [])
            self.assertEqual(marker.read_text(encoding="utf-8"), "run\n")
            self.assertFalse(lock_path.exists())

    def test_install_preflight_timeout_releases_repo_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            (root / "package.json").write_text('{"packageManager":"pnpm@9.0.0"}\n', encoding="utf-8")
            (root / "pnpm-workspace.yaml").write_text("packages: []\n", encoding="utf-8")
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            pnpm = fake_bin / "pnpm"
            pnpm.write_text(
                "#!/usr/bin/env python3\n"
                "import time\n"
                "print('api_key=sk-timeoutabcdefghijklmnopqrstuvwxyz123456', flush=True)\n"
                "time.sleep(2)\n",
                encoding="utf-8",
            )
            pnpm.chmod(pnpm.stat().st_mode | 0o111)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{fake_bin}:{old_path}"
            try:
                args = argparse.Namespace(skip_install=False, install_preflight_done=False, install_timeout=1)
                errors = RUN_PHASES.run_install_preflight(root, task_path, args)
            finally:
                os.environ["PATH"] = old_path

            self.assertTrue(any("exited 124" in error for error in errors), errors)
            payload = json.loads(RUN_PHASES.install_preflight_path(task_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["exit_code"], 124)
            self.assertIn("[REDACTED]", payload["output_tail"])
            self.assertNotIn("sk-timeout", payload["output_tail"])
            self.assertFalse(RUN_PHASES.install_preflight_lock_path(root).exists())

    @unittest.skipIf(sys.platform == "win32", "process group cleanup is POSIX-specific")
    def test_install_preflight_timeout_kills_child_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            (root / "package.json").write_text('{"packageManager":"pnpm@9.0.0"}\n', encoding="utf-8")
            (root / "pnpm-workspace.yaml").write_text("packages: []\n", encoding="utf-8")
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            marker = tmp / "install-heartbeat.txt"
            child = tmp / "install_child.py"
            child.write_text(
                textwrap.dedent(
                    """
                    import signal
                    import sys
                    import time
                    from pathlib import Path

                    signal.signal(signal.SIGTERM, signal.SIG_IGN)
                    marker = Path(sys.argv[1])
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        with marker.open("a", encoding="utf-8") as handle:
                            handle.write("tick\\n")
                            handle.flush()
                        time.sleep(0.1)
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            pnpm = fake_bin / "pnpm"
            pnpm.write_text(
                textwrap.dedent(
                    f"""
                    #!{sys.executable}
                    import subprocess
                    import sys
                    import time
                    from pathlib import Path

                    marker = Path({str(marker)!r})
                    subprocess.Popen([sys.executable, {str(child)!r}, str(marker)])
                    deadline = time.monotonic() + 5
                    while not marker.exists() and time.monotonic() < deadline:
                        time.sleep(0.05)
                    print('api_key=sk-timeoutabcdefghijklmnopqrstuvwxyz123456', flush=True)
                    time.sleep(30)
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            pnpm.chmod(pnpm.stat().st_mode | 0o111)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{fake_bin}:{old_path}"
            try:
                args = argparse.Namespace(skip_install=False, install_preflight_done=False, install_timeout=1)
                started = time.monotonic()
                errors = RUN_PHASES.run_install_preflight(root, task_path, args)
                elapsed = time.monotonic() - started
            finally:
                os.environ["PATH"] = old_path

            self.assertTrue(any("exited 124" in error for error in errors), errors)
            self.assertLess(elapsed, 3.0)
            payload = json.loads(RUN_PHASES.install_preflight_path(task_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["exit_code"], 124)
            self.assertIn("[REDACTED]", payload["output_tail"])
            self.assertNotIn("sk-timeout", payload["output_tail"])
            self.assertFalse(RUN_PHASES.install_preflight_lock_path(root).exists())
            self.assertTrue(marker.exists())
            before = marker.read_text(encoding="utf-8")
            time.sleep(0.5)
            self.assertEqual(marker.read_text(encoding="utf-8"), before)

    def test_install_preflight_sanitizes_env_and_redacts_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            (root / "package.json").write_text('{"packageManager":"pnpm@9.0.0"}\n', encoding="utf-8")
            (root / "pnpm-workspace.yaml").write_text("packages: []\n", encoding="utf-8")
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            pnpm = fake_bin / "pnpm"
            pnpm.write_text(
                "#!/usr/bin/env python3\n"
                "import os\n"
                "print('NPM_TOKEN=' + os.environ.get('NPM_TOKEN', 'missing'))\n"
                "print('OPENAI_API_KEY=' + os.environ.get('OPENAI_API_KEY', 'missing'))\n"
                "print('api_key=sk-abcdefghijklmnopqrstuvwxyz123456')\n"
                "print('//registry.npmjs.org/:_authToken=npm_secret_token_1234567890')\n"
                "raise SystemExit(1)\n",
                encoding="utf-8",
            )
            pnpm.chmod(pnpm.stat().st_mode | 0o111)
            old_path = os.environ.get("PATH", "")
            old_npm_token = os.environ.get("NPM_TOKEN")
            old_openai_key = os.environ.get("OPENAI_API_KEY")
            old_env_allow = os.environ.get("CODEX_HARNESS_ENV_ALLOW")
            os.environ["PATH"] = f"{fake_bin}:{old_path}"
            os.environ["NPM_TOKEN"] = "npm_secret_token_1234567890"
            os.environ["OPENAI_API_KEY"] = "sk-abcdefghijklmnopqrstuvwxyz999999"
            os.environ["CODEX_HARNESS_ENV_ALLOW"] = "NPM_TOKEN"
            try:
                args = argparse.Namespace(skip_install=False, install_preflight_done=False, install_timeout=10)
                errors = RUN_PHASES.run_install_preflight(root, task_path, args)
            finally:
                os.environ["PATH"] = old_path
                if old_npm_token is None:
                    os.environ.pop("NPM_TOKEN", None)
                else:
                    os.environ["NPM_TOKEN"] = old_npm_token
                if old_openai_key is None:
                    os.environ.pop("OPENAI_API_KEY", None)
                else:
                    os.environ["OPENAI_API_KEY"] = old_openai_key
                if old_env_allow is None:
                    os.environ.pop("CODEX_HARNESS_ENV_ALLOW", None)
                else:
                    os.environ["CODEX_HARNESS_ENV_ALLOW"] = old_env_allow

            self.assertTrue(any("exited 1" in error for error in errors), errors)
            payload = json.loads(RUN_PHASES.install_preflight_path(task_path).read_text(encoding="utf-8"))
            output = payload["output_tail"]
            self.assertTrue(payload["env_sanitized"])
            self.assertTrue(payload["output_redacted"])
            self.assertEqual(payload["install_timeout_seconds"], 10)
            self.assertEqual(payload["policy_pack"], RUN_PHASES.runtime_policy_pack())
            self.assertIn("NPM_TOKEN=missing", output)
            self.assertIn("OPENAI_API_KEY=missing", output)
            self.assertIn("[REDACTED]", output)
            self.assertNotIn("npm_secret_token_1234567890", output)
            self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", output)

    def test_install_preflight_lock_contention_is_retryable_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            _, task_path = self.make_task(Path(raw_tmp))
            RUN_PHASES.install_preflight_path(task_path).write_text(
                json.dumps(
                    {
                        "command": ["pnpm", "install"],
                        "exit_code": RUN_PHASES.INSTALL_PREFLIGHT_LOCK_EXIT_CODE,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertTrue(RUN_PHASES.install_preflight_failure_retryable(task_path))

    def test_execute_phase_uses_contract_attempt_budget(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root = tmp / "repo"
            task_path = root / "tasks" / "demo"
            (root / "scripts" / "harness").mkdir(parents=True)
            (task_path / "phases").mkdir(parents=True)
            (task_path / "context-pack" / "runtime").mkdir(parents=True)
            (task_path / "context-pack" / "handoffs").mkdir(parents=True)
            for static_file in RUN_PHASES.MANDATORY_STATIC_FILES:
                target = task_path / "context-pack" / "static" / static_file
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(self.static_content(static_file), encoding="utf-8")
            docs = []
            for index in range(5):
                doc_path = root / f"doc{index}.md"
                doc_path.write_text("doc\n", encoding="utf-8")
                docs.append(doc_path.name)
            quality_doc = root / "docs" / "harness" / "implementation-quality.md"
            quality_doc.parent.mkdir(parents=True, exist_ok=True)
            quality_doc.write_text("quality\n", encoding="utf-8")
            subprocess_result = subprocess.run(
                ["git", "init"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(subprocess_result.returncode, 0, subprocess_result.stderr)

            contract = {
                "phase": 0,
                "name": "demo",
                "read_first": {"docs": docs, "previous_outputs": []},
                "scope": {"layer": "docs", "allowed_paths": ["src"]},
                "interfaces": [],
                "decision_refs": ["D-001"],
                "architecture_refs": ["A-001"],
                "dependency_policy": {
                    "new_dependencies": "forbidden",
                    "approved_new_dependencies": [],
                    "approved_dependency_manifest_changes": [],
                },
                "instructions": [
                    {
                        "id": "P0-001",
                        "task": "Write the handoff.",
                        "expected_evidence": ["context-pack/handoffs/phase0.md"],
                    }
                ],
                "success_criteria": ["The handoff exists."],
                "stop_rules": ["Stop if required context is missing."],
                "fallback_behavior": {
                    "if_blocked": "Write the blocker to the handoff.",
                    "if_tests_fail": "Fix failures inside allowed_paths.",
                },
                "validation_budget": {
                    "max_attempts": 1,
                    "command_timeout_seconds": 600,
                },
                "missing_evidence_behavior": "Treat missing evidence as unresolved.",
                "acceptance_commands": ["false"],
                "required_outputs": ["context-pack/handoffs/phase0.md"],
                "forbidden": [
                    {
                        "rule": "Do not update task status.",
                        "reason": "The runner owns status.",
                    }
                ],
            }
            (task_path / "phases" / "phase0.md").write_text(
                "# Phase 0: demo\n\n## Contract\n\n```json\n"
                + json.dumps(contract, indent=2)
                + "\n```\n",
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "project": "demo",
                        "task": "demo",
                        "docs": docs,
                        "common_docs": ["docs/harness/implementation-quality.md"],
                        "phases": [{"phase": 0, "name": "demo", "status": "pending"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    sys.stdin.read()
                    from pathlib import Path
                    Path.cwd().joinpath("tasks/demo/context-pack/handoffs/phase0.md").write_text(
                        "handoff\\n",
                        encoding="utf-8",
                    )
                    Path.cwd().joinpath("outside.txt").write_text("outside\\n", encoding="utf-8")
                    raise SystemExit(0)
                    """
                ),
            )
            args = argparse.Namespace(
                dry_run=False,
                max_attempts=3,
                ac_timeout=600,
                codex_bin=str(fake),
                full_auto=False,
                yolo=False,
                codex_idle_timeout=10,
                failed=False,
            )

            with mock.patch.object(RUN_PHASES, "verify_task", return_value=0):
                self.assertFalse(RUN_PHASES.execute_phase(root, task_path, args))
            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(task_index["phases"][0]["attempts"], 1)
            self.assertEqual(task_index["phases"][0]["status"], "error")
            repair_packet = json.loads(
                (task_path / "context-pack" / "runtime" / "phase0-repair-packet.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(repair_packet["failure"]["retryable"])
            self.assertEqual(repair_packet["contaminating_changes"], ["outside.txt"])
            last_error = (
                task_path / "context-pack" / "runtime" / "phase0-last-error.md"
            ).read_text(encoding="utf-8")
            self.assertIn("outside.txt", last_error)

    def test_execute_phase_success_writes_attempt_commit_and_uses_phase_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            (task_path / "phases").mkdir(parents=True)
            (task_path / "context-pack" / "handoffs").mkdir(parents=True)
            subprocess.run(["git", "init"], cwd=root, text=True, capture_output=True, check=False)
            contract = {
                "phase": 0,
                "name": "demo",
                "read_first": {"docs": [], "previous_outputs": []},
                "scope": {"layer": "app", "allowed_paths": ["src/**"]},
                "interfaces": [],
                "decision_refs": [],
                "architecture_refs": [],
                "dependency_policy": {
                    "new_dependencies": "forbidden",
                    "approved_new_dependencies": [],
                    "approved_dependency_manifest_changes": [],
                },
                "instructions": [
                    {
                        "id": "P0-001",
                        "task": "Create app output.",
                        "expected_evidence": ["src/app.py"],
                    }
                ],
                "success_criteria": ["The app output exists."],
                "stop_rules": ["Stop if required context is missing."],
                "fallback_behavior": {
                    "if_blocked": "Write the blocker to the handoff.",
                    "if_tests_fail": "Fix failures inside allowed_paths.",
                },
                "validation_budget": {
                    "max_attempts": 2,
                    "command_timeout_seconds": 600,
                },
                "missing_evidence_behavior": "Treat missing evidence as unresolved.",
                "acceptance_commands": ["true"],
                "required_outputs": ["context-pack/handoffs/phase0.md"],
                "required_repo_outputs": ["src/app.py"],
                "forbidden": [
                    {
                        "rule": "Do not update task status.",
                        "reason": "The runner owns status.",
                    }
                ],
            }
            (task_path / "phases" / "phase0.md").write_text(
                "# Phase 0: demo\n\n## Contract\n\n```json\n"
                + json.dumps(contract, indent=2)
                + "\n```\n",
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "project": "demo",
                        "task": "demo",
                        "docs": [],
                        "common_docs": [],
                        "phases": [{"phase": 0, "name": "demo", "status": "pending"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    sys.stdin.read()
                    from pathlib import Path
                    Path.cwd().joinpath("src/app.py").parent.mkdir(parents=True, exist_ok=True)
                    Path.cwd().joinpath("src/app.py").write_text("ok\\n", encoding="utf-8")
                    Path.cwd().joinpath("tasks/demo/context-pack/handoffs/phase0.md").write_text(
                        "# Handoff\\n\\n## Change Trace\\n\\n- `src/app.py`: `P0-001`\\n",
                        encoding="utf-8",
                    )
                    raise SystemExit(0)
                    """
                ),
            )
            args = argparse.Namespace(
                dry_run=False,
                max_attempts=3,
                ac_timeout=600,
                codex_bin=str(fake),
                full_auto=False,
                yolo=False,
                codex_idle_timeout=10,
                failed=False,
            )

            with (
                mock.patch.object(RUN_PHASES, "verify_task", return_value=0),
                mock.patch.object(RUN_PHASES, "preflight_phase", return_value=[]),
                mock.patch.object(RUN_PHASES, "nested_codex_preflight_errors", return_value=[]),
                mock.patch.object(
                    RUN_PHASES,
                    "run_quality_checks",
                    return_value={"status": "passed", "checks": [], "blocking_reasons": []},
                ),
            ):
                self.assertTrue(RUN_PHASES.execute_phase(root, task_path, args))

            result = json.loads(RUN_PHASES.phase_result_path(task_path, 0).read_text(encoding="utf-8"))
            commit_path = task_path / result["artifacts"]["attempt_commit"]
            commit = json.loads(commit_path.read_text(encoding="utf-8"))
            baseline = json.loads(RUN_PHASES.phase_baseline_path(task_path, 0).read_text(encoding="utf-8"))
            self.assertEqual(result["artifacts"]["prompt"], "context-pack/runtime/phase0-prompt-attempt1.md")
            self.assertEqual(result["artifacts"]["contract"], "context-pack/runtime/phase0-contract-attempt1.json")
            self.assertEqual(result["artifacts"]["checklist"], "context-pack/runtime/phase0-checklist-attempt1.md")
            self.assertTrue((task_path / "context-pack" / "runtime" / "phase0-prompt.md").exists())
            self.assertTrue(RUN_PHASES.phase_contract_path(task_path, 0).exists())
            self.assertTrue(RUN_PHASES.phase_checklist_path(task_path, 0).exists())
            self.assertEqual(result["repo_content"]["required_repo_outputs"][0]["before"]["exists"], False)
            self.assertEqual(commit["result"]["path"], "context-pack/runtime/phase0-result-attempt1.json")
            self.assertEqual(
                commit["result"]["sha256"],
                RUN_PHASES.file_sha256(RUN_PHASES.phase_attempt_result_path(task_path, 0, 1)),
            )
            by_name = {item["name"]: item for item in commit["artifacts"]}
            self.assertEqual(
                by_name["prompt"]["sha256"],
                RUN_PHASES.file_sha256(task_path / result["artifacts"]["prompt"]),
            )
            manifest = self.read_attempt_manifest(task_path, 0)
            self.assertEqual([item["record_type"] for item in manifest], ["attempt_started", "attempt_committed"])
            self.assertEqual(manifest[0]["status"], "running")
            self.assertEqual(manifest[1]["status"], "committed")
            self.assertEqual(manifest[1]["result"]["path"], "context-pack/runtime/phase0-result-attempt1.json")
            self.assertEqual(manifest[1]["attempt_commit"]["path"], "context-pack/runtime/phase0-attempt1-commit.json")
            self.assertEqual(manifest[1]["attempt_commit"]["sha256"], RUN_PHASES.file_sha256(commit_path))
            self.assertIn("src/app.py", result["changed_files"])
            self.assertEqual(baseline["required_repo_outputs"][0]["path"], "src/app.py")

    def test_execute_phase_ignores_tampered_contract_alias_after_codex(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            (task_path / "phases").mkdir(parents=True)
            (task_path / "context-pack" / "handoffs").mkdir(parents=True)
            subprocess.run(["git", "init"], cwd=root, text=True, capture_output=True, check=False)
            contract = {
                "phase": 0,
                "name": "demo",
                "read_first": {"docs": [], "previous_outputs": []},
                "scope": {"layer": "app", "allowed_paths": ["src/**"]},
                "interfaces": [],
                "decision_refs": [],
                "architecture_refs": [],
                "dependency_policy": {
                    "new_dependencies": "forbidden",
                    "approved_new_dependencies": [],
                    "approved_dependency_manifest_changes": [],
                },
                "instructions": [
                    {
                        "id": "P0-001",
                        "task": "Create app output.",
                        "expected_evidence": ["src/app.py"],
                    }
                ],
                "success_criteria": ["The app output exists."],
                "stop_rules": ["Stop if required context is missing."],
                "fallback_behavior": {
                    "if_blocked": "Write the blocker to the handoff.",
                    "if_tests_fail": "Fix failures inside allowed_paths.",
                },
                "validation_budget": {
                    "max_attempts": 1,
                    "command_timeout_seconds": 600,
                },
                "missing_evidence_behavior": "Treat missing evidence as unresolved.",
                "acceptance_commands": ["false"],
                "required_outputs": ["context-pack/handoffs/phase0.md"],
                "required_repo_outputs": ["src/app.py"],
                "forbidden": [
                    {
                        "rule": "Do not update task status.",
                        "reason": "The runner owns status.",
                    }
                ],
            }
            (task_path / "phases" / "phase0.md").write_text(
                "# Phase 0: demo\n\n## Contract\n\n```json\n"
                + json.dumps(contract, indent=2)
                + "\n```\n",
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "project": "demo",
                        "task": "demo",
                        "docs": [],
                        "common_docs": [],
                        "phases": [{"phase": 0, "name": "demo", "status": "pending"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    sys.stdin.read()
                    import json
                    from pathlib import Path
                    Path.cwd().joinpath("src/app.py").parent.mkdir(parents=True, exist_ok=True)
                    Path.cwd().joinpath("src/app.py").write_text("ok\\n", encoding="utf-8")
                    Path.cwd().joinpath("tasks/demo/context-pack/handoffs/phase0.md").write_text(
                        "# Handoff\\n\\n## Change Trace\\n\\n- `src/app.py`: `P0-001`\\n",
                        encoding="utf-8",
                    )
                    alias = Path.cwd().joinpath("tasks/demo/context-pack/runtime/phase0-contract.json")
                    data = json.loads(alias.read_text(encoding="utf-8"))
                    data["acceptance_commands"] = ["true"]
                    data["required_repo_outputs"] = []
                    alias.write_text(json.dumps(data) + "\\n", encoding="utf-8")
                    raise SystemExit(0)
                    """
                ),
            )
            args = argparse.Namespace(
                dry_run=False,
                max_attempts=3,
                ac_timeout=600,
                codex_bin=str(fake),
                full_auto=False,
                yolo=False,
                codex_idle_timeout=10,
                failed=False,
            )

            with (
                mock.patch.object(RUN_PHASES, "verify_task", return_value=0),
                mock.patch.object(RUN_PHASES, "preflight_phase", return_value=[]),
                mock.patch.object(RUN_PHASES, "nested_codex_preflight_errors", return_value=[]),
            ):
                self.assertFalse(RUN_PHASES.execute_phase(root, task_path, args))

            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(task_index["phases"][0]["status"], "error")
            self.assertFalse(RUN_PHASES.phase_result_path(task_path, 0).exists())
            last_error = (task_path / "context-pack" / "runtime" / "phase0-last-error.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("AC command failed: false", last_error)

    def test_execute_phase_retry_keeps_attempt_prompt_artifacts_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            (task_path / "phases").mkdir(parents=True)
            (task_path / "context-pack" / "handoffs").mkdir(parents=True)
            subprocess.run(["git", "init"], cwd=root, text=True, capture_output=True, check=False)
            ac_counter = tmp / "ac-counter.txt"
            ac_script = tmp / "acceptance.py"
            ac_script.write_text(
                "from pathlib import Path\n"
                f"counter = Path({str(ac_counter)!r})\n"
                "count = int(counter.read_text(encoding='utf-8')) if counter.exists() else 0\n"
                "counter.write_text(str(count + 1), encoding='utf-8')\n"
                "raise SystemExit(1 if count == 0 else 0)\n",
                encoding="utf-8",
            )
            contract = {
                "phase": 0,
                "name": "demo",
                "read_first": {"docs": [], "previous_outputs": []},
                "scope": {
                    "layer": "docs",
                    "allowed_paths": ["tasks/demo/context-pack/handoffs/**", "tasks/demo/index.json"],
                },
                "interfaces": [],
                "decision_refs": [],
                "architecture_refs": [],
                "dependency_policy": {"new_dependencies": "forbidden"},
                "instructions": [{"id": "P0-001", "task": "Write the handoff."}],
                "success_criteria": ["The handoff exists."],
                "stop_rules": ["Stop if required context is missing."],
                "fallback_behavior": {"if_blocked": "Write the blocker to the handoff."},
                "validation_budget": {"max_attempts": 2, "command_timeout_seconds": 600},
                "missing_evidence_behavior": "Treat missing evidence as unresolved.",
                "acceptance_commands": [f"{sys.executable} {ac_script}"],
                "required_outputs": ["context-pack/handoffs/phase0.md"],
            }
            (task_path / "phases" / "phase0.md").write_text(
                "# Phase 0: demo\n\n## Contract\n\n```json\n"
                + json.dumps(contract, indent=2)
                + "\n```\n",
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "project": "demo",
                        "task": "demo",
                        "docs": [],
                        "common_docs": [],
                        "phases": [{"phase": 0, "name": "demo", "status": "pending"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    sys.stdin.read()
                    from pathlib import Path
                    Path.cwd().joinpath("tasks/demo/context-pack/handoffs/phase0.md").write_text(
                        "# Handoff\\n\\n## Change Trace\\n\\n- `tasks/demo/index.json`: `P0-001`\\n",
                        encoding="utf-8",
                    )
                    raise SystemExit(0)
                    """
                ),
            )
            args = argparse.Namespace(
                dry_run=False,
                max_attempts=3,
                ac_timeout=600,
                codex_bin=str(fake),
                full_auto=False,
                yolo=False,
                codex_idle_timeout=10,
                failed=False,
            )

            with (
                mock.patch.object(RUN_PHASES, "verify_task", return_value=0),
                mock.patch.object(RUN_PHASES, "preflight_phase", return_value=[]),
                mock.patch.object(RUN_PHASES, "nested_codex_preflight_errors", return_value=[]),
                mock.patch.object(
                    RUN_PHASES,
                    "run_quality_checks",
                    return_value={"status": "passed", "checks": [], "blocking_reasons": []},
                ),
            ):
                self.assertTrue(RUN_PHASES.execute_phase(root, task_path, args))

            result = json.loads(RUN_PHASES.phase_result_path(task_path, 0).read_text(encoding="utf-8"))
            commit = json.loads((task_path / result["artifacts"]["attempt_commit"]).read_text(encoding="utf-8"))
            attempt1_prompt = RUN_PHASES.phase_attempt_prompt_path(task_path, 0, 1)
            attempt2_prompt = RUN_PHASES.phase_attempt_prompt_path(task_path, 0, 2)
            self.assertEqual(result["attempt"], 2)
            self.assertTrue(attempt1_prompt.exists())
            self.assertTrue(attempt2_prompt.exists())
            self.assertNotIn("Repair mode:", attempt1_prompt.read_text(encoding="utf-8"))
            self.assertIn("Repair mode:", attempt2_prompt.read_text(encoding="utf-8"))
            self.assertEqual(result["artifacts"]["prompt"], "context-pack/runtime/phase0-prompt-attempt2.md")
            self.assertEqual(
                result["artifacts"]["repair_packet"],
                "context-pack/runtime/phase0-repair-packet-attempt1.json",
            )
            self.assertTrue(RUN_PHASES.phase_attempt_repair_packet_path(task_path, 0, 1).exists())
            self.assertTrue(RUN_PHASES.phase_attempt_repair_packet_summary_path(task_path, 0, 1).exists())
            self.assertFalse(RUN_PHASES.phase_repair_packet_path(task_path, 0).exists())
            self.assertFalse(RUN_PHASES.phase_repair_packet_summary_path(task_path, 0).exists())
            repair_packet = json.loads(
                RUN_PHASES.phase_attempt_repair_packet_path(task_path, 0, 1).read_text(encoding="utf-8")
            )
            self.assertEqual(repair_packet["attempt"], 1)
            self.assertEqual(repair_packet["failure"]["type"], "acceptance_commands")
            repair_artifacts = {item["name"]: item for item in repair_packet["failed_attempt_artifacts"]}
            self.assertTrue(repair_artifacts["prompt"]["exists"])
            self.assertTrue(repair_artifacts["ac_results"]["exists"])
            by_name = {item["name"]: item for item in commit["artifacts"]}
            self.assertEqual(by_name["prompt"]["sha256"], RUN_PHASES.file_sha256(attempt2_prompt))

    def test_execute_phase_retry_keeps_failed_gate_attempt_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            (task_path / "phases").mkdir(parents=True)
            (task_path / "context-pack" / "handoffs").mkdir(parents=True)
            subprocess.run(["git", "init"], cwd=root, text=True, capture_output=True, check=False)
            contract = {
                "phase": 0,
                "name": "demo",
                "read_first": {"docs": [], "previous_outputs": []},
                "scope": {
                    "layer": "docs",
                    "allowed_paths": ["tasks/demo/context-pack/handoffs/**", "tasks/demo/index.json"],
                },
                "interfaces": [],
                "decision_refs": [],
                "architecture_refs": [],
                "dependency_policy": {"new_dependencies": "forbidden"},
                "instructions": [
                    {
                        "id": "P0-001",
                        "task": "Write the handoff.",
                        "expected_evidence": ["context-pack/handoffs/phase0.md"],
                    }
                ],
                "success_criteria": ["The handoff exists."],
                "stop_rules": ["Stop if required context is missing."],
                "fallback_behavior": {"if_blocked": "Write the blocker to the handoff."},
                "validation_budget": {"max_attempts": 2, "command_timeout_seconds": 600},
                "missing_evidence_behavior": "Treat missing evidence as unresolved.",
                "acceptance_commands": ["true"],
                "required_outputs": ["context-pack/handoffs/phase0.md"],
            }
            (task_path / "phases" / "phase0.md").write_text(
                "# Phase 0: demo\n\n## Contract\n\n```json\n"
                + json.dumps(contract, indent=2)
                + "\n```\n",
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "project": "demo",
                        "task": "demo",
                        "docs": [],
                        "common_docs": [],
                        "phases": [{"phase": 0, "name": "demo", "status": "pending"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    sys.stdin.read()
                    from pathlib import Path
                    Path.cwd().joinpath("tasks/demo/context-pack/handoffs/phase0.md").write_text(
                        "# Handoff\\n\\n## Change Trace\\n\\n"
                        "- `tasks/demo/context-pack/handoffs/phase0.md`: `P0-001`\\n"
                        "- `tasks/demo/index.json`: `P0-001`\\n",
                        encoding="utf-8",
                    )
                    raise SystemExit(0)
                    """
                ),
            )
            args = argparse.Namespace(
                dry_run=False,
                max_attempts=3,
                ac_timeout=600,
                codex_bin=str(fake),
                full_auto=False,
                yolo=False,
                codex_idle_timeout=10,
                failed=False,
            )
            quality_results = [
                {
                    "status": "failed",
                    "checks": [{"name": "mock-quality", "status": "failed"}],
                    "blocking_reasons": ["mock quality failed"],
                },
                {"status": "passed", "checks": [], "blocking_reasons": []},
            ]

            with (
                mock.patch.object(RUN_PHASES, "verify_task", return_value=0),
                mock.patch.object(RUN_PHASES, "preflight_phase", return_value=[]),
                mock.patch.object(RUN_PHASES, "nested_codex_preflight_errors", return_value=[]),
                mock.patch.object(RUN_PHASES, "run_quality_checks", side_effect=quality_results),
            ):
                self.assertTrue(RUN_PHASES.execute_phase(root, task_path, args))

            result = json.loads(RUN_PHASES.phase_result_path(task_path, 0).read_text(encoding="utf-8"))
            commit = json.loads((task_path / result["artifacts"]["attempt_commit"]).read_text(encoding="utf-8"))
            self.assertEqual(result["attempt"], 2)
            self.assertEqual(result["artifacts"]["quality"], "context-pack/runtime/phase0-quality-attempt2.json")
            self.assertEqual(result["artifacts"]["evidence"], "context-pack/runtime/phase0-evidence-attempt2.json")
            self.assertEqual(result["artifacts"]["reconciliation"], "context-pack/runtime/phase0-reconciliation-attempt2.json")
            self.assertEqual(
                result["artifacts"]["reconciliation_summary"],
                "context-pack/runtime/phase0-reconciliation-attempt2.md",
            )
            self.assertEqual(result["artifacts"]["gate"], "context-pack/runtime/phase0-gate-attempt2.json")
            self.assertEqual(
                result["artifacts"]["repair_packet"],
                "context-pack/runtime/phase0-repair-packet-attempt1.json",
            )
            attempt1_gate = json.loads(
                RUN_PHASES.phase_attempt_gate_path(task_path, 0, 1).read_text(encoding="utf-8")
            )
            attempt2_gate = json.loads(
                RUN_PHASES.phase_attempt_gate_path(task_path, 0, 2).read_text(encoding="utf-8")
            )
            attempt1_repair = json.loads(
                RUN_PHASES.phase_attempt_repair_packet_path(task_path, 0, 1).read_text(encoding="utf-8")
            )
            self.assertEqual(attempt1_gate["status"], "failed")
            self.assertEqual(attempt2_gate["status"], "passed")
            self.assertEqual(attempt1_repair["failure"]["type"], "gate")
            repair_artifacts = {item["name"]: item for item in attempt1_repair["failed_attempt_artifacts"]}
            self.assertTrue(repair_artifacts["quality"]["exists"])
            self.assertTrue(repair_artifacts["evidence"]["exists"])
            self.assertTrue(repair_artifacts["gate"]["exists"])
            self.assertTrue(repair_artifacts["handoff"]["exists"])
            self.assertTrue(RUN_PHASES.phase_attempt_handoff_path(task_path, 0, 1).exists())
            self.assertTrue(RUN_PHASES.phase_attempt_evidence_path(task_path, 0, 1).exists())
            self.assertTrue(RUN_PHASES.phase_attempt_reconciliation_path(task_path, 0, 1).exists())
            self.assertTrue(RUN_PHASES.phase_attempt_reconciliation_summary_path(task_path, 0, 1).exists())
            self.assertTrue(RUN_PHASES.phase_attempt_quality_path(task_path, 0, 1).exists())
            manifest = self.read_attempt_manifest(task_path, 0)
            self.assertEqual(
                [item["record_type"] for item in manifest],
                ["attempt_started", "attempt_failed", "attempt_started", "attempt_committed"],
            )
            self.assertEqual(manifest[1]["failure"]["type"], "gate")
            self.assertTrue(manifest[1]["retryable"])
            self.assertEqual(manifest[3]["attempt"], 2)
            by_name = {item["name"]: item for item in commit["artifacts"]}
            self.assertEqual(
                by_name["gate"]["sha256"],
                RUN_PHASES.file_sha256(RUN_PHASES.phase_attempt_gate_path(task_path, 0, 2)),
            )

    def test_execute_phase_stops_retry_when_scope_cleanup_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root = tmp / "repo"
            task_path = root / "tasks" / "demo"
            (root / "scripts" / "harness").mkdir(parents=True)
            (task_path / "phases").mkdir(parents=True)
            (task_path / "context-pack" / "runtime").mkdir(parents=True)
            (task_path / "context-pack" / "handoffs").mkdir(parents=True)
            for static_file in RUN_PHASES.MANDATORY_STATIC_FILES:
                target = task_path / "context-pack" / "static" / static_file
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(self.static_content(static_file), encoding="utf-8")
            docs = []
            for index in range(5):
                doc_path = root / f"doc{index}.md"
                doc_path.write_text("doc\n", encoding="utf-8")
                docs.append(doc_path.name)
            quality_doc = root / "docs" / "harness" / "implementation-quality.md"
            quality_doc.parent.mkdir(parents=True, exist_ok=True)
            quality_doc.write_text("quality\n", encoding="utf-8")
            subprocess_result = subprocess.run(
                ["git", "init"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(subprocess_result.returncode, 0, subprocess_result.stderr)

            contract = {
                "phase": 0,
                "name": "demo",
                "read_first": {"docs": docs, "previous_outputs": []},
                "scope": {"layer": "docs", "allowed_paths": ["src"]},
                "interfaces": [],
                "decision_refs": ["D-001"],
                "architecture_refs": ["A-001"],
                "dependency_policy": {
                    "new_dependencies": "forbidden",
                    "approved_new_dependencies": [],
                    "approved_dependency_manifest_changes": [],
                },
                "instructions": [
                    {
                        "id": "P0-001",
                        "task": "Write the handoff.",
                        "expected_evidence": ["context-pack/handoffs/phase0.md"],
                    }
                ],
                "success_criteria": ["The handoff exists."],
                "stop_rules": ["Stop if required context is missing."],
                "fallback_behavior": {
                    "if_blocked": "Write the blocker to the handoff.",
                    "if_tests_fail": "Fix failures inside allowed_paths.",
                },
                "validation_budget": {
                    "max_attempts": 2,
                    "command_timeout_seconds": 600,
                },
                "missing_evidence_behavior": "Treat missing evidence as unresolved.",
                "acceptance_commands": ["true"],
                "required_outputs": ["context-pack/handoffs/phase0.md"],
                "forbidden": [
                    {
                        "rule": "Do not update task status.",
                        "reason": "The runner owns status.",
                    }
                ],
            }
            (task_path / "phases" / "phase0.md").write_text(
                "# Phase 0: demo\n\n## Contract\n\n```json\n"
                + json.dumps(contract, indent=2)
                + "\n```\n",
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "project": "demo",
                        "task": "demo",
                        "docs": docs,
                        "common_docs": ["docs/harness/implementation-quality.md"],
                        "phases": [{"phase": 0, "name": "demo", "status": "pending"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            attempt_counter = tmp / "attempts.txt"
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    f"""
                    sys.stdin.read()
                    from pathlib import Path
                    counter = Path({str(attempt_counter)!r})
                    count = int(counter.read_text(encoding="utf-8")) if counter.exists() else 0
                    counter.write_text(str(count + 1), encoding="utf-8")
                    Path.cwd().joinpath("tasks/demo/context-pack/handoffs/phase0.md").write_text(
                        "handoff\\n",
                        encoding="utf-8",
                    )
                    Path.cwd().joinpath("outside.txt").write_text("outside\\n", encoding="utf-8")
                    raise SystemExit(0)
                    """
                ),
            )
            args = argparse.Namespace(
                dry_run=False,
                max_attempts=3,
                ac_timeout=600,
                codex_bin=str(fake),
                full_auto=False,
                yolo=False,
                codex_idle_timeout=10,
                failed=False,
            )

            with mock.patch.object(RUN_PHASES, "verify_task", return_value=0):
                self.assertFalse(RUN_PHASES.execute_phase(root, task_path, args))
            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(task_index["phases"][0]["attempts"], 1)
            self.assertEqual(task_index["phases"][0]["status"], "error")
            self.assertEqual(attempt_counter.read_text(encoding="utf-8"), "1")
            repair_packet = json.loads(
                (task_path / "context-pack" / "runtime" / "phase0-repair-packet.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(repair_packet["failure"]["type"], "gate")
            self.assertFalse(repair_packet["failure"]["retryable"])
            self.assertEqual(repair_packet["contaminating_changes"], ["outside.txt"])
            self.assertIn("outside.txt", repair_packet["failure"]["message"])
            repair_artifacts = {item["name"]: item for item in repair_packet["failed_attempt_artifacts"]}
            self.assertTrue(repair_artifacts["handoff"]["exists"])
            self.assertTrue(RUN_PHASES.phase_attempt_handoff_path(task_path, 0, 1).exists())
            RUN_PHASES.clear_attempt_artifacts(task_path, 0)
            self.assertFalse(RUN_PHASES.phase_handoff_path(task_path, 0).exists())
            self.assertTrue(RUN_PHASES.phase_attempt_handoff_path(task_path, 0, 1).exists())
            manifest = self.read_attempt_manifest(task_path, 0)
            self.assertEqual([item["record_type"] for item in manifest], ["attempt_started", "attempt_failed"])
            self.assertEqual(manifest[1]["failure"]["type"], "gate")
            self.assertFalse(manifest[1]["retryable"])

    def test_execute_phase_marks_error_when_attempt_budget_already_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root = tmp / "repo"
            task_path = root / "tasks" / "demo"
            (root / "scripts" / "harness").mkdir(parents=True)
            (task_path / "phases").mkdir(parents=True)
            (task_path / "context-pack" / "runtime").mkdir(parents=True)
            (task_path / "context-pack" / "handoffs").mkdir(parents=True)
            for static_file in RUN_PHASES.MANDATORY_STATIC_FILES:
                target = task_path / "context-pack" / "static" / static_file
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(self.static_content(static_file), encoding="utf-8")
            docs = []
            for index in range(5):
                doc_path = root / f"doc{index}.md"
                doc_path.write_text("doc\n", encoding="utf-8")
                docs.append(doc_path.name)
            quality_doc = root / "docs" / "harness" / "implementation-quality.md"
            quality_doc.parent.mkdir(parents=True, exist_ok=True)
            quality_doc.write_text("quality\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=root, text=True, capture_output=True, check=False)

            contract = {
                "phase": 0,
                "name": "demo",
                "read_first": {"docs": docs, "previous_outputs": []},
                "scope": {"layer": "docs", "allowed_paths": ["src"]},
                "interfaces": [],
                "decision_refs": ["D-001"],
                "architecture_refs": ["A-001"],
                "dependency_policy": {
                    "new_dependencies": "forbidden",
                    "approved_new_dependencies": [],
                    "approved_dependency_manifest_changes": [],
                },
                "instructions": [
                    {
                        "id": "P0-001",
                        "task": "Write the handoff.",
                        "expected_evidence": ["context-pack/handoffs/phase0.md"],
                    }
                ],
                "success_criteria": ["The handoff exists."],
                "stop_rules": ["Stop if required context is missing."],
                "fallback_behavior": {
                    "if_blocked": "Write the blocker to the handoff.",
                    "if_tests_fail": "Fix failures inside allowed_paths.",
                },
                "validation_budget": {
                    "max_attempts": 1,
                    "command_timeout_seconds": 600,
                },
                "missing_evidence_behavior": "Treat missing evidence as unresolved.",
                "acceptance_commands": ["true"],
                "required_outputs": ["context-pack/handoffs/phase0.md"],
                "forbidden": [
                    {
                        "rule": "Do not update task status.",
                        "reason": "The runner owns status.",
                    }
                ],
            }
            (task_path / "phases" / "phase0.md").write_text(
                "# Phase 0: demo\n\n## Contract\n\n```json\n"
                + json.dumps(contract, indent=2)
                + "\n```\n",
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "project": "demo",
                        "task": "demo",
                        "docs": docs,
                        "common_docs": ["docs/harness/implementation-quality.md"],
                        "phases": [
                            {
                                "phase": 0,
                                "name": "demo",
                                "status": "running",
                                "attempts": 1,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                dry_run=False,
                max_attempts=3,
                ac_timeout=600,
                codex_bin=str(tmp / "unused-codex"),
                full_auto=False,
                yolo=False,
                codex_idle_timeout=10,
                failed=False,
            )

            with mock.patch.object(RUN_PHASES, "verify_task", return_value=0):
                self.assertFalse(RUN_PHASES.execute_phase(root, task_path, args))
            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            phase = task_index["phases"][0]
            self.assertEqual(phase["status"], "error")
            self.assertIn("attempt budget exhausted", phase["error_message"])
            self.assertIn(
                "attempt budget exhausted",
                (task_path / "context-pack" / "runtime" / "phase0-last-error.md").read_text(
                    encoding="utf-8"
                ),
            )


if __name__ == "__main__":
    unittest.main()
