#!/usr/bin/env python3
"""Tests for phase evidence obligation matching."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))

from evidence_obligations import (  # noqa: E402
    evidence_ref_matched,
    expected_evidence_gate_failures,
    instruction_evidence_matches,
)


class EvidenceObligationsTest(unittest.TestCase):
    def test_matches_command_id_required_output_repo_output_and_changed_file(self) -> None:
        evidence = {
            "commands": [
                {"command": "python3 -m unittest", "id": "unit-tests", "exit_code": 0},
                {"command": "false", "id": "failing-command", "exit_code": 1},
            ],
            "required_outputs": [
                {"path": "context-pack/handoffs/phase0.md", "exists": True},
            ],
            "required_repo_outputs": [
                {"path": "src/app.py", "exists": True},
            ],
            "changed_files": [
                "packages/api/src/service.py",
            ],
        }

        self.assertTrue(evidence_ref_matched("unit-tests", evidence))
        self.assertTrue(evidence_ref_matched("context-pack/handoffs/phase0.md", evidence))
        self.assertTrue(evidence_ref_matched("src/app.py", evidence))
        self.assertTrue(evidence_ref_matched("src/service.py", evidence))
        self.assertFalse(evidence_ref_matched("failing-command", evidence))

    def test_instruction_results_report_missing_expected_evidence(self) -> None:
        contract = {
            "instructions": [
                {
                    "id": "I-1",
                    "task": "Create service",
                    "expected_evidence": ["src/service.py", "unit-tests"],
                }
            ]
        }
        evidence = {
            "commands": [{"command": "python3 -m unittest", "id": "unit-tests", "exit_code": 0}],
            "required_outputs": [],
            "required_repo_outputs": [],
            "changed_files": [],
        }

        results = instruction_evidence_matches(contract, evidence)
        failures = expected_evidence_gate_failures(contract, evidence)

        self.assertEqual(results[0]["matched_expected_evidence"], ["unit-tests"])
        self.assertEqual(results[0]["missing_expected_evidence"], ["src/service.py"])
        self.assertEqual(failures, [{"id": "I-1", "missing_expected_evidence": ["src/service.py"]}])

    def test_typed_refs_only_match_their_declared_source(self) -> None:
        evidence = {
            "commands": [{"command": "python3 -m unittest", "id": "unit-tests", "exit_code": 0}],
            "required_outputs": [{"path": "context-pack/handoffs/phase0.md", "exists": True}],
            "required_repo_outputs": [{"path": "src/app.py", "exists": True}],
            "changed_files": ["src/changed.py"],
        }

        self.assertTrue(evidence_ref_matched({"type": "command", "ref": "unit-tests"}, evidence))
        self.assertTrue(
            evidence_ref_matched(
                {"type": "required_output", "ref": "context-pack/handoffs/phase0.md"},
                evidence,
            )
        )
        self.assertTrue(evidence_ref_matched({"type": "required_repo_output", "ref": "src/app.py"}, evidence))
        self.assertTrue(evidence_ref_matched({"type": "changed_file", "ref": "src/changed.py"}, evidence))
        self.assertFalse(evidence_ref_matched({"type": "command", "ref": "src/app.py"}, evidence))
        self.assertFalse(evidence_ref_matched({"type": "required_repo_output", "ref": "unit-tests"}, evidence))
        self.assertFalse(evidence_ref_matched({"type": "changed_file", "ref": "changed.py"}, evidence))
        self.assertTrue(evidence_ref_matched("changed.py", evidence))


if __name__ == "__main__":
    unittest.main()
