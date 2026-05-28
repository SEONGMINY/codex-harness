#!/usr/bin/env python3
"""Regression tests for design approval policy lineage semantics."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))

import policy_lineage  # noqa: E402


ACTIVE = {"id": "default-security", "schema_version": "1", "sha256": "a" * 64}
OLD = {"id": "default-security", "schema_version": "1", "sha256": "b" * 64}
NEW = {"id": "default-security", "schema_version": "1", "sha256": "c" * 64}


class PolicyLineageTest(unittest.TestCase):
    def test_duplicate_fingerprint_is_rejected(self) -> None:
        _, errors = policy_lineage.normalize_policy_pack_fingerprints(
            [ACTIVE, dict(ACTIVE)],
            "lineage",
        )

        self.assertTrue(any("duplicates" in error for error in errors), errors)

    def test_revoked_entries_require_reason_and_are_excluded(self) -> None:
        entries, errors = policy_lineage.normalize_policy_pack_lineage_entries(
            [
                {**ACTIVE, "status": "active"},
                {**OLD, "status": "revoked", "revocation_reason": "Known bad policy.", "replacement_policy_pack": ACTIVE},
            ],
            "lineage",
            ACTIVE,
        )

        self.assertEqual(errors, [])
        self.assertEqual(policy_lineage.allowed_policy_fingerprints(entries), [ACTIVE])

    def test_revoked_entry_without_reason_is_rejected(self) -> None:
        _, errors = policy_lineage.normalize_policy_pack_lineage_entries(
            [{**OLD, "status": "revoked"}],
            "lineage",
            ACTIVE,
        )

        self.assertTrue(any("revocation_reason is required" in error for error in errors), errors)

    def test_active_policy_pack_must_not_be_revoked(self) -> None:
        _, errors = policy_lineage.normalize_policy_pack_lineage_entries(
            [{**ACTIVE, "status": "revoked", "revocation_reason": "bad"}],
            "lineage",
            ACTIVE,
        )

        self.assertTrue(any("active_policy_pack entry must not be revoked" in error for error in errors), errors)

    def test_current_policy_must_match_active_design_approval_policy(self) -> None:
        approval = {
            "schema_version": 3,
            "active_policy_pack": ACTIVE,
            "approved_policy_packs": [
                {**OLD, "status": "historical"},
                {**ACTIVE, "status": "active"},
            ],
        }

        errors = policy_lineage.validate_current_policy_lineage(
            approval,
            NEW,
            action_label="running evaluation",
        )

        self.assertTrue(any("does not match design approval active_policy_pack" in error for error in errors), errors)

    def test_design_scope_hash_includes_lineage_status(self) -> None:
        bundle = [{"path": "tasks/demo/docs/implementation-design-review.md", "sha256": "d" * 64}]
        historical = policy_lineage.design_approval_scope_sha256(
            bundle,
            [ACTIVE],
            ACTIVE,
            [{**ACTIVE, "status": "historical"}],
        )
        active = policy_lineage.design_approval_scope_sha256(
            bundle,
            [ACTIVE],
            ACTIVE,
            [{**ACTIVE, "status": "active"}],
        )

        self.assertNotEqual(historical, active)


if __name__ == "__main__":
    unittest.main()
