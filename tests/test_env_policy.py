#!/usr/bin/env python3
"""Regression tests for harness child-process environment minimization."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "harness"))

from env_policy import sanitized_env  # noqa: E402


class EnvPolicyTest(unittest.TestCase):
    def test_policy_pack_override_controls_are_not_inherited(self) -> None:
        env = sanitized_env(
            base={
                "PATH": "/bin",
                "CODEX_HARNESS_ACTIVE": "1",
                "CODEX_HARNESS_UNKNOWN_CONTROL": "unsafe",
                "CODEX_HARNESS_POLICY_PACK": "/tmp/weak.json",
                "CODEX_HARNESS_ALLOW_POLICY_PACK_OVERRIDE": "1",
            }
        )

        self.assertEqual(env["CODEX_HARNESS_ACTIVE"], "1")
        self.assertNotIn("CODEX_HARNESS_UNKNOWN_CONTROL", env)
        self.assertNotIn("CODEX_HARNESS_POLICY_PACK", env)
        self.assertNotIn("CODEX_HARNESS_ALLOW_POLICY_PACK_OVERRIDE", env)

    def test_untrusted_harness_controls_cannot_be_reintroduced_by_overrides(self) -> None:
        env = sanitized_env(
            base={"PATH": "/bin"},
            overrides={
                "CODEX_HARNESS_UNKNOWN_CONTROL": "unsafe",
                "CODEX_HARNESS_POLICY_PACK": "/tmp/weak.json",
                "CODEX_HARNESS_ALLOW_POLICY_PACK_OVERRIDE": "1",
            },
        )

        self.assertNotIn("CODEX_HARNESS_UNKNOWN_CONTROL", env)
        self.assertNotIn("CODEX_HARNESS_POLICY_PACK", env)
        self.assertNotIn("CODEX_HARNESS_ALLOW_POLICY_PACK_OVERRIDE", env)

    def test_policy_pack_override_controls_can_be_explicitly_forwarded_by_harness(self) -> None:
        env = sanitized_env(
            base={"PATH": "/bin"},
            overrides={
                "CODEX_HARNESS_POLICY_PACK": "/trusted/policy.json",
                "CODEX_HARNESS_ALLOW_POLICY_PACK_OVERRIDE": "1",
            },
            allow_harness_policy_controls=True,
        )

        self.assertEqual(env["CODEX_HARNESS_POLICY_PACK"], "/trusted/policy.json")
        self.assertEqual(env["CODEX_HARNESS_ALLOW_POLICY_PACK_OVERRIDE"], "1")

    def test_additional_env_allow_is_not_honored_by_default(self) -> None:
        env = sanitized_env(
            base={
                "PATH": "/bin",
                "CODEX_HARNESS_ENV_ALLOW": "PYTHONPATH",
                "PYTHONPATH": "/tmp/injected",
            }
        )

        self.assertNotIn("CODEX_HARNESS_ENV_ALLOW", env)
        self.assertNotIn("PYTHONPATH", env)

    def test_additional_env_allow_requires_explicit_opt_in(self) -> None:
        env = sanitized_env(
            base={
                "PATH": "/bin",
                "CODEX_HARNESS_ENV_ALLOW": "PYTHONPATH",
                "PYTHONPATH": "/tmp/needed",
            },
            allow_additional_env_names=True,
        )

        self.assertNotIn("CODEX_HARNESS_ENV_ALLOW", env)
        self.assertEqual(env["PYTHONPATH"], "/tmp/needed")


if __name__ == "__main__":
    unittest.main()
