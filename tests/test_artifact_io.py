#!/usr/bin/env python3
"""Regression tests for atomic artifact writes."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))
SPEC = importlib.util.spec_from_file_location("artifact_io", HARNESS_DIR / "artifact_io.py")
assert SPEC is not None
ARTIFACT_IO = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ARTIFACT_IO)


class ArtifactIOTest(unittest.TestCase):
    def test_atomic_write_json_writes_complete_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "runtime" / "phase0-result.json"

            ARTIFACT_IO.atomic_write_json(path, {"status": "completed", "phase": 0})

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"status": "completed", "phase": 0},
            )
            self.assertEqual(list(path.parent.glob(".*.tmp")), [])

    def test_atomic_write_text_preserves_existing_file_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "runtime" / "phase0-gate.json"
            path.parent.mkdir(parents=True)
            path.write_text("old\n", encoding="utf-8")

            with mock.patch.object(ARTIFACT_IO.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    ARTIFACT_IO.atomic_write_text(path, "new\n")

            self.assertEqual(path.read_text(encoding="utf-8"), "old\n")
            self.assertEqual(list(path.parent.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
