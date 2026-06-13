#!/usr/bin/env python3
"""Regression tests for main-session orchestration artifact protocol."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))
SPEC = importlib.util.spec_from_file_location("orchestration_protocol", HARNESS_DIR / "orchestration_protocol.py")
assert SPEC is not None
ORCHESTRATION_PROTOCOL = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ORCHESTRATION_PROTOCOL)

RUNTIME_SPEC = importlib.util.spec_from_file_location("runtime_protocol", HARNESS_DIR / "runtime_protocol.py")
assert RUNTIME_SPEC is not None
RUNTIME_PROTOCOL = importlib.util.module_from_spec(RUNTIME_SPEC)
assert RUNTIME_SPEC.loader is not None
RUNTIME_SPEC.loader.exec_module(RUNTIME_PROTOCOL)


class OrchestrationProtocolTest(unittest.TestCase):
    def make_task(self, raw_tmp: str) -> tuple[Path, Path]:
        task_path = Path(raw_tmp) / "repo" / "tasks" / "demo"
        docs = task_path / "docs"
        runtime = task_path / "context-pack" / "runtime"
        docs.mkdir(parents=True)
        runtime.mkdir(parents=True)
        (docs / "prd.md").write_text("# PRD\n", encoding="utf-8")
        (runtime / "verification-results.json").write_text('{"status":"passed"}\n', encoding="utf-8")
        return task_path, docs / "prd.md"

    def test_orchestration_journal_record_accepts_main_session_artifact_refs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            task_path, prd = self.make_task(raw_tmp)
            record = {
                "schema_version": 1,
                "artifact_kind": "orchestration_journal_record",
                "record_type": "artifact_updated",
                "actor": "main_session",
                "timestamp": "2026-06-03T00:00:00Z",
                "summary": "Recorded approved PRD update.",
                "input_artifacts": [RUNTIME_PROTOCOL.artifact_ref(task_path, "prd", prd)],
            }

            errors = ORCHESTRATION_PROTOCOL.orchestration_journal_record_errors(task_path, record)

            self.assertEqual(errors, [])

    def test_sub_thread_journal_record_requires_bounded_inquiry_context(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            task_path, _ = self.make_task(raw_tmp)
            record = {
                "schema_version": 1,
                "artifact_kind": "orchestration_journal_record",
                "record_type": "sub_thread_output_collected",
                "actor": "main_session",
                "timestamp": "2026-06-03T00:00:00Z",
                "summary": "Collected review finding.",
            }

            errors = ORCHESTRATION_PROTOCOL.orchestration_journal_record_errors(task_path, record)

            self.assertTrue(any("thread_id is required" in error for error in errors), errors)
            self.assertTrue(any("inquiry_type is required" in error for error in errors), errors)
            self.assertTrue(any("bounded_question is required" in error for error in errors), errors)
            self.assertTrue(any("scope_summary is required" in error for error in errors), errors)
            self.assertTrue(any("main_decision_ref is required" in error for error in errors), errors)

    def test_sub_thread_journal_record_accepts_bounded_inquiry_type(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            task_path, prd = self.make_task(raw_tmp)
            record = {
                "schema_version": 1,
                "artifact_kind": "orchestration_journal_record",
                "record_type": "sub_thread_output_collected",
                "actor": "main_session",
                "timestamp": "2026-06-03T00:00:00Z",
                "summary": "Collected skeptical risk notes.",
                "thread_id": "thread-123",
                "inquiry_type": "skeptical_risk_review",
                "bounded_question": "What are the main risks in the proposed storage contract?",
                "scope_summary": "Read only the approved PRD and summarize risks; do not propose implementation.",
                "main_decision_ref": "main:2026-06-03:bounded-risk-review",
                "input_artifacts": [RUNTIME_PROTOCOL.artifact_ref(task_path, "prd", prd)],
            }

            errors = ORCHESTRATION_PROTOCOL.orchestration_journal_record_errors(task_path, record)

            self.assertEqual(errors, [])

    def test_sub_thread_journal_record_rejects_role_like_inquiry_type(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            task_path, _ = self.make_task(raw_tmp)
            for inquiry_type in ["planner", "improver"]:
                with self.subTest(inquiry_type=inquiry_type):
                    record = {
                        "schema_version": 1,
                        "artifact_kind": "orchestration_journal_record",
                        "record_type": "sub_thread_opened",
                        "actor": "main_session",
                        "timestamp": "2026-06-03T00:00:00Z",
                        "summary": "Opened a bounded inquiry.",
                        "thread_id": "thread-123",
                        "inquiry_type": inquiry_type,
                        "bounded_question": "What is the risk?",
                        "scope_summary": "Answer only the question.",
                        "main_decision_ref": "main:2026-06-03:bounded-risk-review",
                    }

                    errors = ORCHESTRATION_PROTOCOL.orchestration_journal_record_errors(task_path, record)

                    self.assertTrue(any("not a persistent role" in error for error in errors), errors)

    def test_journal_record_rejects_thread_as_actor_and_escaped_artifact_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            task_path, _ = self.make_task(raw_tmp)
            record = {
                "schema_version": 1,
                "artifact_kind": "orchestration_journal_record",
                "record_type": "artifact_updated",
                "actor": "sub_thread",
                "timestamp": "2026-06-03T00:00:00Z",
                "summary": "Sub thread tried to update proof.",
                "output_artifacts": [{"name": "escape", "path": "../outside.json", "exists": True}],
            }

            errors = ORCHESTRATION_PROTOCOL.orchestration_journal_record_errors(task_path, record)

            self.assertTrue(any('actor must be "main_session"' in error for error in errors), errors)
            self.assertTrue(any("must stay inside the task directory" in error for error in errors), errors)

    def test_failure_state_record_accepts_blocked_state_with_artifact_refs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            task_path, prd = self.make_task(raw_tmp)
            record = {
                "schema_version": 1,
                "artifact_kind": "orchestration_failure_state",
                "status": "blocked",
                "observed_by": "main_session",
                "reason": "Open API decision is required.",
                "affected_scope": "task",
                "next_required_action": "Ask the user to choose the API behavior.",
                "input_artifacts": [RUNTIME_PROTOCOL.artifact_ref(task_path, "prd", prd)],
            }

            errors = ORCHESTRATION_PROTOCOL.failure_state_record_errors(task_path, record)

            self.assertEqual(errors, [])

    def test_interrupted_failure_state_cannot_promote_partial_output_to_proof(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            task_path, _ = self.make_task(raw_tmp)
            record = {
                "schema_version": 1,
                "artifact_kind": "orchestration_failure_state",
                "status": "interrupted",
                "observed_by": "main_session",
                "reason": "Thread timed out.",
                "affected_scope": "task",
                "next_required_action": "Re-run verifier before deciding status.",
                "partial_output_promoted_to_proof": True,
            }

            errors = ORCHESTRATION_PROTOCOL.failure_state_record_errors(task_path, record)

            self.assertTrue(any("partial_output_promoted_to_proof to false" in error for error in errors), errors)

    def test_journal_reader_keeps_valid_records_and_reports_invalid_lines(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            task_path, _ = self.make_task(raw_tmp)
            journal = task_path / "context-pack" / "runtime" / "orchestration-journal.jsonl"
            valid_record = {
                "schema_version": 1,
                "artifact_kind": "orchestration_journal_record",
                "record_type": "assumption_stated",
                "actor": "main_session",
                "timestamp": "2026-06-03T00:00:00Z",
                "summary": "Runner is not the execution engine.",
            }
            journal.write_text(json.dumps(valid_record) + "\n{not-json}\n[]\n", encoding="utf-8")

            records, errors = ORCHESTRATION_PROTOCOL.read_orchestration_journal_records_with_errors(
                task_path,
                journal,
            )

            self.assertEqual(records, [valid_record])
            self.assertTrue(any("Invalid orchestration journal JSON" in error for error in errors), errors)
            self.assertTrue(any("must be a JSON object" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
