#!/usr/bin/env python3
"""Regression tests for compiled phase semantics."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))

import phase_semantics  # noqa: E402


class PhaseSemanticsTest(unittest.TestCase):
    def test_path_classification_table(self) -> None:
        cases = [
            (
                {
                    "scope": {
                        "layer": "tests",
                        "allowed_paths": ["tests/validate_x.py"],
                    },
                },
                {"validation_only": True, "writes_validator": True, "writes_product_code": False},
            ),
            (
                {
                    "scope": {
                        "layer": "ios",
                        "allowed_paths": ["SupApp/Tests/SupHomeViewTests.swift"],
                    },
                },
                {"validation_only": False, "writes_validator": True, "writes_product_code": False},
            ),
            (
                {
                    "scope": {
                        "layer": "ios",
                        "allowed_paths": ["SupApp/Sources/SupApp/SupHomeView.swift"],
                    },
                },
                {"validation_only": False, "writes_validator": False, "writes_product_code": True},
            ),
        ]
        for contract, expected in cases:
            with self.subTest(contract=contract):
                semantics = phase_semantics.analyze_phase(contract)
                self.assertEqual(semantics.validation_only, expected["validation_only"])
                self.assertEqual(semantics.writes_validator, expected["writes_validator"])
                self.assertEqual(semantics.writes_product_code, expected["writes_product_code"])

    def test_compile_phase_contract_normalizes_command_evidence_refs(self) -> None:
        contract = {
            "scope": {
                "layer": "validation",
                "allowed_paths": ["tests/validate_boundary.py"],
            },
            "acceptance_commands": [
                "python3 tests/validate_boundary.py --fixture tests/fixtures/boundary",
            ],
            "verification_evidence": {
                "reproduction": ["python3 tests/validate_boundary.py --repo-scan"],
            },
            "command_expectations": [
                {
                    "id": "boundary-reproduction",
                    "command": "python3 tests/validate_boundary.py --repo-scan",
                    "role": "reproduction",
                    "target": "tests/validate_boundary.py",
                    "repo_scan": True,
                },
                {
                    "id": "boundary-fixture",
                    "command": "python3 tests/validate_boundary.py --fixture tests/fixtures/boundary",
                    "role": "fixture",
                    "target": "tests/fixtures/boundary",
                    "repo_scan": False,
                },
            ],
        }

        phase_ir = phase_semantics.compile_phase_contract(contract)

        self.assertEqual(phase_ir.phase_kind, "validation")
        self.assertEqual(
            phase_ir.acceptance_evidence_refs,
            frozenset(
                {
                    "python3 tests/validate_boundary.py --fixture tests/fixtures/boundary",
                    "boundary-fixture",
                }
            ),
        )
        self.assertEqual(
            phase_ir.command_metadata_by_command[
                "python3 tests/validate_boundary.py --fixture tests/fixtures/boundary"
            ],
            {
                "id": "boundary-fixture",
                "role": "fixture",
                "target": "tests/fixtures/boundary",
                "repo_scan": False,
            },
        )

    def test_explicit_phase_kind_overrides_heuristic_layer(self) -> None:
        contract = {
            "phase_kind": "implementation",
            "scope": {
                "layer": "docs",
                "allowed_paths": ["docs/runner.md"],
            },
            "acceptance_commands": ["python3 -m unittest discover -s tests"],
        }

        semantics = phase_semantics.analyze_phase(contract)

        self.assertEqual(semantics.phase_kind, "implementation")
        self.assertTrue(semantics.writes_product_code)

    def test_explicit_validation_kind_requires_verification_evidence(self) -> None:
        contract = {
            "phase_kind": "validation",
            "name": "contract checks",
            "scope": {
                "layer": "qa",
                "allowed_paths": ["tests/validate_contract.py"],
            },
        }

        self.assertTrue(phase_semantics.contract_needs_verification_evidence(contract))

    def test_reproduction_only_command_id_does_not_close_acceptance_evidence(self) -> None:
        contract = {
            "scope": {
                "layer": "validation",
                "allowed_paths": ["tests/validate_boundary.py"],
            },
            "verification_evidence": {
                "reproduction": ["python3 tests/validate_boundary.py --repo-scan"],
            },
            "command_expectations": [
                {
                    "id": "boundary-reproduction",
                    "command": "python3 tests/validate_boundary.py --repo-scan",
                    "role": "reproduction",
                    "target": "tests/validate_boundary.py",
                    "repo_scan": True,
                }
            ],
        }

        phase_ir = phase_semantics.compile_phase_contract(contract)

        self.assertNotIn("boundary-reproduction", phase_ir.acceptance_evidence_refs)


if __name__ == "__main__":
    unittest.main()
