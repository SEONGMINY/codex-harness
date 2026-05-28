#!/usr/bin/env python3
"""Runtime tests for run-phases child Codex handling."""

from __future__ import annotations

import importlib.util
import argparse
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
                "obligation_ledger.py",
                "phase_contract.py",
                "phase_semantics.py",
                "policy_pack.py",
                "reference_resolver.py",
                "redaction.py",
                "run-phases.py",
                "verify-task.py",
                "run-quality-checks.py",
                "relationship_graph.py",
                "policy-packs/default-security.json",
                "schemas/phase-final.schema.json",
                "schemas/evaluation-final.schema.json",
            ]:
                (scripts / raw_path).parent.mkdir(parents=True, exist_ok=True)
                (scripts / raw_path).write_text("{}\n", encoding="utf-8")
            (scripts / "artifact_io.py").unlink()

            errors = RUN_PHASES.harness_install_errors(root)

        self.assertTrue(any("artifact_io.py" in error for error in errors), errors)

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
            self.assertEqual(commit["result"]["path"], "context-pack/runtime/phase0-result.json")
            self.assertEqual(commit["result"]["sha256"], RUN_PHASES.file_sha256(result_path))
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

            RUN_PHASES.apply_phase_reset(root, task_path, from_phase=0, dry_run=False)

            marker = json.loads(RUN_PHASES.phase_reset_marker_path(task_path, 0).read_text(encoding="utf-8"))
            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(marker["phase"], 0)
            self.assertEqual(marker["from_phase"], 0)
            self.assertEqual(task_index["phases"][0]["status"], "pending")
            self.assertEqual(task_index["phases"][0]["reset_at"], marker["reset_at"])

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
            )

            with (
                mock.patch.object(RUN_PHASES, "verify_task", return_value=1) as verify_task,
                mock.patch.object(RUN_PHASES, "nested_codex_preflight_errors", return_value=[]),
                mock.patch.object(RUN_PHASES, "preflight_phase", return_value=[]),
            ):
                self.assertFalse(RUN_PHASES.execute_phase(root, task_path, args))

            verify_task.assert_called_once_with(root, task_path, strict_current_harness=False)
            self.assertTrue(args.failed)
            last_error = (
                task_path / "context-pack" / "runtime" / "phase0-last-error.md"
            ).read_text(encoding="utf-8")
            self.assertIn("Task verification failed before phase execution.", last_error)

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

            class FakeResult:
                returncode = 0

            def fake_run(command, **kwargs):
                calls.append([str(item) for item in command])
                return FakeResult()

            args = argparse.Namespace(
                eval_command=["npm test"],
                full_auto=True,
                yolo=True,
            )

            try:
                RUN_PHASES.SCRIPT_DIR = installed_scripts
                with mock.patch.object(RUN_PHASES.subprocess, "run", side_effect=fake_run):
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
            self.assertTrue(repair_packet.exists())

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
