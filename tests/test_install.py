#!/usr/bin/env python3
"""Regression tests for project installation layout."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-codex-harness.py"


class InstallCodexHarnessTest(unittest.TestCase):
    def test_project_install_removes_project_local_skill_shadow(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            target = tmp / "target"
            target.mkdir()
            stale_skill = target / ".agents" / "skills" / "codex-harness"
            stale_skill.mkdir(parents=True)
            (stale_skill / "SKILL.md").write_text("# stale\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(INSTALLER),
                    str(target),
                    "--scope",
                    "project",
                    "--force",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertFalse(stale_skill.exists())
            self.assertTrue((target / ".codex" / "harness" / "scripts" / "skill" / "SKILL.md").exists())
            self.assertTrue((target / ".codex" / "harness" / "scripts" / "codex_exec.py").exists())
            self.assertTrue((target / ".codex" / "harness" / "scripts" / "run-quality-checks.py").exists())
            self.assertTrue((target / ".codex" / "harness" / "scripts" / "review-phase-plan.py").exists())
            self.assertFalse((target / "scripts" / "harness").exists())
            self.assertTrue((target / "codex-harness.json").exists())
            gitignore = (target / ".gitignore").read_text(encoding="utf-8")
            self.assertIn(".codex/harness/", gitignore)
            self.assertIn(".codex-harness/", gitignore)

    def test_project_force_install_removes_legacy_scripts_harness(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            target = tmp / "target"
            legacy = target / "scripts" / "harness"
            legacy.mkdir(parents=True)
            (legacy / "start.py").write_text("# old\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(INSTALLER),
                    str(target),
                    "--scope",
                    "project",
                    "--force",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertFalse(legacy.exists())
            self.assertTrue((target / ".codex" / "harness" / "scripts" / "start.py").exists())

    def test_project_force_install_preserves_harness_source_checkout_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            target = tmp / "target"
            legacy = target / "scripts" / "harness"
            legacy.mkdir(parents=True)
            (legacy / "start.py").write_text("# local source\n", encoding="utf-8")
            (target / "scripts" / "install-codex-harness.py").write_text("# installer\n", encoding="utf-8")
            source_skill = target / ".agents" / "skills" / "codex-harness"
            source_skill.mkdir(parents=True)
            (source_skill / "SKILL.md").write_text("# source skill\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(INSTALLER),
                    str(target),
                    "--scope",
                    "project",
                    "--force",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue((legacy / "start.py").exists())
            self.assertTrue((target / ".codex" / "harness" / "scripts" / "start.py").exists())

    def test_project_hook_install_ignores_local_hook_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            target = tmp / "target"
            target.mkdir()

            result = subprocess.run(
                [
                    sys.executable,
                    str(INSTALLER),
                    str(target),
                    "--scope",
                    "project",
                    "--force",
                    "--with-hooks",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue((target / ".codex" / "hooks.json").exists())
            self.assertTrue((target / ".codex" / "hooks" / "codex-harness" / "harness_pre_tool_use.py").exists())
            gitignore = (target / ".gitignore").read_text(encoding="utf-8")
            self.assertIn(".codex/hooks/codex-harness/", gitignore)
            self.assertIn(".codex/hooks.json", gitignore)
            self.assertIn(".codex/hooks.optional.json", gitignore)


if __name__ == "__main__":
    unittest.main()
