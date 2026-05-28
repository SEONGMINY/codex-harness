#!/usr/bin/env python3
"""Regression tests for project installation layout."""

from __future__ import annotations

import importlib.util
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-codex-harness.py"
BOOTSTRAP = ROOT / "scripts" / "bootstrap-install.py"
SPEC = importlib.util.spec_from_file_location("install_codex_harness", INSTALLER)
INSTALL_MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(INSTALL_MODULE)
HARNESS_ATTESTATION_SPEC = importlib.util.spec_from_file_location(
    "source_harness_attestation",
    ROOT / "scripts" / "harness" / "harness_attestation.py",
)
SOURCE_HARNESS_ATTESTATION = importlib.util.module_from_spec(HARNESS_ATTESTATION_SPEC)
assert HARNESS_ATTESTATION_SPEC.loader is not None
HARNESS_ATTESTATION_SPEC.loader.exec_module(SOURCE_HARNESS_ATTESTATION)
sys.path.insert(0, str(ROOT / ".codex" / "hooks"))
import harness_common as SOURCE_HOOK_COMMON  # noqa: E402


def load_attestation_module(path: Path):
    spec = importlib.util.spec_from_file_location("installed_harness_attestation", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class InstallCodexHarnessTest(unittest.TestCase):
    def test_project_install_checks_sources_before_mutating_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            source = tmp / "source"
            target = tmp / "target"
            source.mkdir()
            target_skill = target / ".codex" / "harness" / "scripts" / "skill"
            target_skill.mkdir(parents=True)
            (target_skill / "SKILL.md").write_text("existing skill\n", encoding="utf-8")

            with self.assertRaises(FileNotFoundError):
                INSTALL_MODULE.install_project(
                    source,
                    target,
                    force=True,
                    with_hooks=False,
                    optional_hooks=False,
                )

            self.assertEqual((target_skill / "SKILL.md").read_text(encoding="utf-8"), "existing skill\n")

    def test_project_install_fails_when_install_lock_is_held(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            target = tmp / "target"
            target.mkdir()
            lock_path = target / INSTALL_MODULE.PROJECT_INSTALL_LOCK_TARGET
            lock_path.parent.mkdir(parents=True)
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o666)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

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
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

            self.assertEqual(result.returncode, 1)
            self.assertIn("Another codex-harness project install is active", result.stderr)
            self.assertFalse((target / ".codex" / "harness" / "scripts" / "start.py").exists())

    def test_bootstrap_uses_local_installer_for_harness_source_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            target = tmp / "target"
            target.mkdir()
            installer = target / "scripts" / "install-codex-harness.py"
            installer.parent.mkdir(parents=True)
            marker = target / "local-installer-used.txt"
            installer.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                "Path('local-installer-used.txt').write_text('yes\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            installer.chmod(0o755)
            skill = target / ".agents" / "skills" / "codex-harness" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: codex-harness\nversion: 0.1.5\n---\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(BOOTSTRAP),
                    str(target),
                    "--repo",
                    "file:///definitely/not/used",
                    "--force",
                ],
                text=True,
                capture_output=True,
                check=False,
                cwd=target,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(marker.read_text(encoding="utf-8"), "yes\n")

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
            self.assertEqual((source_skill / "SKILL.md").read_text(encoding="utf-8"), "# source skill\n")
            self.assertTrue((target / ".codex" / "harness" / "scripts" / "start.py").exists())

    def test_project_install_copies_runtime_attested_files_without_drift(self) -> None:
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
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            installed = load_attestation_module(
                target / ".codex" / "harness" / "scripts" / "harness_attestation.py"
            )
            install_manifest = json.loads(
                (target / ".codex" / "harness" / "install-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                installed.harness_attestation()["digest"],
                SOURCE_HARNESS_ATTESTATION.harness_attestation()["digest"],
            )
            self.assertEqual(
                install_manifest["runtime_attestation"]["digest"],
                SOURCE_HARNESS_ATTESTATION.harness_attestation()["digest"],
            )
            self.assertEqual(
                install_manifest["runtime_attestation_trust"],
                "project-local-drift-detection",
            )

    def test_installed_start_preflight_reports_missing_helper_before_imports(self) -> None:
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
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            (target / ".codex" / "harness" / "scripts" / "codex_exec.py").unlink()

            result = subprocess.run(
                [
                    sys.executable,
                    str(target / ".codex" / "harness" / "scripts" / "start.py"),
                    "--root",
                    str(target),
                    "--request",
                    "invalid install",
                    "--codex-bin",
                    str(tmp / "unused-codex"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(".codex/harness/scripts/codex_exec.py", result.stderr)
            self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_installed_runner_preflight_reports_missing_helper_before_imports(self) -> None:
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
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            (target / ".codex" / "harness" / "scripts" / "decision_registry.py").unlink()

            result = subprocess.run(
                [
                    sys.executable,
                    str(target / ".codex" / "harness" / "scripts" / "run-phases.py"),
                    "demo",
                    "--root",
                    str(target),
                    "--codex-bin",
                    str(tmp / "unused-codex"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(".codex/harness/scripts/decision_registry.py", result.stderr)
            self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_installed_runner_preflight_reports_missing_process_runner_before_imports(self) -> None:
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
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            (target / ".codex" / "harness" / "scripts" / "process_runner.py").unlink()

            result = subprocess.run(
                [
                    sys.executable,
                    str(target / ".codex" / "harness" / "scripts" / "run-phases.py"),
                    "demo",
                    "--root",
                    str(target),
                    "--codex-bin",
                    str(tmp / "unused-codex"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(".codex/harness/scripts/process_runner.py", result.stderr)
            self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_installed_verify_preflight_reports_missing_runtime_protocol_before_imports(self) -> None:
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
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            (target / ".codex" / "harness" / "scripts" / "runtime_protocol.py").unlink()

            result = subprocess.run(
                [
                    sys.executable,
                    str(target / ".codex" / "harness" / "scripts" / "verify-task.py"),
                    "demo",
                    "--root",
                    str(target),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(".codex/harness/scripts/runtime_protocol.py", result.stderr)
            self.assertNotIn("ModuleNotFoundError", result.stderr)

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

    def test_hook_registration_uses_shared_write_tool_matcher(self) -> None:
        matcher = INSTALL_MODULE.load_hook_write_tool_matcher(ROOT)

        self.assertEqual(matcher, SOURCE_HOOK_COMMON.HOOK_WRITE_TOOL_MATCHER)
        project_hooks = INSTALL_MODULE.project_hook_groups(optional_hooks=True, write_tool_matcher=matcher)
        user_hooks = INSTALL_MODULE.user_hook_groups(
            Path("/tmp/codex-home"),
            optional_hooks=True,
            write_tool_matcher=matcher,
        )

        self.assertEqual(project_hooks["PreToolUse"][0]["matcher"], SOURCE_HOOK_COMMON.HOOK_WRITE_TOOL_MATCHER)
        self.assertEqual(project_hooks["PostToolUse"][0]["matcher"], SOURCE_HOOK_COMMON.HOOK_WRITE_TOOL_MATCHER)
        self.assertEqual(user_hooks["PreToolUse"][0]["matcher"], SOURCE_HOOK_COMMON.HOOK_WRITE_TOOL_MATCHER)
        self.assertEqual(user_hooks["PostToolUse"][0]["matcher"], SOURCE_HOOK_COMMON.HOOK_WRITE_TOOL_MATCHER)

    def test_project_hook_install_replaces_legacy_direct_hook_commands(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            target = tmp / "target"
            target.mkdir()
            hooks_path = target / ".codex" / "hooks.json"
            hooks_path.parent.mkdir(parents=True)
            hooks_path.write_text(
                """
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|apply_patch|Edit|Write|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \\"$(git rev-parse --show-toplevel)/.codex/hooks/harness_pre_tool_use.py\\"",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
""".lstrip(),
                encoding="utf-8",
            )

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
            hooks = json.loads(hooks_path.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
            commands = [hook["command"] for group in hooks for hook in group["hooks"]]
            self.assertEqual(len([item for item in commands if "harness_pre_tool_use.py" in item]), 1)
            self.assertIn(".codex/hooks/codex-harness/harness_pre_tool_use.py", commands[0])
            self.assertNotIn(".codex/hooks/harness_pre_tool_use.py", commands[0])


if __name__ == "__main__":
    unittest.main()
