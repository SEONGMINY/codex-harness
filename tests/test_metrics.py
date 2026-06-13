#!/usr/bin/env python3
"""Regression tests for artifact-only metrics reporting."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))
SPEC = importlib.util.spec_from_file_location("harness_metrics", HARNESS_DIR / "metrics.py")
assert SPEC is not None
METRICS = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(METRICS)


class MetricsCollectorTest(unittest.TestCase):
    def make_task(self, root: Path, *, phase: bool = True) -> Path:
        task_path = root / "tasks" / "demo"
        (task_path / "phases").mkdir(parents=True)
        (task_path / "context-pack" / "runtime").mkdir(parents=True)
        (task_path / "context-pack" / "handoffs").mkdir(parents=True)
        (root / "tasks").mkdir(exist_ok=True)
        (root / "tasks" / "index.json").write_text(
            json.dumps({"tasks": [{"id": "demo", "status": "generated"}]}) + "\n",
            encoding="utf-8",
        )
        (task_path / "index.json").write_text(
            json.dumps({"id": "demo", "status": "generated", "phases": []}) + "\n",
            encoding="utf-8",
        )
        if phase:
            (task_path / "phases" / "phase0.md").write_text(
                "# Phase 0: docs\n\n"
                "## Contract\n\n"
                "```json\n"
                '{"phase":0,"name":"docs","scope":{"allowed_paths":["docs/**"]}}\n'
                "```\n",
                encoding="utf-8",
            )
        return task_path

    def write_completed_phase(
        self,
        task_path: Path,
        *,
        changed_files: list[str] | None = None,
        output_text: str = '{"type":"thread_final","message":"done"}\n',
        gate_status: str = "passed",
        scope_violations: list[str] | None = None,
        ac_exit_code: int = 0,
        repair_packet: bool = False,
    ) -> None:
        runtime = task_path / "context-pack" / "runtime"
        changed_files = changed_files or ["docs/a.md"]
        scope_violations = scope_violations or []
        (runtime / "phase0-attempt-manifest.jsonl").write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "schema_version": 1,
                            "artifact_kind": "phase_attempt_manifest_record",
                            "record_type": "attempt_started",
                            "phase": 0,
                            "attempt": 1,
                            "recorded_at": "2026-06-04T00:00:00+00:00",
                        }
                    ),
                    json.dumps(
                        {
                            "schema_version": 1,
                            "artifact_kind": "phase_attempt_manifest_record",
                            "record_type": "attempt_committed",
                            "phase": 0,
                            "attempt": 1,
                            "recorded_at": "2026-06-04T00:00:12+00:00",
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        result = {
            "schema_version": 1,
            "phase": 0,
            "attempt": 1,
            "status": "completed",
            "changed_files": changed_files,
            "commands_run": [{"command": "python3 -m unittest", "exit_code": ac_exit_code}],
            "required_outputs": [{"path": "context-pack/handoffs/phase0.md", "exists": True}],
            "required_repo_outputs": [{"path": "docs/a.md", "exists": True}],
        }
        for name in ["phase0-result.json", "phase0-result-attempt1.json"]:
            (runtime / name).write_text(json.dumps(result) + "\n", encoding="utf-8")
        gate = {
            "phase": 0,
            "status": gate_status,
            "checks": [
                {"name": "acceptance_commands", "status": "passed" if ac_exit_code == 0 else "failed"},
                {"name": "required_outputs", "status": "passed"},
                {"name": "required_repo_outputs", "status": "passed"},
                {"name": "handoff_status", "status": "passed"},
                {"name": "scope", "status": "failed" if scope_violations else "passed", "violations": scope_violations},
            ],
        }
        for name in ["phase0-gate.json", "phase0-gate-attempt1.json"]:
            (runtime / name).write_text(json.dumps(gate) + "\n", encoding="utf-8")
        evidence = {
            "phase": 0,
            "attempt": 1,
            "changed_files": changed_files,
            "required_outputs": [{"path": "context-pack/handoffs/phase0.md", "exists": True}],
            "required_repo_outputs": [{"path": "docs/a.md", "exists": True}],
        }
        for name in ["phase0-evidence.json", "phase0-evidence-attempt1.json"]:
            (runtime / name).write_text(json.dumps(evidence) + "\n", encoding="utf-8")
        (runtime / "phase0-ac-attempt1.json").write_text(
            json.dumps({"commands": [{"command": "python3 -m unittest", "exit_code": ac_exit_code}]}) + "\n",
            encoding="utf-8",
        )
        (runtime / "phase0-prompt-attempt1.md").write_text("prompt\n", encoding="utf-8")
        (runtime / "phase0-output-attempt1.jsonl").write_text(output_text, encoding="utf-8")
        (runtime / "phase0-stderr-attempt1.txt").write_text("stderr\n", encoding="utf-8")
        if repair_packet:
            (runtime / "phase0-repair-packet-attempt1.json").write_text(
                json.dumps({"failure": {"type": "gate", "retryable": True}}) + "\n",
                encoding="utf-8",
            )

    def test_empty_minimal_task_generates_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_path = self.make_task(root, phase=False)
            report = METRICS.generate_report(task_path, root)
            self.assertEqual(report["summary"]["phase_count"], 0)
            self.assertEqual(report["rollout_readiness"]["level_1_health"], "unknown")

    def test_completed_phase_summary_attempts_gate_ac_and_sizes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_path = self.make_task(root)
            self.write_completed_phase(task_path, repair_packet=True)
            report = METRICS.generate_report(task_path, root)
            phase = report["phases"][0]
            self.assertEqual(phase["phase_id"], 0)
            self.assertEqual(phase["phase_name"], "docs")
            self.assertEqual(phase["execution_mode"], "codex_thread")
            self.assertEqual(phase["attempt_count"], 1)
            self.assertEqual(phase["duration_seconds"], 12.0)
            self.assertEqual(phase["final_status"], "completed")
            self.assertEqual(phase["gate_status"], "passed")
            self.assertEqual(phase["acceptance_status"], "passed")
            self.assertEqual(phase["changed_file_count"], 1)
            self.assertEqual(phase["scope_violation_count"], 0)
            self.assertEqual(phase["repair_packet_count"], 1)
            self.assertGreater(phase["prompt_bytes"], 0)
            self.assertGreater(phase["output_bytes"], 0)
            self.assertGreater(phase["stderr_bytes"], 0)
            self.assertGreater(phase["artifact_bytes"], 0)
            summary = report["summary"]
            self.assertEqual(summary["completed_phase_count"], 1)
            self.assertEqual(summary["phase_completion_rate"], 1.0)
            self.assertEqual(summary["total_attempts"], 1)
            self.assertEqual(summary["retry_count"], 0)
            self.assertEqual(summary["repair_packet_count"], 1)
            self.assertEqual(summary["gate_pass_rate"], 1.0)
            self.assertEqual(summary["acceptance_pass_rate"], 1.0)

    def test_unknown_execution_mode_adds_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_path = self.make_task(root)
            self.write_completed_phase(task_path, output_text='{"type":"message","content":"done"}\n')
            report = METRICS.generate_report(task_path, root)
            self.assertEqual(report["phases"][0]["execution_mode"], "unknown")
            self.assertTrue(any("execution_mode is unknown" in item for item in report["warnings"]))

    def test_scope_violation_fails_level_1_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_path = self.make_task(root)
            self.write_completed_phase(
                task_path,
                changed_files=["docs/a.md", "outside.txt"],
                gate_status="failed",
                scope_violations=["outside.txt"],
            )
            report = METRICS.generate_report(task_path, root)
            self.assertEqual(report["summary"]["scope_violation_count"], 1)
            self.assertEqual(report["rollout_readiness"]["level_1_health"], "fail")
            self.assertIn("scope_violation_count", report["rollout_readiness"]["blockers"])

    def test_protected_path_write_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_path = self.make_task(root)
            self.write_completed_phase(
                task_path,
                changed_files=["tasks/demo/context-pack/runtime/phase0-result.json"],
            )
            report = METRICS.generate_report(task_path, root)
            self.assertTrue(report["phases"][0]["protected_path_write"])
            self.assertEqual(report["summary"]["protected_path_write_count"], 1)
            self.assertIn("protected_path_write_count", report["rollout_readiness"]["blockers"])

    def test_collector_writes_out_without_mutating_task_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_path = self.make_task(root)
            self.write_completed_phase(task_path)
            task_index = task_path / "index.json"
            result_path = task_path / "context-pack" / "runtime" / "phase0-result.json"
            before_index = task_index.read_text(encoding="utf-8")
            before_result = result_path.read_text(encoding="utf-8")
            cwd = Path.cwd()
            out = root / "report.json"
            try:
                os.chdir(root)
                exit_code = METRICS.main(["demo", "--out", str(out)])
            finally:
                os.chdir(cwd)
            self.assertEqual(exit_code, 0)
            self.assertTrue(out.exists())
            self.assertEqual(task_index.read_text(encoding="utf-8"), before_index)
            self.assertEqual(result_path.read_text(encoding="utf-8"), before_result)

    def test_collector_source_does_not_call_execution_or_verifier(self) -> None:
        source = (HARNESS_DIR / "metrics.py").read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("subprocess.", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn("run_phases", source)
        self.assertNotIn("verify_task", source)


if __name__ == "__main__":
    unittest.main()
