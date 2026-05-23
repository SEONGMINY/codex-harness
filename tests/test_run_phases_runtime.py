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


class RunCodexRuntimeTest(unittest.TestCase):
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

            verify_task.assert_called_once_with(root, task_path)
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
                    self.assertEqual(RUN_PHASES.run_evaluation(root, task_path, args), 0)
            finally:
                RUN_PHASES.SCRIPT_DIR = original_script_dir

            self.assertEqual(calls[0][1], str(installed_scripts / "verify-task.py"))
            self.assertEqual(calls[1][1], str(installed_scripts / "verify-task.py"))
            self.assertIn("--require-design-approval", calls[0])
            self.assertIn("--require-design-approval", calls[1])
            self.assertIn("--require-evaluation", calls[1])
            self.assertEqual(calls[2][1], str(installed_scripts / "evaluate-task.py"))
            self.assertIn("--command", calls[2])
            self.assertIn("npm test", calls[2])
            self.assertIn("--full-auto", calls[2])
            self.assertIn("--yolo", calls[2])

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
