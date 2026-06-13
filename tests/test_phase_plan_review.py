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
        (task_path / "context-pack" / "static" / "design-contract.json").write_text(
            json.dumps({"schema_version": "1", "obligations": []}, indent=2) + "\n",
            encoding="utf-8",
        )
        (task_path / "context-pack" / "static" / "traceability-matrix.json").write_text(
            json.dumps({"entries": []}, indent=2) + "\n",
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

    def write_design_contract(self, task_path: Path, obligations: list[dict[str, object]]) -> None:
        (task_path / "context-pack" / "static" / "design-contract.json").write_text(
            json.dumps({"schema_version": "1", "obligations": obligations}, indent=2) + "\n",
            encoding="utf-8",
        )

    def write_traceability_matrix(self, task_path: Path, entries: list[dict[str, object]]) -> None:
        (task_path / "context-pack" / "static" / "traceability-matrix.json").write_text(
            json.dumps({"entries": entries}, indent=2) + "\n",
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

    def test_docs_review_gate_obligation_requires_same_phase_acceptance_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            self.write_design_contract(
                task_path,
                [
                    {
                        "id": "OB-001",
                        "class": "acceptance_validity",
                        "summary": "Non-clean docs review status blocks verifier and runner gates.",
                        "closure_command_refs": [
                            "CMD-VERIFY-DOCS-REVIEW-STATUS",
                            "CMD-RUNNER-PREFLIGHT-DOCS-REVIEW-STATUS",
                        ],
                    }
                ],
            )
            contract = self.base_contract()
            contract["closes_obligations"] = ["OB-001"]
            contract["command_expectations"] = [
                {
                    "id": "CMD-VERIFY-DOCS-REVIEW-STATUS",
                    "command": "python3 -m unittest tests.test_verify_task",
                    "role": "acceptance",
                }
            ]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(
                any("CMD-RUNNER-PREFLIGHT-DOCS-REVIEW-STATUS" in error for error in errors),
                errors,
            )

    def test_docs_review_gate_obligation_accepts_verify_and_runner_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            self.write_design_contract(
                task_path,
                [
                    {
                        "id": "OB-001",
                        "class": "acceptance_validity",
                        "summary": "Non-clean docs review status blocks verifier and runner gates.",
                        "closure_command_refs": [
                            "CMD-VERIFY-DOCS-REVIEW-STATUS",
                            "CMD-RUNNER-PREFLIGHT-DOCS-REVIEW-STATUS",
                        ],
                    }
                ],
            )
            contract = self.base_contract()
            contract["closes_obligations"] = ["OB-001"]
            contract["command_expectations"] = [
                {
                    "id": "CMD-VERIFY-DOCS-REVIEW-STATUS",
                    "command": "python3 -m unittest tests.test_verify_task",
                    "role": "acceptance",
                },
                {
                    "id": "CMD-RUNNER-PREFLIGHT-DOCS-REVIEW-STATUS",
                    "command": "python3 -m unittest tests.test_run_phases_runtime",
                    "role": "acceptance",
                },
            ]

            self.write_phase(task_path, 0, contract)

            self.assertEqual(PHASE_PLAN_REVIEW.review_phase_plan(root, task_path), [])

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

    def test_missing_static_design_contract_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            (task_path / "context-pack" / "static" / "design-contract.json").unlink()
            contract = self.base_contract()

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("Missing design-contract.json" in error for error in errors), errors)

    def test_invalid_static_traceability_matrix_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            (task_path / "context-pack" / "static" / "traceability-matrix.json").write_text(
                "{not-json",
                encoding="utf-8",
            )
            contract = self.base_contract()

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("Invalid traceability-matrix.json JSON" in error for error in errors), errors)

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
                    "id": "home-loader-reproduction",
                    "command": "python3 tests/validate_home_live_loader.py",
                    "role": "reproduction",
                    "target": "tests/validate_home_live_loader.py",
                    "repo_scan": True,
                },
                {
                    "id": "home-loader-fixture",
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
                    "id": "home-loader-reproduction",
                    "command": "python3 tests/validate_home_live_loader.py",
                    "role": "reproduction",
                    "target": "tests/validate_home_live_loader.py",
                    "repo_scan": True,
                },
                {
                    "id": "home-loader-fixture",
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

    def test_risk_ledger_requires_same_phase_acceptance_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "runtime bridge"
            contract["scope"] = {
                "layer": "SupApp.Runtime",
                "allowed_paths": ["SupApp/Sources/SupApp/AppEnvironment.swift"],
            }
            contract["required_repo_outputs"] = ["SupApp/Sources/SupApp/AppEnvironment.swift"]
            contract["acceptance_commands"] = ["xcodebuild -project App.xcodeproj -scheme App build"]
            contract["risk_ledger"] = [
                {
                    "id": "R-boundary",
                    "class": "secret_sdk_boundary",
                    "action": "introduces",
                    "required_evidence": ["python3 tests/validate_ios_boundaries.py"],
                }
            ]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("required_evidence" in error for error in errors), errors)

    def test_risk_ledger_accepts_same_phase_acceptance_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            self.write_design_contract(
                task_path,
                [
                    {
                        "id": "obl.boundary",
                        "class": "secret_sdk_boundary",
                        "trigger": "Runtime bridge boundary changes.",
                        "closure_condition": "Boundary validator passes.",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["python3 tests/validate_ios_boundaries.py"],
                    }
                ],
            )
            contract = self.base_contract()
            contract["name"] = "runtime bridge"
            contract["scope"] = {
                "layer": "SupApp.Runtime",
                "allowed_paths": ["SupApp/Sources/SupApp/AppEnvironment.swift"],
            }
            contract["required_repo_outputs"] = ["SupApp/Sources/SupApp/AppEnvironment.swift"]
            contract["acceptance_commands"] = [
                "python3 tests/validate_ios_boundaries.py",
                "xcodebuild -project App.xcodeproj -scheme App build",
            ]
            contract["risk_ledger"] = [
                {
                    "id": "R-boundary",
                    "class": "secret_sdk_boundary",
                    "action": "introduces",
                    "required_evidence": ["python3 tests/validate_ios_boundaries.py"],
                }
            ]
            contract["closes_obligations"] = ["obl.boundary"]

            self.write_phase(task_path, 0, contract)

            self.assertEqual(PHASE_PLAN_REVIEW.review_phase_plan(root, task_path), [])

    def test_risk_ledger_accepts_same_phase_command_expectation_id(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            self.write_design_contract(
                task_path,
                [
                    {
                        "id": "obl.boundary",
                        "class": "secret_sdk_boundary",
                        "trigger": "Bridge boundary changes.",
                        "closure_condition": "Boundary validator passes.",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["ios-boundary-validator"],
                    }
                ],
            )
            contract = self.base_contract()
            contract["name"] = "boundary repair"
            contract["scope"] = {
                "layer": "SupApp.Bridge",
                "allowed_paths": ["SupApp/Sources/SupApp/Bridge/SupabaseBridge.swift"],
            }
            contract["required_repo_outputs"] = ["SupApp/Sources/SupApp/Bridge/SupabaseBridge.swift"]
            contract["interfaces"] = [
                {
                    "path": "SupApp/Sources/SupApp/Bridge/SupabaseBridge.swift",
                    "symbol": "SupabaseBridge",
                    "signature": "public struct SupabaseBridge {}",
                    "business_rules": ["No SDK secret crosses the app boundary."],
                }
            ]
            contract["acceptance_commands"] = [
                "python3 tests/validate_ios_boundaries.py",
                "xcodebuild -project SupApp.xcodeproj -scheme SupApp -configuration Debug build",
            ]
            contract["command_expectations"] = [
                {
                    "id": "ios-boundary-validator",
                    "command": "python3 tests/validate_ios_boundaries.py",
                    "role": "acceptance",
                    "target": "tests/validate_ios_boundaries.py",
                }
            ]
            contract["risk_ledger"] = [
                {
                    "id": "R0-001",
                    "class": "secret_sdk_boundary",
                    "action": "modifies",
                    "required_evidence": ["ios-boundary-validator"],
                    "rationale": "Bridge boundary changes must be validated in this phase.",
                }
            ]
            contract["closes_obligations"] = ["obl.boundary"]

            self.write_phase(task_path, 0, contract)

            self.assertEqual(PHASE_PLAN_REVIEW.review_phase_plan(root, task_path), [])

    def test_risk_ledger_rejects_reproduction_only_command_expectation_id(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "boundary validator"
            contract["scope"] = {"layer": "tests", "allowed_paths": ["tests/validate_ios_boundaries.py"]}
            contract["required_repo_outputs"] = ["tests/validate_ios_boundaries.py"]
            contract["verification_evidence"] = {
                "reproduction": ["python3 tests/validate_ios_boundaries.py --repo-scan"],
            }
            contract["acceptance_commands"] = [
                "python3 tests/validate_ios_boundaries.py --fixture tests/fixtures/ios_boundaries"
            ]
            contract["command_expectations"] = [
                {
                    "id": "ios-boundary-reproduction",
                    "command": "python3 tests/validate_ios_boundaries.py --repo-scan",
                    "role": "reproduction",
                    "target": "tests/validate_ios_boundaries.py",
                    "repo_scan": True,
                }
            ]
            contract["risk_ledger"] = [
                {
                    "id": "R0-001",
                    "class": "secret_sdk_boundary",
                    "action": "verifies",
                    "required_evidence": ["ios-boundary-reproduction"],
                    "rationale": "Reproduction-only commands must not close acceptance evidence.",
                }
            ]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("required_evidence is not covered" in error for error in errors), errors)

    def test_risk_ledger_rejects_partial_command_match(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["acceptance_commands"] = ["pytest"]
            contract["risk_ledger"] = [
                {
                    "id": "R0-001",
                    "class": "acceptance_validity",
                    "action": "verifies",
                    "required_evidence": ["pytest tests/test_specific.py"],
                    "rationale": "Specific evidence cannot be closed by a broader substring match.",
                }
            ]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("required_evidence is not covered" in error for error in errors), errors)

    def test_design_obligation_closure_requires_same_phase_acceptance_ref(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            self.write_design_contract(
                task_path,
                [
                    {
                        "id": "obl.boundary",
                        "class": "secret_sdk_boundary",
                        "trigger": "Bridge boundary changes.",
                        "closure_condition": "Boundary validator passes.",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["ios-boundary-validator"],
                    }
                ],
            )
            contract = self.base_contract()
            contract["acceptance_commands"] = ["xcodebuild -project App.xcodeproj -scheme App build"]
            contract["closes_obligations"] = ["obl.boundary"]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("closure_command_refs" in error for error in errors), errors)

    def test_design_obligation_closure_requires_available_design_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["closes_obligations"] = ["obl.boundary"]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("design-contract obligations are unavailable" in error for error in errors), errors)

    def test_design_obligation_closure_roles_are_scoped_to_closure_refs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            self.write_design_contract(
                task_path,
                [
                    {
                        "id": "obl.boundary",
                        "class": "secret_sdk_boundary",
                        "trigger": "Bridge boundary changes.",
                        "closure_condition": "Boundary validator passes.",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["boundary-fixture"],
                    }
                ],
            )
            contract = self.base_contract()
            contract["acceptance_commands"] = [
                "python3 tests/validate_boundary.py --fixture tests/fixtures/boundary",
                "xcodebuild -project App.xcodeproj -scheme App build",
            ]
            contract["command_expectations"] = [
                {
                    "id": "boundary-fixture",
                    "command": "python3 tests/validate_boundary.py --fixture tests/fixtures/boundary",
                    "role": "fixture",
                    "target": "tests/fixtures/boundary",
                    "repo_scan": False,
                }
            ]
            contract["closes_obligations"] = ["obl.boundary"]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("required roles" in error for error in errors), errors)

    def test_design_obligation_closure_rejects_reproduction_only_ref(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            self.write_design_contract(
                task_path,
                [
                    {
                        "id": "obl.boundary",
                        "class": "secret_sdk_boundary",
                        "trigger": "Bridge boundary changes.",
                        "closure_condition": "Boundary reproduction exists.",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["ios-boundary-reproduction"],
                    }
                ],
            )
            contract = self.base_contract()
            contract["verification_evidence"] = {
                "reproduction": ["python3 tests/validate_ios_boundaries.py --repo-scan"],
            }
            contract["acceptance_commands"] = [
                "python3 tests/validate_ios_boundaries.py --fixture tests/fixtures/ios_boundaries"
            ]
            contract["command_expectations"] = [
                {
                    "id": "ios-boundary-reproduction",
                    "command": "python3 tests/validate_ios_boundaries.py --repo-scan",
                    "role": "reproduction",
                    "target": "tests/validate_ios_boundaries.py",
                    "repo_scan": True,
                }
            ]
            contract["closes_obligations"] = ["obl.boundary"]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("closure_command_refs" in error for error in errors), errors)

    def test_design_obligation_closure_accepts_same_phase_command_expectation_id(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            self.write_design_contract(
                task_path,
                [
                    {
                        "id": "obl.boundary",
                        "class": "secret_sdk_boundary",
                        "trigger": "Bridge boundary changes.",
                        "closure_condition": "Boundary validator passes.",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["ios-boundary-validator"],
                    }
                ],
            )
            contract = self.base_contract()
            contract["acceptance_commands"] = ["python3 tests/validate_ios_boundaries.py"]
            contract["command_expectations"] = [
                {
                    "id": "ios-boundary-validator",
                    "command": "python3 tests/validate_ios_boundaries.py",
                    "role": "acceptance",
                    "target": "tests/validate_ios_boundaries.py",
                }
            ]
            contract["closes_obligations"] = ["obl.boundary"]

            self.write_phase(task_path, 0, contract)

            self.assertEqual(PHASE_PLAN_REVIEW.review_phase_plan(root, task_path), [])

    def test_traceability_assigned_obligation_must_be_closed_by_same_phase(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            self.write_design_contract(
                task_path,
                [
                    {
                        "id": "obl.boundary",
                        "class": "secret_sdk_boundary",
                        "trigger": "Bridge boundary changes.",
                        "closure_condition": "Boundary validator passes.",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["ios-boundary-validator"],
                    }
                ],
            )
            self.write_traceability_matrix(
                task_path,
                [
                    {
                        "phase": 0,
                        "design_ref": "obl.boundary",
                        "files": ["SupApp/Sources/SupApp/Bridge.swift"],
                        "evidence": ["obligation:obl.boundary"],
                    }
                ],
            )
            contract = self.base_contract()
            contract["acceptance_commands"] = ["python3 tests/validate_ios_boundaries.py"]
            contract["command_expectations"] = [
                {
                    "id": "ios-boundary-validator",
                    "command": "python3 tests/validate_ios_boundaries.py",
                    "role": "acceptance",
                    "target": "tests/validate_ios_boundaries.py",
                }
            ]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("traceability-matrix assigns obligation" in error for error in errors), errors)

    def test_traceability_assigned_obligation_accepts_same_phase_closure(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            self.write_design_contract(
                task_path,
                [
                    {
                        "id": "obl.boundary",
                        "class": "secret_sdk_boundary",
                        "trigger": "Bridge boundary changes.",
                        "closure_condition": "Boundary validator passes.",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["ios-boundary-validator"],
                    }
                ],
            )
            self.write_traceability_matrix(
                task_path,
                [
                    {
                        "phase": 0,
                        "design_ref": "obl.boundary",
                        "files": ["SupApp/Sources/SupApp/Bridge.swift"],
                        "evidence": ["obligation:obl.boundary"],
                    }
                ],
            )
            contract = self.base_contract()
            contract["acceptance_commands"] = ["python3 tests/validate_ios_boundaries.py"]
            contract["command_expectations"] = [
                {
                    "id": "ios-boundary-validator",
                    "command": "python3 tests/validate_ios_boundaries.py",
                    "role": "acceptance",
                    "target": "tests/validate_ios_boundaries.py",
                }
            ]
            contract["closes_obligations"] = ["obl.boundary"]

            self.write_phase(task_path, 0, contract)

            self.assertEqual(PHASE_PLAN_REVIEW.review_phase_plan(root, task_path), [])

    def test_public_interface_rejects_internal_protocol_exposure(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "runtime bridge"
            contract["scope"] = {
                "layer": "SupApp.Runtime",
                "allowed_paths": ["SupApp/Sources/SupApp/AppEnvironment.swift"],
            }
            contract["required_repo_outputs"] = ["SupApp/Sources/SupApp/AppEnvironment.swift"]
            contract["interfaces"] = [
                {
                    "path": "SupApp/Sources/SupApp/AppEnvironment.swift",
                    "symbol": "AppEnvironment.activityTokenPendingSyncer",
                    "signature": "public let activityTokenPendingSyncer: ActivityTokenPendingSyncing?",
                    "business_rules": ["Expose syncer intentionally."],
                },
                {
                    "path": "SupApp/Sources/SupApp/ActivityTokenPendingSync.swift",
                    "symbol": "ActivityTokenPendingSyncing",
                    "signature": "protocol ActivityTokenPendingSyncing { func sync() async }",
                    "business_rules": ["Local protocol."],
                },
            ]
            contract["acceptance_commands"] = ["xcodebuild -project App.xcodeproj -scheme App build"]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("public interface exposes" in error for error in errors), errors)

    def test_public_interface_rejects_structured_non_public_exposure(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "runtime bridge"
            contract["scope"] = {
                "layer": "SupApp.Runtime",
                "allowed_paths": ["SupApp/Sources/SupApp/AppEnvironment.swift"],
            }
            contract["required_repo_outputs"] = ["SupApp/Sources/SupApp/AppEnvironment.swift"]
            contract["interfaces"] = [
                {
                    "path": "SupApp/Sources/SupApp/AppEnvironment.swift",
                    "symbol": "AppEnvironment.activityTokenPendingSyncer",
                    "signature": "let activityTokenPendingSyncer: any ActivityTokenPendingSyncing",
                    "visibility": "public",
                    "kind": "property",
                    "exposes": ["ActivityTokenPendingSyncing"],
                    "business_rules": ["Expose syncer intentionally."],
                },
                {
                    "path": "SupApp/Sources/SupApp/ActivityTokenPendingSync.swift",
                    "symbol": "ActivityTokenPendingSyncing",
                    "signature": "protocol ActivityTokenPendingSyncing { func sync() async }",
                    "visibility": "internal",
                    "kind": "protocol",
                    "business_rules": ["Local protocol."],
                },
            ]
            contract["acceptance_commands"] = ["xcodebuild -project App.xcodeproj -scheme App build"]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("structured metadata" in error for error in errors), errors)

    def test_public_interface_accepts_structured_public_exposure(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "runtime bridge"
            contract["scope"] = {
                "layer": "SupApp.Runtime",
                "allowed_paths": ["SupApp/Sources/SupApp/AppEnvironment.swift"],
            }
            contract["required_repo_outputs"] = ["SupApp/Sources/SupApp/AppEnvironment.swift"]
            contract["interfaces"] = [
                {
                    "path": "SupApp/Sources/SupApp/AppEnvironment.swift",
                    "symbol": "AppEnvironment.activityTokenPendingSyncer",
                    "signature": "let activityTokenPendingSyncer: any ActivityTokenPendingSyncing",
                    "visibility": "public",
                    "kind": "property",
                    "exposes": ["ActivityTokenPendingSyncing"],
                    "business_rules": ["Expose syncer intentionally."],
                },
                {
                    "path": "SupApp/Sources/SupApp/ActivityTokenPendingSync.swift",
                    "symbol": "ActivityTokenPendingSyncing",
                    "signature": "public protocol ActivityTokenPendingSyncing { func sync() async }",
                    "visibility": "public",
                    "kind": "protocol",
                    "exposes": [],
                    "business_rules": ["Public protocol."],
                },
            ]
            contract["acceptance_commands"] = ["xcodebuild -project App.xcodeproj -scheme App build"]

            self.write_phase(task_path, 0, contract)

            self.assertEqual(PHASE_PLAN_REVIEW.review_phase_plan(root, task_path), [])

    def test_structured_interface_metadata_takes_precedence_over_signature_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "runtime bridge"
            contract["scope"] = {
                "layer": "SupApp.Runtime",
                "allowed_paths": ["SupApp/Sources/SupApp/AppEnvironment.swift"],
            }
            contract["required_repo_outputs"] = ["SupApp/Sources/SupApp/AppEnvironment.swift"]
            contract["interfaces"] = [
                {
                    "path": "SupApp/Sources/SupApp/AppEnvironment.swift",
                    "symbol": "AppEnvironment.activityTokenPendingSyncer",
                    "signature": "public let activityTokenPendingSyncer: ActivityTokenPendingSyncing?",
                    "visibility": "internal",
                    "kind": "property",
                    "business_rules": ["Signature text may be stale, metadata is authoritative."],
                },
                {
                    "path": "SupApp/Sources/SupApp/ActivityTokenPendingSync.swift",
                    "symbol": "ActivityTokenPendingSyncing",
                    "signature": "protocol ActivityTokenPendingSyncing { func sync() async }",
                    "visibility": "internal",
                    "kind": "protocol",
                    "business_rules": ["Local protocol."],
                },
            ]
            contract["acceptance_commands"] = ["xcodebuild -project App.xcodeproj -scheme App build"]

            self.write_phase(task_path, 0, contract)

            self.assertEqual(PHASE_PLAN_REVIEW.review_phase_plan(root, task_path), [])

    def test_boundary_risk_requires_secret_sdk_boundary_obligation_closure(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "supapp bridge"
            contract["scope"] = {
                "layer": "SupApp.Runtime.NotificationBridge",
                "allowed_paths": ["SupApp/Sources/SupApp/AppEnvironment.swift"],
            }
            contract["required_repo_outputs"] = ["SupApp/Sources/SupApp/AppEnvironment.swift"]
            contract["instructions"] = [
                {
                    "id": "P0-001",
                    "task": "Add bridge while preserving Supabase SDK and server secret boundary.",
                    "expected_evidence": ["SupApp/Sources/SupApp/AppEnvironment.swift"],
                }
            ]
            contract["acceptance_commands"] = [
                "xcodebuild -project App.xcodeproj -scheme App build"
            ]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("secret_sdk_boundary design obligation" in error for error in errors), errors)

    def test_boundary_risk_accepts_secret_sdk_boundary_obligation_closure(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            self.write_design_contract(
                task_path,
                [
                    {
                        "id": "obl.secret-boundary",
                        "class": "secret_sdk_boundary",
                        "trigger": "Supabase SDK bridge boundary changes.",
                        "closure_condition": "Boundary validator passes.",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["boundary-validator"],
                    }
                ],
            )
            contract = self.base_contract()
            contract["name"] = "supapp bridge"
            contract["scope"] = {
                "layer": "SupApp.Runtime.NotificationBridge",
                "allowed_paths": ["SupApp/Sources/SupApp/AppEnvironment.swift"],
            }
            contract["required_repo_outputs"] = ["SupApp/Sources/SupApp/AppEnvironment.swift"]
            contract["instructions"] = [
                {
                    "id": "P0-001",
                    "task": "Add bridge while preserving Supabase SDK and server secret boundary.",
                    "expected_evidence": ["SupApp/Sources/SupApp/AppEnvironment.swift"],
                }
            ]
            contract["closes_obligations"] = ["obl.secret-boundary"]
            contract["acceptance_commands"] = [
                "python3 tests/validate_boundaries.py",
                "xcodebuild -project App.xcodeproj -scheme App build",
            ]
            contract["command_expectations"] = [
                {
                    "id": "boundary-validator",
                    "command": "python3 tests/validate_boundaries.py",
                    "role": "acceptance",
                    "target": "tests/validate_boundaries.py",
                }
            ]

            self.write_phase(task_path, 0, contract)

            self.assertEqual(PHASE_PLAN_REVIEW.review_phase_plan(root, task_path), [])

    def test_append_preservation_claim_requires_transaction_or_concurrency_obligation_closure(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            contract = self.base_contract()
            contract["name"] = "pending store"
            contract["scope"] = {
                "layer": "AmbientData",
                "allowed_paths": ["Modules/AmbientData/Sources/AmbientData/AppGroupActivityTokenRegistry.swift"],
            }
            contract["required_repo_outputs"] = [
                "Modules/AmbientData/Sources/AmbientData/AppGroupActivityTokenRegistry.swift"
            ]
            contract["interfaces"] = [
                {
                    "path": "Modules/AmbientData/Sources/AmbientData/AppGroupActivityTokenRegistry.swift",
                    "symbol": "removePendingActivityTokenRegistrations",
                    "signature": "public func removePendingActivityTokenRegistrations(activityIDs: Set<String>) throws",
                    "business_rules": [
                        "Removal preserves entries appended between sync read and removal write by re-reading UserDefaults."
                    ],
                }
            ]
            contract["acceptance_commands"] = [
                "xcodebuild -project App.xcodeproj -scheme App build"
            ]

            self.write_phase(task_path, 0, contract)

            errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)
            self.assertTrue(any("append-preserving" in error for error in errors), errors)

    def test_append_preservation_claim_accepts_transaction_obligation_closure(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            self.write_design_contract(
                task_path,
                [
                    {
                        "id": "obl.pending-store-transaction",
                        "class": "transaction_boundary",
                        "trigger": "Remove pending registrations after re-reading storage.",
                        "closure_condition": "Transaction boundary validator passes.",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["pending-store-validator"],
                    }
                ],
            )
            contract = self.base_contract()
            contract["name"] = "pending store"
            contract["scope"] = {
                "layer": "AmbientData",
                "allowed_paths": ["Modules/AmbientData/Sources/AmbientData/AppGroupActivityTokenRegistry.swift"],
            }
            contract["required_repo_outputs"] = [
                "Modules/AmbientData/Sources/AmbientData/AppGroupActivityTokenRegistry.swift"
            ]
            contract["interfaces"] = [
                {
                    "path": "Modules/AmbientData/Sources/AmbientData/AppGroupActivityTokenRegistry.swift",
                    "symbol": "removePendingActivityTokenRegistrations",
                    "signature": "public func removePendingActivityTokenRegistrations(activityIDs: Set<String>) throws",
                    "business_rules": [
                        "Removal preserves entries appended between sync read and removal write by re-reading UserDefaults."
                    ],
                }
            ]
            contract["closes_obligations"] = ["obl.pending-store-transaction"]
            contract["acceptance_commands"] = [
                "python3 tests/validate_pending_store.py",
                "xcodebuild -project App.xcodeproj -scheme App build",
            ]
            contract["command_expectations"] = [
                {
                    "id": "pending-store-validator",
                    "command": "python3 tests/validate_pending_store.py",
                    "role": "acceptance",
                    "target": "tests/validate_pending_store.py",
                }
            ]

            self.write_phase(task_path, 0, contract)

            self.assertEqual(PHASE_PLAN_REVIEW.review_phase_plan(root, task_path), [])

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
