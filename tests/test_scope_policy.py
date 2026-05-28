#!/usr/bin/env python3
"""Regression tests for shared codex-harness scope path semantics."""

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

SCOPE_SPEC = importlib.util.spec_from_file_location("scope_policy", HARNESS_DIR / "scope_policy.py")
assert SCOPE_SPEC is not None
SCOPE = importlib.util.module_from_spec(SCOPE_SPEC)
assert SCOPE_SPEC.loader is not None
SCOPE_SPEC.loader.exec_module(SCOPE)

PHASE_SPEC = importlib.util.spec_from_file_location("phase_contract", HARNESS_DIR / "phase_contract.py")
assert PHASE_SPEC is not None
PHASE = importlib.util.module_from_spec(PHASE_SPEC)
assert PHASE_SPEC.loader is not None
PHASE_SPEC.loader.exec_module(PHASE)

QUALITY_SPEC = importlib.util.spec_from_file_location("quality_checks", HARNESS_DIR / "run-quality-checks.py")
assert QUALITY_SPEC is not None
QUALITY = importlib.util.module_from_spec(QUALITY_SPEC)
assert QUALITY_SPEC.loader is not None
QUALITY_SPEC.loader.exec_module(QUALITY)

HOOKS_DIR = ROOT / ".codex" / "hooks"
sys.path.insert(0, str(HOOKS_DIR))
HOOK_SPEC = importlib.util.spec_from_file_location("harness_common", HOOKS_DIR / "harness_common.py")
assert HOOK_SPEC is not None
HOOKS = importlib.util.module_from_spec(HOOK_SPEC)
assert HOOK_SPEC.loader is not None
sys.modules["harness_common"] = HOOKS
HOOK_SPEC.loader.exec_module(HOOKS)


class ScopePolicyTest(unittest.TestCase):
    def test_phase_contract_reexports_shared_scope_policy(self) -> None:
        cases = [
            ("src/app.py", ["src/**"], True),
            ("src/nested/app.py", ["src"], True),
            ("docs/app.md", ["src/**"], False),
            ("./src/app.py", ["src/**"], True),
            ("../src/app.py", ["src/**"], False),
            ("/src/app.py", ["src/**"], False),
            (".env", ["env"], False),
            (".github/workflows/ci.yml", ["github/**"], False),
            ("src/app.py", [], False),
        ]

        for path, allowed, expected in cases:
            with self.subTest(path=path, allowed=allowed):
                self.assertEqual(SCOPE.path_allowed(path, allowed), expected)
                self.assertEqual(PHASE.path_allowed(path, allowed), expected)

    def test_quality_checks_do_not_expand_empty_scope_to_repo_wide_scan(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            (root / "src").mkdir()
            (root / "src" / "demo.py").write_text("value = 1\n", encoding="utf-8")

            self.assertEqual(QUALITY.changed_files_from_args(root, [], {}), [])
            self.assertEqual(
                QUALITY.changed_files_from_args(root, ["src/demo.py"], {}),
                ["src/demo.py"],
            )

    def test_hook_uses_installed_scope_policy_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp).resolve()
            installed = root / ".codex" / "harness" / "scripts" / "scope_policy.py"
            installed.parent.mkdir(parents=True)
            installed.write_text(
                "def path_allowed(path, allowed_paths):\n"
                "    return path == 'custom/allowed.txt'\n",
                encoding="utf-8",
            )

            self.assertTrue(HOOKS.path_allowed("custom/allowed.txt", ["ignored"], root))
            self.assertFalse(HOOKS.path_allowed("src/app.py", ["src/**"], root))

    def test_shared_policy_preserves_hidden_and_traversal_paths_in_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp).resolve()
            installed = root / ".codex" / "harness" / "scripts" / "scope_policy.py"
            installed.parent.mkdir(parents=True)
            installed.write_text((ROOT / "scripts" / "harness" / "scope_policy.py").read_text(encoding="utf-8"), encoding="utf-8")
            task_path = root / "tasks" / "demo"
            contract_path = task_path / "context-pack" / "runtime" / "phase0-contract.json"
            contract_path.parent.mkdir(parents=True)
            contract = {
                "phase": 0,
                "scope": {"allowed_paths": ["src/**", "env", "github/**"]},
                "required_outputs": [],
            }
            contract_path.write_text(json.dumps(contract) + "\n", encoding="utf-8")
            ctx = HOOKS.HarnessContext(root, task_path, 0, contract_path, contract)

            violations = HOOKS.scope_violations(
                ctx,
                [
                    "../src/app.py",
                    ".env",
                    ".github/workflows/ci.yml",
                    "src/app.py",
                ],
            )

            self.assertEqual(
                violations,
                ["../src/app.py", ".env", ".github/workflows/ci.yml"],
            )

    def test_scope_violations_match_required_output_exemptions(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp).resolve()
            task_path = root / "tasks" / "demo"
            runtime = task_path / "context-pack" / "runtime"
            runtime.mkdir(parents=True)
            contract_path = runtime / "phase0-contract.json"
            contract = {
                "phase": 0,
                "scope": {"allowed_paths": ["src/**"]},
                "required_outputs": ["context-pack/handoffs/phase0.md"],
            }
            contract_path.write_text(json.dumps(contract) + "\n", encoding="utf-8")
            ctx = HOOKS.HarnessContext(root, task_path, 0, contract_path, contract)

            violations = HOOKS.scope_violations(
                ctx,
                [
                    "src/app.py",
                    "tasks/demo/context-pack/handoffs/phase0.md",
                    "docs/out.md",
                ],
            )

            self.assertEqual(violations, ["docs/out.md"])


if __name__ == "__main__":
    unittest.main()
