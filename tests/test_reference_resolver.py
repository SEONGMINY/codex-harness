"""Regression tests for typed harness reference resolution."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))

from reference_resolver import ReferenceUniverse, resolve_reference  # noqa: E402


class ReferenceResolverTest(unittest.TestCase):
    def test_resolves_typed_static_refs_and_legacy_path_aliases(self) -> None:
        universe = ReferenceUniverse()
        universe.add("section", "Transaction Boundaries")
        universe.add("design", "txn.pending-removal", source="transaction_boundaries")
        universe.add_path("docs/harness/implementation-quality.md", source="approved_path")

        section_ref, section_error = resolve_reference("section:Transaction Boundaries", universe)
        design_ref, design_error = resolve_reference("design:txn.pending-removal", universe)
        path_ref, path_error = resolve_reference("path:docs/harness/implementation-quality.md", universe)
        legacy_ref, legacy_error = resolve_reference("docs/harness/implementation-quality.md", universe)

        self.assertIsNone(section_error)
        self.assertEqual(section_ref.canonical, "section:Transaction Boundaries")
        self.assertIsNone(design_error)
        self.assertEqual(design_ref.canonical, "design:txn.pending-removal")
        self.assertEqual(design_ref.metadata, {"source": "transaction_boundaries"})
        self.assertIsNone(path_error)
        self.assertEqual(path_ref.canonical, "path:docs/harness/implementation-quality.md")
        self.assertEqual(path_ref.metadata, {"source": "approved_path"})
        self.assertIsNone(legacy_error)
        self.assertEqual(legacy_ref.canonical, "path:docs/harness/implementation-quality.md")
        self.assertTrue(legacy_ref.legacy)

    def test_rejects_unknown_or_unsafe_refs(self) -> None:
        universe = ReferenceUniverse()
        universe.add("section", "API Contract")

        for raw_ref in [
            "section:Missing",
            "path:../secret.txt",
            "/tmp/output.txt",
            "https://example.com/design",
            "path:docs/.env",
            "decision:../D-001",
        ]:
            with self.subTest(raw_ref=raw_ref):
                resolved, error = resolve_reference(raw_ref, universe)
                self.assertIsNone(resolved)
                self.assertIsNotNone(error)

    def test_allows_security_domain_words_in_non_path_ids(self) -> None:
        universe = ReferenceUniverse()
        universe.add("design", "pending-token-removal")
        universe.add("design", "secret_sdk_boundary")

        for raw_ref in ["design:pending-token-removal", "design:secret_sdk_boundary"]:
            with self.subTest(raw_ref=raw_ref):
                resolved, error = resolve_reference(raw_ref, universe)
                self.assertIsNone(error)
                self.assertEqual(resolved.raw, raw_ref)

    def test_redacts_unsafe_refs_in_errors(self) -> None:
        universe = ReferenceUniverse()

        resolved, error = resolve_reference("path:docs/.env", universe)

        self.assertIsNone(resolved)
        self.assertIn("[redacted-ref]", error)
        self.assertNotIn(".env", error)


if __name__ == "__main__":
    unittest.main()
