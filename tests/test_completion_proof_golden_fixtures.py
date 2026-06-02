#!/usr/bin/env python3
"""Golden fixtures for verifier completion proof regressions."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "completion_proofs"
sys.path.insert(0, str(HARNESS_DIR))
SPEC = importlib.util.spec_from_file_location("verify_task", HARNESS_DIR / "verify-task.py")
assert SPEC is not None
VERIFY_TASK = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VERIFY_TASK)


class CompletionProofGoldenFixtureTest(unittest.TestCase):
    def fixture_names(self) -> list[str]:
        return sorted(path.name for path in FIXTURE_DIR.iterdir() if path.is_dir())

    def load_fixture(self, fixture_name: str) -> dict[str, object]:
        fixture_path = FIXTURE_DIR / fixture_name / "fixture.json"
        return json.loads(fixture_path.read_text(encoding="utf-8"))

    def assert_valid_fixture_source(self, fixture_name: str, fixture: dict[str, object]) -> None:
        source = fixture.get("source") if isinstance(fixture.get("source"), dict) else {}
        assert isinstance(source, dict)
        source_type = source.get("type")
        self.assertIn(
            source_type,
            {"actual_session_failure", "derived_risk_regression"},
            f"{fixture_name} must classify fixture source",
        )
        self.assertIsInstance(source.get("session_id"), str, f"{fixture_name} must include source.session_id")
        self.assertIsInstance(source.get("session_line"), int, f"{fixture_name} must include source.session_line")
        self.assertIsInstance(source.get("observed_failure"), str, f"{fixture_name} must describe observed failure")
        if source_type == "actual_session_failure":
            self.assertIsInstance(source.get("artifact_path"), str, f"{fixture_name} must include artifact_path")
            self.assertIsInstance(source.get("observed_text"), str, f"{fixture_name} must include observed_text")
            self.assertIn("Completed manually", str(source.get("observed_text")))
        else:
            self.assertIsInstance(source.get("derived_from"), str, f"{fixture_name} must include derived_from")

    def assert_completion_diagnostic_schema(self, phase_report: dict[str, object]) -> None:
        self.assertIn("source_of_truth", phase_report)
        self.assertIn("evidence", phase_report)
        self.assertIn("gate", phase_report)
        self.assertIn("result", phase_report)
        self.assertIn("completion_proof", phase_report)
        self.assertIn("diagnostic_only", phase_report)
        consistency = phase_report.get("consistency")
        self.assertIsInstance(consistency, dict)
        assert isinstance(consistency, dict)
        for key in [
            "handoff_snapshot",
            "handoff_snapshot_vs_evidence",
            "handoff_snapshot_vs_gate",
            "result_vs_handoff_snapshot",
        ]:
            self.assertIn(key, consistency)
        failures = phase_report.get("failures")
        self.assertIsInstance(failures, list)
        assert isinstance(failures, list)
        for failure in failures:
            self.assertIsInstance(failure, dict)
            assert isinstance(failure, dict)
            for key in ["kind", "message", "phase", "attempt"]:
                self.assertIn(key, failure)

    def materialize_fixture(self, root: Path, fixture: dict[str, object]) -> Path:
        task_path = root / "tasks" / "demo"
        runtime_dir = task_path / "context-pack" / "runtime"
        handoff_dir = task_path / "context-pack" / "handoffs"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        handoff_dir.mkdir(parents=True, exist_ok=True)

        phase = int(fixture.get("phase", 0))
        attempt = int(fixture.get("attempt", 1))
        runtime = fixture.get("runtime") if isinstance(fixture.get("runtime"), dict) else {}
        assert isinstance(runtime, dict)

        (task_path / "index.json").write_text(
            json.dumps(
                {
                    "project": "demo",
                    "task": "demo",
                    "totalPhases": 1,
                    "phases": [{"phase": phase, "name": "demo", "status": "completed", "attempts": attempt}],
                }
            )
            + "\n",
            encoding="utf-8",
        )

        contract = {
            "phase": phase,
            "instructions": [],
            "scope": {"allowed_paths": []},
            "acceptance_commands": [],
            "required_outputs": [],
            "required_repo_outputs": [],
        }
        evidence = {
            "commands": [],
            "required_outputs": [],
            "required_repo_outputs": [],
            "changed_files": [],
        }
        if isinstance(runtime.get("evidence_handoff_state"), dict):
            evidence["handoff_state"] = runtime["evidence_handoff_state"]
        gate = {
            "status": "passed",
            "checks": runtime.get("gate_checks") if isinstance(runtime.get("gate_checks"), list) else [],
        }
        files = {
            f"phase{phase}-contract-attempt{attempt}.json": contract,
            f"phase{phase}-evidence-attempt{attempt}.json": evidence,
            f"phase{phase}-reconciliation-attempt{attempt}.json": {
                "status": "satisfied",
                "instruction_results": [],
            },
            f"phase{phase}-gate-attempt{attempt}.json": gate,
            f"phase{phase}-quality-attempt{attempt}.json": {"status": "passed", "checks": []},
            f"phase{phase}-result-attempt{attempt}.json": {
                "phase": phase,
                "attempt": attempt,
                "status": "completed",
                "codex_exit_code": 0,
            },
        }
        for filename, value in files.items():
            (runtime_dir / filename).write_text(json.dumps(value) + "\n", encoding="utf-8")

        snapshot = runtime.get("handoff_snapshot")
        if isinstance(snapshot, dict) and snapshot.get("exists") is not False:
            (runtime_dir / f"phase{phase}-handoff-attempt{attempt}.md").write_text(
                str(snapshot.get("text", "")),
                encoding="utf-8",
            )
        (handoff_dir / f"phase{phase}.md").write_text(
            str(runtime.get("handoff_alias_text", "Status: completed\n")),
            encoding="utf-8",
        )
        return task_path

    def test_completion_proof_golden_fixtures(self) -> None:
        self.assertGreaterEqual(len(self.fixture_names()), 3, "expected at least three completion fixtures")
        actual_failure_count = 0
        for fixture_name in self.fixture_names():
            with self.subTest(fixture=fixture_name):
                fixture = self.load_fixture(fixture_name)
                self.assert_valid_fixture_source(fixture_name, fixture)
                source = fixture.get("source") if isinstance(fixture.get("source"), dict) else {}
                if isinstance(source, dict) and source.get("type") == "actual_session_failure":
                    actual_failure_count += 1
                with tempfile.TemporaryDirectory() as raw_tmp:
                    root = Path(raw_tmp) / "repo"
                    task_path = self.materialize_fixture(root, fixture)

                    errors = VERIFY_TASK.validate_runtime_contract_bundle(
                        root,
                        task_path,
                        int(fixture.get("phase", 0)),
                        [],
                        [],
                        [],
                        expected_attempt=int(fixture.get("attempt", 1)),
                    )
                    diagnostics = VERIFY_TASK.build_completion_diagnostics(root, task_path, errors)

                expected = fixture.get("expected") if isinstance(fixture.get("expected"), dict) else {}
                assert isinstance(expected, dict)
                self.assertTrue(errors, "golden failure fixture must produce verifier errors")
                for needle in expected.get("errors_contain", []):
                    self.assertTrue(
                        any(str(needle) in error for error in errors),
                        f"missing expected error fragment {needle!r}; errors={errors!r}",
                    )
                failure_kinds = {
                    failure.get("kind")
                    for phase in diagnostics.get("phases", [])
                    if isinstance(phase, dict)
                    for failure in phase.get("failures", [])
                    if isinstance(failure, dict)
                }
                for kind in expected.get("failure_kinds", []):
                    self.assertIn(kind, failure_kinds)
                phase_reports = diagnostics.get("phases")
                self.assertIsInstance(phase_reports, list)
                assert isinstance(phase_reports, list)
                self.assertEqual(len(phase_reports), 1)
                self.assert_completion_diagnostic_schema(phase_reports[0])
        self.assertGreaterEqual(actual_failure_count, 3, "expected at least three actual session failure fixtures")

    def test_completion_diagnostics_report_can_be_written(self) -> None:
        fixture = json.loads(
            (
                FIXTURE_DIR
                / "stale_evidence_gate_blocks_hidden_partial"
                / "fixture.json"
            ).read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = self.materialize_fixture(root, fixture)
            errors = VERIFY_TASK.validate_runtime_contract_bundle(root, task_path, 0, [], [], [], expected_attempt=1)
            output_path = task_path / "context-pack" / "runtime" / "completion-diagnostics.json"

            VERIFY_TASK.write_completion_diagnostics(root, task_path, errors, output_path)

            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["phases"][0]["source_of_truth"]["exists"], True)
        self.assertIn("completion_proof", report["phases"][0])
        self.assertIn("diagnostic_only", report["phases"][0])
        self.assertIn("consistency", report["phases"][0])
        self.assert_completion_diagnostic_schema(report["phases"][0])
        failure_kinds = {item["kind"] for item in report["phases"][0]["failures"]}
        self.assertIn("blocking_handoff_snapshot", failure_kinds)

    def test_verify_cli_writes_completion_diagnostics_report(self) -> None:
        fixture = json.loads(
            (
                FIXTURE_DIR
                / "manual_completed_missing_snapshot"
                / "fixture.json"
            ).read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = self.materialize_fixture(root, fixture)
            output_path = root / "completion-diagnostics.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(HARNESS_DIR / "verify-task.py"),
                    str(task_path),
                    "--root",
                    str(root),
                    "--diagnostics-out",
                    str(output_path),
                ],
                check=False,
                text=True,
                capture_output=True,
            )

            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["schema_version"], 1)
        self.assert_completion_diagnostic_schema(report["phases"][0])
        self.assertEqual(report["phases"][0]["failures"][0]["kind"], "missing_handoff_snapshot")


if __name__ == "__main__":
    unittest.main()
