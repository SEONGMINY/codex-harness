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
            self.assertTrue((target / "scripts" / "harness" / "skill" / "SKILL.md").exists())
            self.assertTrue((target / "scripts" / "harness" / "codex_exec.py").exists())
            self.assertTrue((target / "codex-harness.json").exists())


if __name__ == "__main__":
    unittest.main()
