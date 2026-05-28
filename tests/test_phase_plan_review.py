#!/usr/bin/env python3
"""Regression tests for planned-state phase semantic review."""

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
SPEC = importlib.util.spec_from_file_location("phase_plan_review", HARNESS_DIR / "review-phase-plan.py")
assert SPEC is not None
PHASE_PLAN_REVIEW = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PHASE_PLAN_REVIEW)


class PhasePlanReviewTest(unittest.TestCase):
    def make_task(self, tmp: Path) -> tuple[Path, Path]:
        root = tmp / "repo"
        task_path = root / "tasks" / "demo"
        (task_path / "phases").mkdir(parents=True)
        (task_path / "docs").mkdir(parents=True)
        (task_path / "context-pack" / "static").mkdir(parents=True)
        design = task_path / "docs" / "implementation-design-review.md"
        design.write_text("# Implementation Design Review\n\nDesign approval status: approved.\n", encoding="utf-8")
        (task_path / "context-pack" / "static" / "design-approval.json").write_text(
            json.dumps(
                {
                    "approved": True,
                    "approved_doc": "tasks/demo/docs/implementation-design-review.md",
                    "approved_doc_sha256": "unused",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return root, task_path

    def write_phase(self, task_path: Path, number: int, contract: dict[str, object], body: str = "") -> None:
        (task_path / "phases" / f"phase{number}.md").write_text(
            f"# Phase {number}: demo\n\n## Contract\n\n```json\n"
            + json.dumps(contract, indent=2)
            + "\n```\n\n"
            + body,
            encoding="utf-8",
        )

    def base_contract(self, phase: int = 0) -> dict[str, object]:
        return {
            "phase": phase,
            "name": "docs",
            "scope": {"layer": "docs", "allowed_paths": ["tasks/demo/**"]},
            "instructions": [
                {
                    "id": f"P{phase}-001",
                    "task": "Write the handoff.",
                    "expected_evidence": [f"context-pack/handoffs/phase{phase}.md"],
                }
            ],
            "success_criteria": ["The handoff exists."],
            "acceptance_commands": ["true"],
            "required_outputs": [f"context-pack/handoffs/phase{phase}.md"],
            "required_repo_outputs": [],
        }

    def test_swift_phase_requires_xcodebuild_in_same_phase(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "ios repair"
            contract["scope"] = {
                "layer": "SupApp.NativePolish",
                "allowed_paths": ["SupApp/Sources/SupApp/NativePolish/SupHomeView.swift"],
            }
            contract["required_repo_outputs"] = ["SupApp/Sources/SupApp/NativePolish/SupHomeView.swift"]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("xcodebuild acceptance command" in error for error in errors), errors)

    def test_final_qa_xcodebuild_requires_previous_implementation_xcodebuild_phase(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "final verification"
            contract["scope"] = {"layer": "qa", "allowed_paths": ["tasks/demo/**"]}
            contract["acceptance_commands"] = [
                "xcodebuild -project App.xcodeproj -scheme App -configuration Debug build"
            ]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("xcodebuild first appears in a non-implementation phase" in error for error in errors), errors)

    def test_validator_phase_rejects_deferred_known_gap_enforcement(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "validator hardening"
            contract["scope"] = {"layer": "tests", "allowed_paths": ["tests/validate_demo.py"]}
            contract["required_repo_outputs"] = ["tests/validate_demo.py"]
            contract["instructions"] = [
                {
                    "id": "P0-001",
                    "task": "Prepare checks that Phase 1 can enforce for known app gaps instead of failing now.",
                    "expected_evidence": ["tests/validate_demo.py"],
                }
            ]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("defers enforcement of known gaps" in error for error in errors), errors)

    def test_validation_only_phase_rejects_validator_acceptance_without_separate_reproduction(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "validator hardening"
            contract["scope"] = {"layer": "tests", "allowed_paths": ["tests/validate_home_live_loader.py"]}
            contract["required_repo_outputs"] = ["tests/validate_home_live_loader.py"]
            contract["verification_evidence"] = {
                "reproduction": ["python3 tests/validate_home_live_loader.py"],
            }
            contract["acceptance_commands"] = ["python3 tests/validate_home_live_loader.py"]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("validation-only phase must separate" in error for error in errors), errors)

    def test_validation_only_phase_accepts_distinct_reproduction_and_meta_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "validator hardening"
            contract["scope"] = {"layer": "tests", "allowed_paths": ["tests/validate_home_live_loader.py"]}
            contract["required_repo_outputs"] = ["tests/validate_home_live_loader.py"]
            contract["verification_evidence"] = {
                "reproduction": ["python3 tests/validate_home_live_loader.py --repo-scan"],
            }
            contract["acceptance_commands"] = [
                "python3 tests/validate_home_live_loader.py --fixture tests/fixtures/home_live_loader"
            ]

            self.write_phase(task_path, 0, contract)

            self.assertEqual(PHASE_PLAN_REVIEW.review_phase_plan(root, task_path), [])

    def test_validation_only_phase_accepts_command_expectation_roles(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "validator hardening"
            contract["scope"] = {"layer": "tests", "allowed_paths": ["tests/validate_home_live_loader.py"]}
            contract["required_repo_outputs"] = ["tests/validate_home_live_loader.py"]
            contract["verification_evidence"] = {
                "reproduction": ["python3 tests/validate_home_live_loader.py"],
            }
            contract["acceptance_commands"] = [
                "python3 tests/validate_home_live_loader.py --fixture tests/fixtures/home_live_loader"
            ]
            contract["command_expectations"] = [
                {
                    "command": "python3 tests/validate_home_live_loader.py",
                    "role": "reproduction",
                    "target": "tests/validate_home_live_loader.py",
                    "repo_scan": True,
                },
                {
                    "command": "python3 tests/validate_home_live_loader.py --fixture tests/fixtures/home_live_loader",
                    "role": "fixture",
                    "target": "tests/fixtures/home_live_loader",
                    "repo_scan": False,
                },
            ]

            self.write_phase(task_path, 0, contract)

            self.assertEqual(PHASE_PLAN_REVIEW.review_phase_plan(root, task_path), [])

    def test_validation_only_phase_rejects_unlinked_fixture_expectation_role(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "validator hardening"
            contract["scope"] = {"layer": "tests", "allowed_paths": ["tests/validate_home_live_loader.py"]}
            contract["required_repo_outputs"] = ["tests/validate_home_live_loader.py"]
            contract["verification_evidence"] = {
                "reproduction": ["python3 tests/validate_home_live_loader.py"],
            }
            contract["acceptance_commands"] = ["python3 tests/validate_home_live_loader.py"]
            contract["command_expectations"] = [
                {
                    "command": "python3 tests/validate_home_live_loader.py",
                    "role": "reproduction",
                    "target": "tests/validate_home_live_loader.py",
                    "repo_scan": True,
                },
                {
                    "command": "python3 tests/validate_home_live_loader.py",
                    "role": "fixture",
                    "target": "tests/fixtures/home_live_loader",
                    "repo_scan": False,
                },
            ]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("validation-only phase must separate" in error for error in errors), errors)

    def test_validation_only_phase_rejects_same_validator_repo_scan_with_different_args(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "validator hardening"
            contract["scope"] = {"layer": "tests", "allowed_paths": ["tests/validate_home_live_loader.py"]}
            contract["required_repo_outputs"] = ["tests/validate_home_live_loader.py"]
            contract["verification_evidence"] = {
                "reproduction": ["python3 tests/validate_home_live_loader.py --repo-scan"],
            }
            contract["acceptance_commands"] = ["python3 tests/validate_home_live_loader.py"]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("validation-only phase must separate" in error for error in errors), errors)

    def test_validation_only_phase_rejects_generic_test_suite_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "validator hardening"
            contract["scope"] = {"layer": "tests", "allowed_paths": ["tests/validate_home_live_loader.py"]}
            contract["required_repo_outputs"] = ["tests/validate_home_live_loader.py"]
            contract["verification_evidence"] = {
                "reproduction": ["python3 tests/validate_home_live_loader.py"],
            }
            contract["acceptance_commands"] = ["pytest"]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("validation-only phase must separate" in error for error in errors), errors)

    def test_validation_only_phase_rejects_app_package_test_validator_without_product_scope(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "validator hardening"
            contract["scope"] = {
                "layer": "tests",
                "allowed_paths": ["SupApp/Tests/SupAppTests/HomeLiveLoaderTests.swift"],
            }
            contract["required_repo_outputs"] = ["SupApp/Tests/SupAppTests/HomeLiveLoaderTests.swift"]
            contract["verification_evidence"] = {
                "reproduction": [
                    "xcodebuild -project SupApp.xcodeproj -scheme SupAppTests test"
                ],
            }
            contract["acceptance_commands"] = [
                "xcodebuild -project SupApp.xcodeproj -scheme SupAppTests test"
            ]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("validation-only phase must separate" in error for error in errors), errors)

    def test_validation_only_phase_detects_validator_from_allowed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "validator hardening"
            contract["scope"] = {"layer": "tests", "allowed_paths": ["tests/validate_home_live_loader.py"]}
            contract["required_repo_outputs"] = []
            contract["verification_evidence"] = {
                "reproduction": ["python3 tests/validate_home_live_loader.py"],
            }
            contract["acceptance_commands"] = ["python3 tests/validate_home_live_loader.py"]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("validation-only phase must separate" in error for error in errors), errors)

    def test_validation_only_phase_allows_post_fix_acceptance_without_reproduction_scan(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "post-fix validation"
            contract["scope"] = {"layer": "tests", "allowed_paths": ["tests/validate_home_live_loader.py"]}
            contract["required_repo_outputs"] = ["tests/validate_home_live_loader.py"]
            contract["verification_evidence"] = {
                "fallback_reason": "The implementation fix is completed in an earlier phase.",
                "alternative_evidence": ["tests/validate_home_live_loader.py"],
            }
            contract["acceptance_commands"] = ["python3 tests/validate_home_live_loader.py"]

            self.write_phase(task_path, 0, contract)

            self.assertEqual(PHASE_PLAN_REVIEW.review_phase_plan(root, task_path), [])

    def test_combined_validator_and_implementation_phase_allows_validator_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "implementation with validator"
            contract["scope"] = {
                "layer": "SupApp",
                "allowed_paths": [
                    "tests/validate_home_live_loader.py",
                    "SupApp/Sources/SupApp/NativePolish/SupHomeView.swift",
                ],
            }
            contract["required_repo_outputs"] = [
                "tests/validate_home_live_loader.py",
                "SupApp/Sources/SupApp/NativePolish/SupHomeView.swift",
            ]
            contract["acceptance_commands"] = [
                "python3 tests/validate_home_live_loader.py",
                "xcodebuild -project App.xcodeproj -scheme App -configuration Debug build",
            ]

            self.write_phase(task_path, 0, contract)

            self.assertEqual(PHASE_PLAN_REVIEW.review_phase_plan(root, task_path), [])

    def test_implementation_phase_rejects_implement_or_prove_wording(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "ios lifecycle repair"
            contract["scope"] = {
                "layer": "SupApp",
                "allowed_paths": ["SupApp/Sources/SupApp/NativePolish/SupHomeView.swift"],
            }
            contract["required_repo_outputs"] = ["SupApp/Sources/SupApp/NativePolish/SupHomeView.swift"]
            contract["instructions"] = [
                {
                    "id": "P0-001",
                    "task": "Implement or prove backend-first selected presence fallback.",
                    "expected_evidence": ["SupApp/Sources/SupApp/NativePolish/SupHomeView.swift"],
                }
            ]
            contract["acceptance_commands"] = [
                "xcodebuild -project App.xcodeproj -scheme App -configuration Debug build"
            ]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("implement or prove" in error for error in errors), errors)

    def test_design_approval_text_must_not_remain_unapproved(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            (task_path / "docs" / "implementation-design-review.md").write_text(
                "# Implementation Design Review\n\nDesign approval status: not approved.\n",
                encoding="utf-8",
            )
            contract = self.base_contract()

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("still says design approval is not approved" in error for error in errors), errors)

    def test_valid_swift_then_qa_plan_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            phase0 = self.base_contract(0)
            phase0["name"] = "ios repair"
            phase0["scope"] = {
                "layer": "SupApp",
                "allowed_paths": ["SupApp/Sources/SupApp/NativePolish/SupHomeView.swift"],
            }
            phase0["required_repo_outputs"] = ["SupApp/Sources/SupApp/NativePolish/SupHomeView.swift"]
            phase0["acceptance_commands"] = [
                "xcodebuild -project App.xcodeproj -scheme App -configuration Debug build"
            ]
            phase1 = self.base_contract(1)
            phase1["name"] = "final verification"
            phase1["scope"] = {"layer": "qa", "allowed_paths": ["tasks/demo/**"]}
            phase1["acceptance_commands"] = [
                "xcodebuild -project App.xcodeproj -scheme App -configuration Debug build"
            ]

            self.write_phase(task_path, 0, phase0)
            self.write_phase(task_path, 1, phase1)

            self.assertEqual(PHASE_PLAN_REVIEW.review_phase_plan(root, task_path), [])

    def test_phase_files_are_sorted_by_numeric_phase(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            phase2 = self.base_contract(2)
            phase2["name"] = "ios repair"
            phase2["scope"] = {
                "layer": "SupApp",
                "allowed_paths": ["SupApp/Sources/SupApp/NativePolish/SupHomeView.swift"],
            }
            phase2["required_repo_outputs"] = ["SupApp/Sources/SupApp/NativePolish/SupHomeView.swift"]
            phase2["acceptance_commands"] = [
                "xcodebuild -project App.xcodeproj -scheme App -configuration Debug build"
            ]
            phase10 = self.base_contract(10)
            phase10["name"] = "final qa"
            phase10["scope"] = {"layer": "qa", "allowed_paths": ["tasks/demo/**"]}
            phase10["acceptance_commands"] = [
                "xcodebuild -project App.xcodeproj -scheme App -configuration Debug build"
            ]

            self.write_phase(task_path, 10, phase10)
            self.write_phase(task_path, 2, phase2)

            self.assertEqual(PHASE_PLAN_REVIEW.review_phase_plan(root, task_path), [])


if __name__ == "__main__":
    unittest.main()
