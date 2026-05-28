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
        (root / "docs" / "harness").mkdir(parents=True)
        (task_path / "docs").mkdir(parents=True)
        (task_path / "context-pack" / "handoffs").mkdir(parents=True)
        (root / "docs" / "runner.md").write_text("# Runner\n", encoding="utf-8")
        (root / "docs" / "harness" / "implementation-quality.md").write_text(
            "# Implementation Quality\n",
            encoding="utf-8",
        )
        (task_path / "docs" / "implementation-design-review.md").write_text(
            "# Implementation Design Review\n",
            encoding="utf-8",
        )
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
                "decision_refs",
                "architecture_refs",
                "dependency_policy",
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

    def test_glob_allowed_paths_match_nested_files(self) -> None:
        self.assertTrue(
            PHASE_CONTRACT.path_allowed(
                "apps/web/src/features/animations/useInvitationAnimations.ts",
                ["apps/web/src/**"],
            )
        )
        self.assertFalse(
            PHASE_CONTRACT.path_allowed(
                "apps/api/src/server.ts",
                ["apps/web/src/**"],
            )
        )

    def test_single_star_glob_does_not_cross_path_segments(self) -> None:
        self.assertTrue(
            PHASE_CONTRACT.path_allowed(
                "apps/web/package.json",
                ["apps/*/package.json"],
            )
        )
        self.assertFalse(
            PHASE_CONTRACT.path_allowed(
                "apps/web/src/package.json",
                ["apps/*/package.json"],
            )
        )

    def test_handoff_block_reasons_detect_blocked_status(self) -> None:
        reasons = PHASE_CONTRACT.handoff_block_reasons(
            "# Handoff\n\nStatus: blocked\n\nCould not implement backend files."
        )

        self.assertTrue(reasons)

    def test_handoff_change_trace_requires_changed_file_mapping(self) -> None:
        errors = PHASE_CONTRACT.handoff_change_trace_errors(
            "# Handoff\n\n## Change Trace\n\n- `src/app.py`: `P0-001`\n",
            ["src/app.py", "src/other.py"],
            ["P0-001"],
        )

        self.assertTrue(any("src/other.py" in error for error in errors), errors)

    def test_handoff_change_trace_rejects_unknown_instruction_ids(self) -> None:
        errors = PHASE_CONTRACT.handoff_change_trace_errors(
            "# Handoff\n\n## Change Trace\n\n- `src/app.py`: `P0-999`\n",
            ["src/app.py"],
            ["P0-001"],
        )

        self.assertTrue(any("unknown instruction" in error for error in errors), errors)

    def test_handoff_change_trace_accepts_known_instruction_ids(self) -> None:
        errors = PHASE_CONTRACT.handoff_change_trace_errors(
            "# Handoff\n\n## Change Trace\n\n- `src/app.py`: `P0-001`\n",
            ["src/app.py"],
            ["P0-001"],
        )

        self.assertEqual(errors, [])

    def test_bugfix_phase_requires_verification_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_context(Path(raw_tmp))
            contract = self.valid_contract()
            contract["name"] = "bugfix"
            contract["instructions"] = [
                {
                    "id": "P0-001",
                    "task": "Fix the reported regression.",
                    "expected_evidence": ["docs/runner.md"],
                }
            ]

            _, errors = PHASE_CONTRACT.validate_phase_contract(
                root,
                task_path,
                0,
                "bugfix",
                self.markdown(contract),
                require_previous_outputs=False,
            )

            self.assertTrue(any("verification_evidence" in error for error in errors), errors)

    def test_success_criteria_verification_word_does_not_force_verification_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_context(Path(raw_tmp))
            contract = self.valid_contract()
            contract["success_criteria"] = [
                "The behavior is verified by acceptance commands.",
                "정해진 범위의 동작이 확인 명령으로 검증된다.",
            ]

            _, errors = PHASE_CONTRACT.validate_phase_contract(
                root,
                task_path,
                0,
                "demo",
                self.markdown(contract),
                require_previous_outputs=False,
            )

            self.assertEqual(errors, [])

    def test_bugfix_phase_accepts_reproduction_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_context(Path(raw_tmp))
            contract = self.valid_contract()
            contract["name"] = "bugfix"
            contract["instructions"] = [
                {
                    "id": "P0-001",
                    "task": "Fix the reported regression.",
                    "expected_evidence": ["docs/runner.md"],
                }
            ]
            contract["verification_evidence"] = {
                "reproduction": ["python3 -m unittest tests.test_regression"],
            }
            contract["acceptance_commands"] = ["python3 -m unittest tests.test_regression"]

            _, errors = PHASE_CONTRACT.validate_phase_contract(
                root,
                task_path,
                0,
                "bugfix",
                self.markdown(contract),
                require_previous_outputs=False,
            )

            self.assertEqual(errors, [])

    def test_validation_phase_accepts_fallback_verification_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_context(Path(raw_tmp))
            contract = self.valid_contract()
            contract["name"] = "validation"
            contract["instructions"] = [
                {
                    "id": "P0-001",
                    "task": "Validate the migration behavior.",
                    "expected_evidence": ["docs/runner.md"],
                }
            ]
            contract["verification_evidence"] = {
                "fallback_reason": "The external service is not available in local tests.",
                "alternative_evidence": ["python3 scripts/check_migration_shape.py"],
            }
            contract["acceptance_commands"] = ["python3 scripts/check_migration_shape.py"]

            _, errors = PHASE_CONTRACT.validate_phase_contract(
                root,
                task_path,
                0,
                "validation",
                self.markdown(contract),
                require_previous_outputs=False,
            )

            self.assertEqual(errors, [])

    def test_bugfix_phase_accepts_reproduction_outside_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_context(Path(raw_tmp))
            contract = self.valid_contract()
            contract["name"] = "bugfix"
            contract["instructions"] = [
                {
                    "id": "P0-001",
                    "task": "Fix the reported regression.",
                    "expected_evidence": ["docs/runner.md"],
                }
            ]
            contract["verification_evidence"] = {
                "reproduction": ["python3 -m unittest tests.test_regression"],
            }

            _, errors = PHASE_CONTRACT.validate_phase_contract(
                root,
                task_path,
                0,
                "bugfix",
                self.markdown(contract),
                require_previous_outputs=False,
            )

            self.assertEqual(errors, [])

    def test_validation_phase_rejects_unlinked_alternative_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_context(Path(raw_tmp))
            contract = self.valid_contract()
            contract["name"] = "validation"
            contract["instructions"] = [
                {
                    "id": "P0-001",
                    "task": "Validate the migration behavior.",
                    "expected_evidence": ["docs/runner.md"],
                }
            ]
            contract["verification_evidence"] = {
                "fallback_reason": "The external service is not available in local tests.",
                "alternative_evidence": ["python3 scripts/check_migration_shape.py"],
            }

            _, errors = PHASE_CONTRACT.validate_phase_contract(
                root,
                task_path,
                0,
                "validation",
                self.markdown(contract),
                require_previous_outputs=False,
            )

            self.assertTrue(any("alternative_evidence" in error for error in errors), errors)

    def test_command_expectations_are_validated_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_context(Path(raw_tmp))
            contract = self.valid_contract()
            contract["name"] = "docs"
            contract["command_expectations"] = [
                {
                    "command": "python3 tests/validate_demo.py --repo-scan",
                    "role": "reproduction",
                    "target": "tests/validate_demo.py",
                    "repo_scan": True,
                },
                {
                    "command": "python3 tests/validate_demo.py --fixture tests/fixtures/demo",
                    "role": "fixture",
                    "target": "tests/fixtures/demo",
                    "repo_scan": False,
                },
            ]

            _, errors = PHASE_CONTRACT.validate_phase_contract(
                root,
                task_path,
                0,
                "docs",
                self.markdown(contract),
                require_previous_outputs=False,
            )

            self.assertEqual(errors, [])

            checklist = PHASE_CONTRACT.checklist_markdown(contract)
            self.assertIn("## Command Expectations", checklist)
            self.assertIn("reproduction:", checklist)

    def test_app_package_test_scope_is_not_treated_as_product_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_context(Path(raw_tmp))
            contract = self.valid_contract()
            contract["name"] = "validator hardening"
            contract["scope"] = {
                "layer": "SupApp",
                "allowed_paths": ["SupApp/Tests/SupAppTests/HomeLiveLoaderTests.swift"],
            }
            contract["read_first"] = {
                "docs": ["docs/runner.md"],
                "previous_outputs": [],
            }
            contract["interfaces"] = []
            contract["required_repo_outputs"] = [
                "SupApp/Tests/SupAppTests/HomeLiveLoaderTests.swift"
            ]
            contract["verification_evidence"] = {
                "reproduction": [
                    "xcodebuild -project SupApp.xcodeproj -scheme SupAppTests test"
                ]
            }

            _, errors = PHASE_CONTRACT.validate_phase_contract(
                root,
                task_path,
                0,
                "validator hardening",
                self.markdown(contract),
                require_previous_outputs=False,
            )

            self.assertFalse(any("interfaces" in error for error in errors), errors)
            self.assertFalse(any("implementation-quality" in error for error in errors), errors)

    def test_required_repo_outputs_are_validated_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_context(Path(raw_tmp))
            contract = self.valid_contract()
            contract["required_repo_outputs"] = ["docs/runner.md"]
            _, errors = PHASE_CONTRACT.validate_phase_contract(
                root,
                task_path,
                0,
                "demo",
                self.markdown(contract),
                require_previous_outputs=False,
            )
            self.assertEqual(errors, [])

    def test_required_repo_outputs_must_be_inside_allowed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_context(Path(raw_tmp))
            contract = self.valid_contract()
            contract["required_repo_outputs"] = ["src/server.ts"]
            _, errors = PHASE_CONTRACT.validate_phase_contract(
                root,
                task_path,
                0,
                "demo",
                self.markdown(contract),
                require_previous_outputs=False,
            )

            self.assertTrue(any("required_repo_outputs" in error for error in errors), errors)

    def test_implementation_phase_requires_quality_doc(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_context(Path(raw_tmp))
            contract = self.valid_contract()
            contract["scope"] = {
                "layer": "runner",
                "allowed_paths": ["docs/runner.md"],
            }
            contract["interfaces"] = [
                {
                    "path": "docs/runner.md",
                    "symbol": "RunnerDoc",
                    "signature": "Markdown document",
                    "business_rules": ["Implementation phases read quality guidance."],
                }
            ]
            contract["required_repo_outputs"] = ["docs/runner.md"]

            _, errors = PHASE_CONTRACT.validate_phase_contract(
                root,
                task_path,
                0,
                "demo",
                self.markdown(contract),
                require_previous_outputs=False,
            )

            self.assertTrue(any("implementation-quality.md" in error for error in errors), errors)

    def test_implementation_phase_requires_design_review_doc(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_context(Path(raw_tmp))
            contract = self.valid_contract()
            contract["read_first"] = {
                "docs": [
                    "docs/harness/implementation-quality.md",
                    "docs/runner.md",
                ],
                "previous_outputs": [],
            }
            contract["scope"] = {
                "layer": "runner",
                "allowed_paths": ["docs/runner.md"],
            }
            contract["interfaces"] = [
                {
                    "path": "docs/runner.md",
                    "symbol": "RunnerDoc",
                    "signature": "Markdown document",
                    "business_rules": ["Implementation phases read approved design."],
                }
            ]
            contract["required_repo_outputs"] = ["docs/runner.md"]

            _, errors = PHASE_CONTRACT.validate_phase_contract(
                root,
                task_path,
                0,
                "demo",
                self.markdown(contract),
                require_previous_outputs=False,
            )

            self.assertTrue(any("implementation design review" in error for error in errors), errors)

    def test_implementation_phase_accepts_design_review_doc(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_context(Path(raw_tmp))
            contract = self.valid_contract()
            contract["read_first"] = {
                "docs": [
                    "docs/harness/implementation-quality.md",
                    "tasks/demo/docs/implementation-design-review.md",
                    "docs/runner.md",
                ],
                "previous_outputs": [],
            }
            contract["scope"] = {
                "layer": "runner",
                "allowed_paths": ["docs/runner.md"],
            }
            contract["interfaces"] = [
                {
                    "path": "docs/runner.md",
                    "symbol": "RunnerDoc",
                    "signature": "Markdown document",
                    "business_rules": ["Implementation phases read approved design."],
                }
            ]
            contract["required_repo_outputs"] = ["docs/runner.md"]

            _, errors = PHASE_CONTRACT.validate_phase_contract(
                root,
                task_path,
                0,
                "demo",
                self.markdown(contract),
                require_previous_outputs=False,
            )

            self.assertEqual(errors, [])

    def test_implementation_phase_rejects_root_design_review_doc(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_context(Path(raw_tmp))
            root_review = root / "docs" / "implementation-design-review.md"
            root_review.write_text("# Root Design Review\n", encoding="utf-8")
            contract = self.valid_contract()
            contract["read_first"] = {
                "docs": [
                    "docs/harness/implementation-quality.md",
                    "docs/implementation-design-review.md",
                    "docs/runner.md",
                ],
                "previous_outputs": [],
            }
            contract["scope"] = {
                "layer": "runner",
                "allowed_paths": ["docs/runner.md"],
            }
            contract["interfaces"] = [
                {
                    "path": "docs/runner.md",
                    "symbol": "RunnerDoc",
                    "signature": "Markdown document",
                    "business_rules": ["Implementation phases read approved task design."],
                }
            ]
            contract["required_repo_outputs"] = ["docs/runner.md"]

            _, errors = PHASE_CONTRACT.validate_phase_contract(
                root,
                task_path,
                0,
                "demo",
                self.markdown(contract),
                require_previous_outputs=False,
            )

            self.assertTrue(any("implementation design review" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
