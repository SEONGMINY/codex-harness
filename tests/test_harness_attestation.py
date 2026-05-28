#!/usr/bin/env python3
"""Regression tests for harness runtime attestation helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))

import harness_attestation  # noqa: E402


class HarnessAttestationTest(unittest.TestCase):
    def test_current_attestation_has_stable_runtime_profile(self) -> None:
        attestation = harness_attestation.harness_attestation()

        self.assertEqual(attestation["schema_version"], 1)
        self.assertEqual(attestation["profile"], "runtime-proof")
        self.assertEqual(attestation["hash_algorithm"], "sha256")
        self.assertEqual(
            attestation["digest"],
            harness_attestation.stable_json_sha256(attestation["entries"]),
        )
        paths = [item["path"] for item in attestation["entries"]]
        self.assertEqual(paths, sorted(paths))
        self.assertIn("harness:run-phases.py", paths)
        self.assertIn("harness:verify-task.py", paths)
        self.assertIn("harness:policy-packs/default-security.json", paths)
        self.assertNotIn("harness:start.py", paths)

    def test_fingerprint_rejects_entry_tamper(self) -> None:
        attestation = dict(harness_attestation.harness_attestation())
        entries = [dict(item) for item in attestation["entries"]]
        entries[0]["sha256"] = "tampered"
        attestation["entries"] = entries

        self.assertIsNone(harness_attestation.attestation_fingerprint(attestation))


if __name__ == "__main__":
    unittest.main()
