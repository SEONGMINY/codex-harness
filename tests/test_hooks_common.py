#!/usr/bin/env python3
"""Regression tests for codex-harness hook context trust boundaries."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".codex" / "hooks"))

from harness_common import active_context  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
