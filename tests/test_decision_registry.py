#!/usr/bin/env python3
"""Regression tests for decision registry validation."""

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
sys.path.insert(0, str(HARNESS_DIR))
SPEC = importlib.util.spec_from_file_location("decision_registry", HARNESS_DIR / "decision_registry.py")
assert SPEC is not None
DECISIONS = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(DECISIONS)


class DecisionRegistryTest(unittest.TestCase):
    def registry(self) -> dict[str, object]:
        return {
            "decisions": {
                "decisions": [
                    {"id": "D-001", "status": "approved", "summary": "Use runner-owned gates."}
                ]
            },
            "open_decisions": {"decisions": []},
            "architecture": {
                "nodes": [{"id": "A-001", "name": "runner", "responsibility": "phase execution"}],
                "allowed_edges": [],
                "decisions": [{"id": "A-001", "summary": "Runner owns phase execution."}],
                "forbid_cycles": True,
            },
            "dependency_policy": {
                "new_dependencies": "forbidden",
                "approved_new_dependencies": [],
                "approved_dependency_manifest_changes": [],
            },
            "context_budget": {
                "search_batches": 1,
                "max_files_to_read": 3,
                "stop_when": ["target files are known"],
                "escalate_when": ["scope boundary is unclear"],
            },
        }

    def test_blocking_open_decision_fails(self) -> None:
        registry = self.registry()
        registry["open_decisions"] = {
            "decisions": [
                {
                    "id": "OD-001",
                    "question": "Add a new dependency?",
                    "blocking_stage": "plan",
                    "status": "open",
                }
            ]
        }

        errors = DECISIONS.validate_open_decisions(registry)

        self.assertTrue(any("OD-001" in error for error in errors), errors)

    def test_contract_refs_must_be_approved(self) -> None:
        contract = {
            "decision_refs": ["D-404"],
            "architecture_refs": ["A-001"],
            "dependency_policy": {
                "new_dependencies": "forbidden",
                "approved_new_dependencies": [],
                "approved_dependency_manifest_changes": [],
            },
        }

        errors = DECISIONS.validate_contract_refs(contract, self.registry())

        self.assertTrue(any("D-404" in error for error in errors), errors)

    def test_contract_dependency_policy_cannot_exceed_registry_policy(self) -> None:
        contract = {
            "decision_refs": ["D-001"],
            "architecture_refs": ["A-001"],
            "dependency_policy": {
                "new_dependencies": "allowed",
                "approved_new_dependencies": [],
                "approved_dependency_manifest_changes": [],
            },
        }

        errors = DECISIONS.validate_contract_refs(contract, self.registry())

        self.assertTrue(any("more permissive" in error for error in errors), errors)

    def test_approved_only_contract_must_use_registry_approved_values(self) -> None:
        registry = self.registry()
        registry["dependency_policy"] = {
            "new_dependencies": "approved_only",
            "approved_new_dependencies": ["pydantic"],
            "approved_dependency_manifest_changes": ["pyproject.toml"],
        }
        contract = {
            "decision_refs": ["D-001"],
            "architecture_refs": ["A-001"],
            "dependency_policy": {
                "new_dependencies": "approved_only",
                "approved_new_dependencies": ["requests"],
                "approved_dependency_manifest_changes": ["requirements.txt"],
            },
        }

        errors = DECISIONS.validate_contract_refs(contract, registry)

        self.assertTrue(any("requests" in error for error in errors), errors)
        self.assertTrue(any("requirements.txt" in error for error in errors), errors)

    def test_dependency_manifest_change_requires_policy(self) -> None:
        contract = {
            "dependency_policy": {
                "new_dependencies": "forbidden",
                "approved_new_dependencies": [],
                "approved_dependency_manifest_changes": [],
            }
        }

        errors = DECISIONS.validate_dependency_changes(contract, ["package.json"])

        self.assertTrue(errors)

    def test_approved_only_requires_approved_manifest_path(self) -> None:
        contract = {
            "dependency_policy": {
                "new_dependencies": "approved_only",
                "approved_new_dependencies": ["pydantic"],
                "approved_dependency_manifest_changes": [],
            }
        }

        errors = DECISIONS.validate_dependency_changes(contract, ["package.json"])

        self.assertTrue(errors)

        contract["dependency_policy"]["approved_dependency_manifest_changes"] = ["package.json"]

        errors = DECISIONS.validate_dependency_changes(contract, ["package.json"])

        self.assertEqual(errors, [])

    def test_approved_only_rejects_unapproved_package_json_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            subprocess.run(["git", "init"], cwd=root, text=True, capture_output=True, check=False)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=False)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=False)
            package_json = root / "package.json"
            package_json.write_text(
                json.dumps({"dependencies": {"pydantic": "^1.0.0"}}) + "\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "package.json"], cwd=root, check=False)
            subprocess.run(["git", "commit", "-m", "baseline"], cwd=root, text=True, capture_output=True, check=False)
            package_json.write_text(
                json.dumps({"dependencies": {"pydantic": "^1.0.0", "requests": "^2.0.0"}}) + "\n",
                encoding="utf-8",
            )
            contract = {
                "dependency_policy": {
                    "new_dependencies": "approved_only",
                    "approved_new_dependencies": ["pydantic"],
                    "approved_dependency_manifest_changes": ["package.json"],
                }
            }

            errors = DECISIONS.validate_dependency_changes(contract, ["package.json"], root)

            self.assertTrue(any("requests" in error for error in errors), errors)

    def test_approved_only_accepts_approved_pyproject_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            subprocess.run(["git", "init"], cwd=root, text=True, capture_output=True, check=False)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=False)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=False)
            pyproject = root / "pyproject.toml"
            pyproject.write_text("[project]\ndependencies = []\n", encoding="utf-8")
            subprocess.run(["git", "add", "pyproject.toml"], cwd=root, check=False)
            subprocess.run(["git", "commit", "-m", "baseline"], cwd=root, text=True, capture_output=True, check=False)
            pyproject.write_text("[project]\ndependencies = [\"pydantic>=2\"]\n", encoding="utf-8")
            contract = {
                "dependency_policy": {
                    "new_dependencies": "approved_only",
                    "approved_new_dependencies": ["pydantic"],
                    "approved_dependency_manifest_changes": ["pyproject.toml"],
                }
            }

            errors = DECISIONS.validate_dependency_changes(contract, ["pyproject.toml"], root)

            self.assertEqual(errors, [])

    def test_approved_only_rejects_unsupported_manifest_parser(self) -> None:
        contract = {
            "dependency_policy": {
                "new_dependencies": "approved_only",
                "approved_new_dependencies": ["serde"],
                "approved_dependency_manifest_changes": ["Cargo.toml"],
            }
        }

        errors = DECISIONS.validate_dependency_changes(contract, ["Cargo.toml"], ROOT)

        self.assertTrue(any("supported dependency parsing" in error for error in errors), errors)

    def test_approved_only_allows_lockfile_with_verified_source_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            subprocess.run(["git", "init"], cwd=root, text=True, capture_output=True, check=False)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=False)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=False)
            package_json = root / "package.json"
            package_lock = root / "package-lock.json"
            package_json.write_text(json.dumps({"dependencies": {}}) + "\n", encoding="utf-8")
            package_lock.write_text("{}\n", encoding="utf-8")
            subprocess.run(["git", "add", "package.json", "package-lock.json"], cwd=root, check=False)
            subprocess.run(["git", "commit", "-m", "baseline"], cwd=root, text=True, capture_output=True, check=False)
            package_json.write_text(
                json.dumps({"dependencies": {"pydantic": "^1.0.0"}}) + "\n",
                encoding="utf-8",
            )
            package_lock.write_text('{"packages":{"node_modules/pydantic":{}}}\n', encoding="utf-8")
            contract = {
                "dependency_policy": {
                    "new_dependencies": "approved_only",
                    "approved_new_dependencies": ["pydantic"],
                    "approved_dependency_manifest_changes": ["package.json", "package-lock.json"],
                }
            }

            errors = DECISIONS.validate_dependency_changes(
                contract,
                ["package.json", "package-lock.json"],
                root,
            )

            self.assertEqual(errors, [])

    def test_approved_only_rejects_lockfile_without_source_manifest(self) -> None:
        contract = {
            "dependency_policy": {
                "new_dependencies": "approved_only",
                "approved_new_dependencies": ["pydantic"],
                "approved_dependency_manifest_changes": ["package-lock.json"],
            }
        }

        errors = DECISIONS.validate_dependency_changes(contract, ["package-lock.json"], ROOT)

        self.assertTrue(any("package-lock.json" in error for error in errors), errors)

    def test_placeholders_in_approved_decisions_fail(self) -> None:
        registry = self.registry()
        registry["decisions"] = {
            "decisions": [
                {
                    "id": "D-001",
                    "status": "approved",
                    "summary": "Replace this with an approved decision.",
                }
            ]
        }

        errors = DECISIONS.validate_decision_files(registry)

        self.assertTrue(any("placeholder" in error for error in errors), errors)

    def test_open_decision_enums_are_validated(self) -> None:
        registry = self.registry()
        registry["open_decisions"] = {
            "decisions": [
                {
                    "id": "OD-001",
                    "question": "Approve dependency?",
                    "blocking_stage": "plna",
                    "status": "opne",
                }
            ]
        }

        errors = DECISIONS.validate_decision_files(registry)

        self.assertTrue(any("status" in error for error in errors), errors)
        self.assertTrue(any("blocking_stage" in error for error in errors), errors)

    def test_non_object_registry_items_fail(self) -> None:
        registry = self.registry()
        registry["open_decisions"] = {"decisions": ["not an object"]}

        errors = DECISIONS.validate_decision_files(registry)

        self.assertTrue(any("must be an object" in error for error in errors), errors)

    def test_load_decision_registry_reads_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            task_path = Path(raw_tmp) / "tasks" / "demo"
            static_dir = task_path / "context-pack" / "static"
            static_dir.mkdir(parents=True)
            for key, path in DECISIONS.decision_file_paths(task_path).items():
                value = self.registry()[key]
                path.write_text(json.dumps(value) + "\n", encoding="utf-8")

            registry, errors = DECISIONS.load_decision_registry(task_path)

            self.assertEqual(errors, [])
            self.assertIn("decisions", registry)


if __name__ == "__main__":
    unittest.main()
