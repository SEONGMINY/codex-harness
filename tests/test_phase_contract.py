#!/usr/bin/env python3
"""Regression tests for phase contract validation."""

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
SPEC = importlib.util.spec_from_file_location("phase_contract", HARNESS_DIR / "phase_contract.py")
assert SPEC is not None
PHASE_CONTRACT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PHASE_CONTRACT)


class PhaseContractValidationTest(unittest.TestCase):
    def make_context(self, tmp: Path) -> tuple[Path, Path]:
        root = tmp / "repo"
        task_path = root / "tasks" / "demo"
        (root / "docs").mkdir(parents=True)
        (task_path / "context-pack" / "handoffs").mkdir(parents=True)
        (root / "docs" / "runner.md").write_text("# Runner\n", encoding="utf-8")
        return root, task_path

    def markdown(self, contract: dict[str, object]) -> str:
        return "# Phase 0: demo\n\n## Contract\n\n```json\n" + json.dumps(contract) + "\n```\n"

    def valid_contract(self) -> dict[str, object]:
        return {
            "phase": 0,
            "name": "demo",
            "read_first": {
                "docs": ["docs/runner.md"],
                "previous_outputs": [],
            },
            "scope": {
                "layer": "docs",
                "allowed_paths": ["docs/runner.md"],
            },
            "interfaces": [],
            "instructions": [
                {
                    "id": "P0-001",
                    "task": "Update the runner doc.",
                    "expected_evidence": ["docs/runner.md"],
                }
            ],
            "success_criteria": ["The runner doc records the changed contract fields."],
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
            "acceptance_commands": ["python3 -m py_compile scripts/harness/phase_contract.py"],
            "required_outputs": ["context-pack/handoffs/phase0.md"],
            "forbidden": [
                {
                    "rule": "Do not update task status.",
                    "reason": "The runner owns status.",
                }
            ],
        }

    def test_extended_contract_fields_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_context(Path(raw_tmp))
            contract = self.valid_contract()
            for field in [
                "success_criteria",
                "stop_rules",
                "fallback_behavior",
                "validation_budget",
                "missing_evidence_behavior",
            ]:
                broken = dict(contract)
                broken.pop(field)
                _, errors = PHASE_CONTRACT.validate_phase_contract(
                    root,
                    task_path,
                    0,
                    "demo",
                    self.markdown(broken),
                    require_previous_outputs=False,
                )
                self.assertTrue(any(field in error for error in errors), errors)

    def test_valid_extended_contract_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_context(Path(raw_tmp))
            _, errors = PHASE_CONTRACT.validate_phase_contract(
                root,
                task_path,
                0,
                "demo",
                self.markdown(self.valid_contract()),
                require_previous_outputs=False,
            )
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
