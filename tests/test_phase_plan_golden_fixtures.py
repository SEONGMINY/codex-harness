#!/usr/bin/env python3
"""Golden artifact-shape fixtures for planned-state phase semantic review."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "phase_plans"
sys.path.insert(0, str(HARNESS_DIR))
SPEC = importlib.util.spec_from_file_location("phase_plan_review", HARNESS_DIR / "review-phase-plan.py")
assert SPEC is not None
PHASE_PLAN_REVIEW = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PHASE_PLAN_REVIEW)


class PhasePlanGoldenFixtureTest(unittest.TestCase):
    def fixture_names(self) -> list[str]:
        return sorted(path.name for path in FIXTURE_DIR.iterdir() if path.is_dir())

    def test_phase_plan_golden_fixtures(self) -> None:
        self.assertTrue(self.fixture_names(), "expected at least one phase plan fixture")
        for fixture_name in self.fixture_names():
            with self.subTest(fixture=fixture_name):
                root = FIXTURE_DIR / fixture_name
                task_path = root / "tasks" / "demo"
                expected = json.loads((root / "expected-review.json").read_text(encoding="utf-8"))

                errors = PHASE_PLAN_REVIEW.review_phase_plan(root, task_path)

                if expected["status"] == "passed":
                    self.assertEqual(errors, [])
                    continue
                self.assertTrue(errors, "expected review errors")
                for needle in expected.get("errors_contain", []):
                    self.assertTrue(
                        any(needle in error for error in errors),
                        f"missing expected error fragment {needle!r}; errors={errors!r}",
                    )


if __name__ == "__main__":
    unittest.main()
