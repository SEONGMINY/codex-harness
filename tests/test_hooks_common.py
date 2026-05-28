#!/usr/bin/env python3
"""Regression tests for codex-harness hook context trust boundaries."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".codex" / "hooks"))

import harness_pre_tool_use  # noqa: E402
import harness_post_tool_use  # noqa: E402
from harness_common import (  # noqa: E402
    HarnessContext,
    HOOK_WRITE_TOOL_MATCHER,
    active_context,
    extract_tool_write_paths,
    runner_owned,
    scope_violations,
)


class HookContextTest(unittest.TestCase):
    def make_context_files(self, root: Path, phase: int = 0) -> tuple[Path, Path]:
        task_path = root / "tasks" / "demo"
        runtime = task_path / "context-pack" / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        contract_path = runtime / f"phase{phase}-contract.json"
        contract_path.write_text(json.dumps({"phase": phase, "scope": {"allowed_paths": ["src/**"]}}) + "\n")
        return task_path, contract_path

    def harness_env(self, root: Path, task_path: Path, contract_path: Path, phase: int = 0) -> dict[str, str]:
        return {
            "CODEX_HARNESS_ACTIVE": "1",
            "CODEX_HARNESS_ROOT": str(root),
            "CODEX_HARNESS_TASK_PATH": str(task_path.relative_to(root)),
            "CODEX_HARNESS_PHASE": str(phase),
            "CODEX_HARNESS_CONTRACT_PATH": str(contract_path.relative_to(root)),
        }

    def test_active_context_accepts_runner_runtime_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp).resolve()
            task_path, contract_path = self.make_context_files(root)

            with mock.patch.dict(os.environ, self.harness_env(root, task_path, contract_path), clear=True):
                ctx = active_context({"cwd": str(root)})

            self.assertIsNotNone(ctx)
            assert ctx is not None
            self.assertEqual(ctx.root, root)
            self.assertEqual(ctx.task_path, task_path)
            self.assertEqual(ctx.contract_path, contract_path)

    def test_active_context_rejects_root_mismatch_with_event_repo(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp).resolve()
            other_root = root / "other"
            other_root.mkdir()
            task_path, contract_path = self.make_context_files(other_root)

            with mock.patch.dict(os.environ, self.harness_env(other_root, task_path, contract_path), clear=True):
                ctx = active_context({"cwd": str(root)})

            self.assertIsNone(ctx)

    def test_active_context_rejects_absolute_or_parent_relative_task_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp).resolve()
            task_path, contract_path = self.make_context_files(root)
            env = self.harness_env(root, task_path, contract_path)
            env["CODEX_HARNESS_TASK_PATH"] = "../demo"

            with mock.patch.dict(os.environ, env, clear=True):
                self.assertIsNone(active_context({"cwd": str(root)}))

            env["CODEX_HARNESS_TASK_PATH"] = str(task_path)
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertIsNone(active_context({"cwd": str(root)}))

    def test_active_context_rejects_contract_outside_runtime_dir(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp).resolve()
            task_path, contract_path = self.make_context_files(root)
            outside_contract = task_path / "phase0-contract.json"
            outside_contract.write_text(contract_path.read_text(encoding="utf-8"), encoding="utf-8")
            env = self.harness_env(root, task_path, outside_contract)

            with mock.patch.dict(os.environ, env, clear=True):
                ctx = active_context({"cwd": str(root)})

            self.assertIsNone(ctx)

    def test_active_context_rejects_phase_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp).resolve()
            task_path, contract_path = self.make_context_files(root, phase=1)
            env = self.harness_env(root, task_path, contract_path, phase=0)

            with mock.patch.dict(os.environ, env, clear=True):
                ctx = active_context({"cwd": str(root)})

            self.assertIsNone(ctx)

    def test_extract_tool_write_paths_covers_registered_edit_and_write_tools(self) -> None:
        self.assertEqual(
            extract_tool_write_paths({"tool_name": "Write", "tool_input": {"file_path": "outside.txt"}}),
            ["outside.txt"],
        )
        self.assertEqual(
            extract_tool_write_paths({"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}}),
            ["src/app.py"],
        )
        self.assertEqual(
            extract_tool_write_paths(
                {
                    "tool_name": "MultiEdit",
                    "tool_input": {"file_path": "outside.txt", "edits": [{"old_string": "a", "new_string": "b"}]},
                }
            ),
            ["outside.txt"],
        )
        self.assertEqual(
            extract_tool_write_paths(
                {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "outside.ipynb"}}
            ),
            ["outside.ipynb"],
        )

    def test_hook_matcher_covers_every_supported_write_tool(self) -> None:
        for tool_name in ["Bash", "apply_patch", "Edit", "Write", "MultiEdit", "NotebookEdit"]:
            with self.subTest(tool_name=tool_name):
                self.assertIn(tool_name, HOOK_WRITE_TOOL_MATCHER.split("|"))

    def test_pre_tool_hook_blocks_write_outside_phase_scope(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp).resolve()
            task_path, contract_path = self.make_context_files(root)
            event = {
                "cwd": str(root),
                "tool_name": "Write",
                "tool_input": {"file_path": "outside.txt", "content": "out of scope"},
            }

            with (
                mock.patch.dict(os.environ, self.harness_env(root, task_path, contract_path), clear=True),
                mock.patch("sys.stdin", StringIO(json.dumps(event))),
                mock.patch("sys.stdout", new_callable=StringIO) as stdout,
            ):
                self.assertEqual(harness_pre_tool_use.main(), 0)

            output = json.loads(stdout.getvalue())
            self.assertEqual(output["decision"], "block")
            self.assertIn("outside.txt", output["reason"])

    def test_post_tool_hook_blocks_write_outside_phase_scope(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp).resolve()
            task_path, contract_path = self.make_context_files(root)
            event = {
                "cwd": str(root),
                "tool_name": "Edit",
                "tool_input": {"file_path": "outside.txt", "old_string": "a", "new_string": "b"},
            }

            with (
                mock.patch.dict(os.environ, self.harness_env(root, task_path, contract_path), clear=True),
                mock.patch("sys.stdin", StringIO(json.dumps(event))),
                mock.patch("sys.stdout", new_callable=StringIO) as stdout,
            ):
                self.assertEqual(harness_post_tool_use.main(), 0)

            output = json.loads(stdout.getvalue())
            self.assertEqual(output["decision"], "block")
            self.assertIn("outside.txt", output["reason"])

    def test_scope_allows_write_tool_inside_phase_scope(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp).resolve()
            task_path, contract_path = self.make_context_files(root)

            with mock.patch.dict(os.environ, self.harness_env(root, task_path, contract_path), clear=True):
                ctx = active_context({"cwd": str(root)})

            self.assertIsNotNone(ctx)
            assert ctx is not None
            self.assertEqual(scope_violations(ctx, ["src/app.py"]), [])

    def test_scope_normalizes_relative_write_paths_from_event_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp).resolve()
            task_path, contract_path = self.make_context_files(root)
            subdir = root / "packages" / "web"
            subdir.mkdir(parents=True)
            contract = {"phase": 0, "scope": {"allowed_paths": ["src/**"]}}
            ctx = HarnessContext(root, task_path, 0, contract_path, contract, subdir)

            self.assertEqual(scope_violations(ctx, ["src/app.py"]), ["packages/web/src/app.py"])

    def test_runner_owned_patterns_cover_runtime_proof_artifacts(self) -> None:
        runner_paths = [
            "tasks/demo/context-pack/runtime/phase0-attempt1-commit.json",
            "tasks/demo/context-pack/runtime/phase0-attempt-manifest.jsonl",
            "tasks/demo/context-pack/runtime/phase0-obligation-closure-attempt1.json",
            "tasks/demo/context-pack/runtime/phase0-result-attempt1.json",
            "tasks/demo/context-pack/runtime/phase0-handoff-attempt1.md",
            "tasks/demo/context-pack/runtime/phase0-contract-attempt1.json",
            "tasks/demo/context-pack/runtime/phase0-checklist-attempt1.md",
            "tasks/demo/context-pack/runtime/phase0-prompt-attempt1.md",
            "tasks/demo/context-pack/runtime/phase0-evidence-attempt1.json",
            "tasks/demo/context-pack/runtime/phase0-reconciliation-attempt1.json",
            "tasks/demo/context-pack/runtime/phase0-reconciliation-attempt1.md",
            "tasks/demo/context-pack/runtime/phase0-gate-attempt1.json",
            "tasks/demo/context-pack/runtime/phase0-quality-attempt1.json",
            "tasks/demo/context-pack/runtime/phase0-repair-packet-attempt1.json",
            "tasks/demo/context-pack/runtime/phase0-repair-packet-attempt1.md",
            "tasks/demo/context-pack/runtime/phase0-baseline.json",
            "tasks/demo/context-pack/runtime/phase0-reset-marker.json",
            "tasks/demo/context-pack/runtime/evaluation-repair1-result.json",
            "tasks/demo/context-pack/runtime/run-phases.lock",
            "tasks/demo/context-pack/runtime/progress.md",
            "tasks/demo/context-pack/runtime/install-preflight.json",
        ]

        for path in runner_paths:
            with self.subTest(path=path):
                self.assertTrue(runner_owned(path))


if __name__ == "__main__":
    unittest.main()
