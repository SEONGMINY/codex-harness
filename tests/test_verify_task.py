#!/usr/bin/env python3
"""Regression tests for task verification helpers."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))
SPEC = importlib.util.spec_from_file_location("verify_task", HARNESS_DIR / "verify-task.py")
assert SPEC is not None
VERIFY_TASK = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VERIFY_TASK)


class VerifyTaskHelperTest(unittest.TestCase):
    def test_mermaid_validation_accepts_allowed_diagram_types(self) -> None:
        text = """# Implementation Design Review

```mermaid
flowchart LR
  A["service"] --> B["domain"]
```
"""

        self.assertEqual(VERIFY_TASK.validate_mermaid_blocks(text), [])

    def test_mermaid_validation_rejects_unsupported_diagram_types(self) -> None:
        text = """# Implementation Design Review

```mermaid
classDiagram
  class Service
```
"""

        errors = VERIFY_TASK.validate_mermaid_blocks(text)

        self.assertTrue(any("must start with one of" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
