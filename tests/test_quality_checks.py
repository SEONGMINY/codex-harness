#!/usr/bin/env python3
"""Regression tests for harness quality checks."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
SPEC = importlib.util.spec_from_file_location("quality_checks", HARNESS_DIR / "run-quality-checks.py")
assert SPEC is not None
QUALITY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(QUALITY)


class QualityChecksTest(unittest.TestCase):
    def test_builtin_style_blocks_trailing_whitespace_when_no_project_lint_exists(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            target = root / "src" / "demo.py"
            target.parent.mkdir(parents=True)
            target.write_text("value = 1  \n", encoding="utf-8")

            result = QUALITY.run_quality_checks(root, {}, ["src/demo.py"])

            self.assertEqual(result["source"], "harness")
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["checks"][0]["id"], "harness-baseline-style")
            self.assertEqual(result["checks"][0]["findings"][0]["reason"], "trailing whitespace")

    def test_project_lint_commands_prefer_existing_package_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {
                            "format:check": "prettier --check .",
                            "lint": "eslint .",
                            "typecheck": "tsc --noEmit",
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(QUALITY.shutil, "which", return_value="/usr/bin/npm"):
                commands = QUALITY.project_lint_commands(root)

            self.assertEqual(commands, [["npm", "run", "format:check"], ["npm", "run", "lint"]])

    def test_changed_files_are_limited_to_contract_scope(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            contract = {"scope": {"allowed_paths": ["src/**"]}}

            files = QUALITY.changed_files_from_args(
                root,
                ["src/allowed.ts", "docs/out-of-scope.md"],
                contract,
            )

            self.assertEqual(files, ["src/allowed.ts"])

    def test_existing_lint_missing_manager_is_warning_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            target = root / "src" / "demo.ts"
            target.parent.mkdir(parents=True)
            target.write_text("const value = 1;\n", encoding="utf-8")
            (root / "package.json").write_text(
                json.dumps({"scripts": {"lint": "eslint ."}}) + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(QUALITY.shutil, "which", return_value=None):
                result = QUALITY.run_quality_checks(root, {}, ["src/demo.ts"])

            self.assertEqual(result["source"], "mixed")
            self.assertEqual(result["status"], "passed")
            self.assertIn("Quality check warning: project-command:npm", result["warning_reasons"])

    def test_runnable_project_lint_skips_harness_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            target = root / "src" / "demo.ts"
            target.parent.mkdir(parents=True)
            target.write_text("const value = 1;  \n", encoding="utf-8")
            (root / "package.json").write_text(
                json.dumps({"scripts": {"lint": "eslint ."}}) + "\n",
                encoding="utf-8",
            )

            with (
                mock.patch.object(QUALITY.shutil, "which", return_value="/usr/bin/npm"),
                mock.patch.object(QUALITY, "run_capture", return_value=(0, "")),
            ):
                result = QUALITY.run_quality_checks(root, {}, ["src/demo.ts"])

            self.assertEqual(result["source"], "project")
            self.assertEqual(result["status"], "passed")
            self.assertNotIn("harness-baseline-style", [check["id"] for check in result["checks"]])

    def test_existing_lint_missing_manager_can_block_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            target = root / "src" / "demo.ts"
            target.parent.mkdir(parents=True)
            target.write_text("const value = 1;\n", encoding="utf-8")
            (root / "package.json").write_text(
                json.dumps({"scripts": {"lint": "eslint ."}}) + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(QUALITY.shutil, "which", return_value=None):
                result = QUALITY.run_quality_checks(root, {}, ["src/demo.ts"], "block")

            self.assertEqual(result["source"], "mixed")
            self.assertEqual(result["status"], "failed")
            self.assertIn("Quality check failed: project-command:npm", result["blocking_reasons"])


if __name__ == "__main__":
    unittest.main()
