#!/usr/bin/env python3
"""Regression tests for shared runtime protocol helpers."""

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
SPEC = importlib.util.spec_from_file_location("runtime_protocol", HARNESS_DIR / "runtime_protocol.py")
assert SPEC is not None
RUNTIME_PROTOCOL = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RUNTIME_PROTOCOL)


class RuntimeProtocolTest(unittest.TestCase):
    def test_phase_attempt_manifest_path_is_task_relative_protocol_path(self) -> None:
        task_path = Path("/repo/tasks/demo")

        self.assertEqual(
            RUNTIME_PROTOCOL.phase_attempt_manifest_path(task_path, 0),
            Path("/repo/tasks/demo/context-pack/runtime/phase0-attempt-manifest.jsonl"),
        )

    def test_artifact_ref_records_task_relative_hash_and_missing_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            task_path = Path(raw_tmp) / "repo" / "tasks" / "demo"
            artifact = task_path / "context-pack" / "runtime" / "phase0-result.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("result\n", encoding="utf-8")

            existing = RUNTIME_PROTOCOL.artifact_ref(task_path, "result", artifact)
            missing = RUNTIME_PROTOCOL.artifact_ref(task_path, "missing", artifact.parent / "missing.json")

            self.assertEqual(existing["path"], "context-pack/runtime/phase0-result.json")
            self.assertTrue(existing["exists"])
            self.assertEqual(existing["sha256"], RUNTIME_PROTOCOL.file_sha256(artifact))
            self.assertFalse(missing["exists"])
            self.assertNotIn("sha256", missing)

    def test_runtime_artifact_ref_rejects_task_escape_and_tampered_hash(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            task_path = Path(raw_tmp) / "repo" / "tasks" / "demo"
            artifact = task_path / "context-pack" / "runtime" / "phase0-result.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("result\n", encoding="utf-8")

            escape_errors = RUNTIME_PROTOCOL.runtime_artifact_ref_errors(
                task_path,
                {"name": "result", "path": "../outside.json", "exists": True},
                "result",
                expected_name="result",
            )
            tamper_errors = RUNTIME_PROTOCOL.runtime_artifact_ref_errors(
                task_path,
                {"name": "result", "path": "context-pack/runtime/phase0-result.json", "exists": True, "sha256": "bad"},
                "result",
                expected_name="result",
            )

            self.assertTrue(any("inside the task directory" in error for error in escape_errors), escape_errors)
            self.assertTrue(any("sha256 does not match" in error for error in tamper_errors), tamper_errors)

    def test_attempt_manifest_semantics_reject_duplicate_terminal_records(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            task_path = Path(raw_tmp) / "repo" / "tasks" / "demo"
            runtime = task_path / "context-pack" / "runtime"
            runtime.mkdir(parents=True)
            result = runtime / "phase0-result-attempt1.json"
            result.write_text("{}\n", encoding="utf-8")
            result_ref = RUNTIME_PROTOCOL.artifact_ref(task_path, "result", result)
            records = [
                {
                    "schema_version": 1,
                    "artifact_kind": "phase_attempt_manifest_record",
                    "record_type": "attempt_failed",
                    "phase": 0,
                    "attempt": 1,
                },
                {
                    "schema_version": 1,
                    "artifact_kind": "phase_attempt_manifest_record",
                    "record_type": "attempt_committed",
                    "phase": 0,
                    "attempt": 1,
                    "result": result_ref,
                },
            ]

            errors = RUNTIME_PROTOCOL.attempt_manifest_semantic_errors(task_path, 0, records)

            self.assertTrue(any("multiple terminal manifest records" in error for error in errors), errors)

    def test_attempt_manifest_semantics_require_terminal_payload_refs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            task_path = Path(raw_tmp) / "repo" / "tasks" / "demo"
            records = [
                {
                    "schema_version": 1,
                    "artifact_kind": "phase_attempt_manifest_record",
                    "record_type": "attempt_committed",
                    "phase": 0,
                    "attempt": 1,
                },
                {
                    "schema_version": 1,
                    "artifact_kind": "phase_attempt_manifest_record",
                    "record_type": "attempt_failed",
                    "phase": 0,
                    "attempt": 2,
                },
            ]

            errors = RUNTIME_PROTOCOL.attempt_manifest_semantic_errors(task_path, 0, records)

            self.assertTrue(any("result is required" in error for error in errors), errors)
            self.assertTrue(any("attempt_commit is required" in error for error in errors), errors)
            self.assertTrue(any("repair_packet is required" in error for error in errors), errors)
            self.assertTrue(any("repair_packet_summary is required" in error for error in errors), errors)

    def test_manifest_reader_reports_invalid_json_without_dropping_valid_records(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            task_path = Path(raw_tmp) / "repo" / "tasks" / "demo"
            path = RUNTIME_PROTOCOL.phase_attempt_manifest_path(task_path, 0)
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "artifact_kind": "phase_attempt_manifest_record",
                        "record_type": "attempt_started",
                        "phase": 0,
                        "attempt": 1,
                    }
                )
                + "\n{not-json}\n",
                encoding="utf-8",
            )

            records, errors = RUNTIME_PROTOCOL.read_attempt_manifest_records_with_errors(task_path, 0)

            self.assertEqual(len(records), 1)
            self.assertTrue(any("Invalid phase 0 attempt manifest JSON" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
