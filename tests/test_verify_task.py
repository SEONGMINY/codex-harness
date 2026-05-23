#!/usr/bin/env python3
"""Regression tests for task verification helpers."""

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
SPEC = importlib.util.spec_from_file_location("verify_task", HARNESS_DIR / "verify-task.py")
assert SPEC is not None
VERIFY_TASK = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VERIFY_TASK)


class VerifyTaskHelperTest(unittest.TestCase):
    def write_minimal_task(self, root: Path, task_path: Path) -> None:
        (root / "docs" / "harness").mkdir(parents=True)
        (root / "docs" / "harness" / "implementation-quality.md").write_text(
            "Implementation quality rules.\n",
            encoding="utf-8",
        )

        docs_dir = task_path / "docs"
        docs_dir.mkdir(parents=True)
        for filename in VERIFY_TASK.MANDATORY_TASK_DOCS:
            (docs_dir / filename).write_text(f"# {filename}\n\nApproved content.\n", encoding="utf-8")

        review_sections = "\n\n".join(
            f"## {section}\n\n- `docs/harness/implementation-quality.md`"
            if section == "Files To Add/Change"
            else (
                "## Mermaid Diagrams\n\n"
                "```mermaid\n"
                "flowchart LR\n"
                "  A[\"task\"] --> B[\"docs\"]\n"
                "```\n"
            )
            if section == "Mermaid Diagrams"
            else f"## {section}\n\nApproved content."
            for section in VERIFY_TASK.DESIGN_REVIEW_REQUIRED_SECTIONS
        )
        (docs_dir / "implementation-design-review.md").write_text(
            f"# Implementation Design Review\n\n{review_sections}\n",
            encoding="utf-8",
        )

        static_dir = task_path / "context-pack" / "static"
        static_dir.mkdir(parents=True)
        static_values = {
            "decisions.json": {
                "decisions": [
                    {"id": "D-001", "status": "approved", "summary": "Approved decision."}
                ]
            },
            "open-decisions.json": {"decisions": []},
            "architecture.json": {
                "nodes": [{"id": "A-001", "name": "docs", "responsibility": "docs"}],
                "allowed_edges": [],
                "decisions": [{"id": "A-001", "summary": "Approved architecture."}],
                "forbid_cycles": True,
            },
            "dependency-policy.json": {
                "new_dependencies": "forbidden",
                "approved_new_dependencies": [],
                "approved_dependency_manifest_changes": [],
            },
            "context-gathering-budget.json": {
                "search_batches": 1,
                "max_files_to_read": 1,
                "stop_when": ["context is sufficient"],
                "escalate_when": ["scope is unclear"],
            },
        }
        for filename in VERIFY_TASK.MANDATORY_STATIC_FILES:
            value = static_values.get(filename)
            path = static_dir / filename
            if value is None:
                path.write_text("Approved content.\n", encoding="utf-8")
            else:
                path.write_text(json.dumps(value) + "\n", encoding="utf-8")

        docs = [
            f"tasks/{task_path.name}/docs/{filename}"
            for filename in VERIFY_TASK.MANDATORY_TASK_DOCS
        ]
        docs.append(f"tasks/{task_path.name}/docs/implementation-design-review.md")
        (task_path / "index.json").write_text(
            json.dumps(
                {
                    "project": "demo",
                    "task": "demo",
                    "docs": docs,
                    "common_docs": ["docs/harness/implementation-quality.md"],
                    "totalPhases": 0,
                    "phases": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )

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

    def test_validate_evaluation_final_requires_approved_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            path = root / "tasks" / "demo" / "context-pack" / "runtime" / "evaluation-last-message.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"verdict":"rejected"}\n', encoding="utf-8")

            self.assertEqual(
                VERIFY_TASK.validate_evaluation_final(root, path),
                ['Evaluation verdict must be "approved": tasks/demo/context-pack/runtime/evaluation-last-message.json'],
            )

    def test_design_approval_requires_matching_hash(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            review_path = task_path / "docs" / "implementation-design-review.md"
            approval_path = task_path / "context-pack" / "static" / "design-approval.json"
            approval_path.parent.mkdir(parents=True)
            review_path.parent.mkdir(parents=True)
            review_path.write_text("# Implementation Design Review\n", encoding="utf-8")
            approval_path.write_text(
                json.dumps(
                    {
                        "approved": True,
                        "approved_doc": "tasks/demo/docs/implementation-design-review.md",
                        "approved_doc_sha256": "stale",
                        "approved_at": "2026-05-22T10:00:00+09:00",
                        "approval_source": "--design-approved",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_design_approval(root, task_path)

            self.assertTrue(any("hash" in error for error in errors), errors)

    def test_design_approval_accepts_current_hash(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            review_path = task_path / "docs" / "implementation-design-review.md"
            approval_path = task_path / "context-pack" / "static" / "design-approval.json"
            approval_path.parent.mkdir(parents=True)
            review_path.parent.mkdir(parents=True)
            review_path.write_text("# Implementation Design Review\n", encoding="utf-8")
            approval_path.write_text(
                json.dumps(
                    {
                        "approved": True,
                        "approved_doc": "tasks/demo/docs/implementation-design-review.md",
                        "approved_doc_sha256": VERIFY_TASK.file_sha256(review_path),
                        "approved_at": "2026-05-22T10:00:00+09:00",
                        "approval_source": "--design-approved",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertEqual(VERIFY_TASK.validate_design_approval(root, task_path), [])

    def test_validate_design_approval_reports_missing_when_required(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            review_path = task_path / "docs" / "implementation-design-review.md"
            review_path.parent.mkdir(parents=True)
            review_path.write_text("# Implementation Design Review\n", encoding="utf-8")

            self.assertEqual(VERIFY_TASK.validate_design_approval(root, task_path), [
                "Missing design approval: tasks/demo/context-pack/static/design-approval.json"
            ])

    def test_verify_without_design_approval_requirement_allows_missing_approval_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)

            errors = VERIFY_TASK.verify(
                root,
                task_path,
                require_evaluation=False,
                require_design_approval=False,
            )

            self.assertEqual(errors, [])

    def test_verify_with_design_approval_requirement_rejects_missing_approval_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)

            errors = VERIFY_TASK.verify(
                root,
                task_path,
                require_evaluation=False,
                require_design_approval=True,
            )

            self.assertEqual(errors, [
                "Missing design approval: tasks/demo/context-pack/static/design-approval.json"
            ])

    def test_extract_design_repo_paths_reads_files_to_change_section(self) -> None:
        text = """# Implementation Design Review

## Files To Add/Change

- `scripts/harness/start.py`: update launcher gate
- tests/test_start.py: add regression tests
- README.md: update overview
"""

        self.assertEqual(
            VERIFY_TASK.extract_design_repo_paths(text),
            ["README.md", "scripts/harness/start.py", "tests/test_start.py"],
        )

    def test_extract_design_repo_paths_ignores_placeholder_tokens(self) -> None:
        text = """# Implementation Design Review

## Files To Add/Change

- None.
- N/A.
- TBD - pending approval
- unknown
- No changes
- Not applicable
"""

        self.assertEqual(VERIFY_TASK.extract_design_repo_paths(text), [])

    def test_extract_design_repo_paths_accepts_known_root_directories(self) -> None:
        text = """# Implementation Design Review

## Files To Add/Change

- src
- docs
- custom-feature/
"""

        self.assertEqual(
            VERIFY_TASK.extract_design_repo_paths(text),
            ["custom-feature", "docs", "src"],
        )

    def test_extract_design_repo_paths_normalizes_trailing_punctuation(self) -> None:
        text = """# Implementation Design Review

## Files To Add/Change

- README.md.
- `package.json;`
- scripts/harness/start.py,
"""

        self.assertEqual(
            VERIFY_TASK.extract_design_repo_paths(text),
            ["README.md", "package.json", "scripts/harness/start.py"],
        )

    def test_contract_consistency_rejects_scope_outside_design_paths(self) -> None:
        contract = {
            "scope": {
                "layer": "runner",
                "allowed_paths": ["scripts/harness/start.py", "scripts/harness/run-phases.py"],
            },
            "required_repo_outputs": ["scripts/harness/start.py"],
        }

        errors = VERIFY_TASK.validate_contract_against_design(
            Path("/repo"),
            Path("/repo/tasks/demo"),
            0,
            contract,
            "review",
            ["scripts/harness/start.py"],
        )

        self.assertTrue(any("scope.allowed_paths" in error for error in errors), errors)

    def test_contract_consistency_accepts_paths_inside_design_paths(self) -> None:
        contract = {
            "scope": {
                "layer": "runner",
                "allowed_paths": ["scripts/harness/*.py"],
            },
            "required_repo_outputs": ["scripts/harness/start.py"],
        }

        errors = VERIFY_TASK.validate_contract_against_design(
            Path("/repo"),
            Path("/repo/tasks/demo"),
            0,
            contract,
            "review",
            ["scripts/harness/"],
        )

        self.assertEqual(errors, [])

    def test_contract_consistency_accepts_root_files(self) -> None:
        contract = {
            "scope": {
                "layer": "runner",
                "allowed_paths": ["README.md"],
            },
            "required_repo_outputs": ["README.md"],
        }

        errors = VERIFY_TASK.validate_contract_against_design(
            Path("/repo"),
            Path("/repo/tasks/demo"),
            0,
            contract,
            "review",
            ["README.md"],
        )

        self.assertEqual(errors, [])

    def test_contract_consistency_rejects_different_glob_without_directory_approval(self) -> None:
        contract = {
            "scope": {
                "layer": "runner",
                "allowed_paths": ["scripts/harness/*.py"],
            },
            "required_repo_outputs": ["scripts/harness/start.py"],
        }

        errors = VERIFY_TASK.validate_contract_against_design(
            Path("/repo"),
            Path("/repo/tasks/demo"),
            0,
            contract,
            "review",
            ["scripts/harness/**/*.py"],
        )

        self.assertTrue(any("scope.allowed_paths" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
