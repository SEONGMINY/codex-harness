#!/usr/bin/env python3
"""Regression tests for harness relationship graph export."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
GEN_SCRIPT = HARNESS_DIR / "gen-relationship-graph.py"
sys.path.insert(0, str(HARNESS_DIR))
SPEC = importlib.util.spec_from_file_location("relationship_graph", HARNESS_DIR / "relationship_graph.py")
assert SPEC is not None
RELATIONSHIP_GRAPH = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["relationship_graph"] = RELATIONSHIP_GRAPH
SPEC.loader.exec_module(RELATIONSHIP_GRAPH)


class RelationshipGraphTest(unittest.TestCase):
    def make_task(self, tmp: Path) -> tuple[Path, Path]:
        root = tmp / "repo"
        task_path = root / "tasks" / "demo"
        (root / "docs" / "harness").mkdir(parents=True)
        (task_path / "docs").mkdir(parents=True)
        (task_path / "phases").mkdir(parents=True)
        (task_path / "context-pack" / "static").mkdir(parents=True)
        (task_path / "context-pack" / "runtime").mkdir(parents=True)
        (task_path / "context-pack" / "handoffs").mkdir(parents=True)
        (root / "docs" / "harness" / "implementation-quality.md").write_text("# Quality\n", encoding="utf-8")
        (task_path / "docs" / "implementation-design-review.md").write_text("# Review\n", encoding="utf-8")
        (task_path / "index.json").write_text(
            json.dumps(
                {
                    "project": "demo",
                    "task": "demo",
                    "common_docs": ["docs/harness/implementation-quality.md"],
                    "docs": ["tasks/demo/docs/implementation-design-review.md"],
                    "phases": [{"phase": 0, "name": "implementation", "status": "pending"}],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        for name, payload in {
            "decisions.json": {
                "decisions": [{"id": "D-001", "status": "approved", "summary": "Approved."}]
            },
            "open-decisions.json": {"decisions": []},
            "architecture.json": {
                "nodes": [{"id": "runner", "name": "runner", "responsibility": "Runs phases."}],
                "allowed_edges": [
                    {"id": "A-EDGE-001", "from": "runner", "to": "phase", "reason": "Runner executes phase."}
                ],
                "decisions": [{"id": "A-001", "summary": "Runner owns execution."}],
                "forbid_cycles": True,
            },
            "dependency-policy.json": {
                "new_dependencies": "forbidden",
                "approved_new_dependencies": [],
                "approved_dependency_manifest_changes": [],
            },
            "context-gathering-budget.json": {
                "search_batches": 1,
                "max_files_to_read": 3,
                "stop_when": ["done"],
                "escalate_when": ["unclear"],
            },
            "design-approval.json": {
                "approved": True,
                "approved_doc": "tasks/demo/docs/implementation-design-review.md",
                "approved_doc_sha256": "abc",
            },
        }.items():
            (task_path / "context-pack" / "static" / name).write_text(
                json.dumps(payload) + "\n",
                encoding="utf-8",
            )
        phase_contract = {
            "phase": 0,
            "name": "implementation",
            "read_first": {
                "docs": [
                    "docs/harness/implementation-quality.md",
                    "tasks/demo/docs/implementation-design-review.md",
                ],
                "previous_outputs": [],
            },
            "scope": {"layer": "runner", "allowed_paths": ["scripts/harness/run-phases.py"]},
            "interfaces": [
                {
                    "path": "scripts/harness/run-phases.py",
                    "symbol": "main",
                    "signature": "def main() -> int",
                    "business_rules": ["Runner owns status."],
                }
            ],
            "decision_refs": ["D-001"],
            "architecture_refs": ["A-001"],
            "dependency_policy": {
                "new_dependencies": "forbidden",
                "approved_new_dependencies": [],
                "approved_dependency_manifest_changes": [],
            },
            "instructions": [
                {
                    "id": "P0-001",
                    "task": "Implement the change.",
                    "expected_evidence": ["scripts/harness/run-phases.py"],
                }
            ],
            "success_criteria": ["The runner works."],
            "stop_rules": ["Stop on missing context."],
            "fallback_behavior": {
                "if_blocked": "Write the blocker.",
                "if_tests_fail": "Fix in scope.",
            },
            "validation_budget": {"max_attempts": 1, "command_timeout_seconds": 60},
            "missing_evidence_behavior": "Treat missing evidence as unresolved.",
            "acceptance_commands": ["python3 -m unittest tests.test_relationship_graph"],
            "required_outputs": ["context-pack/handoffs/phase0.md"],
            "required_repo_outputs": ["scripts/harness/run-phases.py"],
            "forbidden": [{"rule": "Do not edit task index.", "reason": "Runner owns status."}],
        }
        (task_path / "phases" / "phase0.md").write_text(
            "# Phase 0\n\n## Contract\n\n```json\n"
            + json.dumps(phase_contract)
            + "\n```\n",
            encoding="utf-8",
        )
        (task_path / "context-pack" / "runtime" / "phase0-result.json").write_text("{}\n", encoding="utf-8")
        (task_path / "context-pack" / "runtime" / "phase0-result-attempt1.json").write_text("{}\n", encoding="utf-8")
        (task_path / "context-pack" / "runtime" / "phase0-attempt-manifest.jsonl").write_text(
            "{}\n",
            encoding="utf-8",
        )
        (task_path / "context-pack" / "runtime" / "phase0-attempt1-commit.json").write_text(
            "{}\n",
            encoding="utf-8",
        )
        (task_path / "context-pack" / "runtime" / "phase0-handoff-attempt1.md").write_text(
            "# Handoff snapshot\n",
            encoding="utf-8",
        )
        (task_path / "context-pack" / "handoffs" / "phase0.md").write_text("# Handoff\n", encoding="utf-8")
        return root, task_path

    def test_graph_links_phase_to_decision_architecture_scope_and_proof(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))

            graph = RELATIONSHIP_GRAPH.graph_from_task(root, task_path)

            edges = {(edge["source"], edge["target"], edge["relation"]) for edge in graph["edges"]}
            self.assertIn(("phase:0", "decision:D-001", "requires_decision"), edges)
            self.assertIn(("phase:0", "architecture-ref:A-001", "requires_architecture"), edges)
            self.assertIn(("phase:0", "path:scripts/harness/run-phases.py", "may_edit"), edges)
            self.assertIn(("phase:0", "runtime:context-pack/runtime/phase0-result.json", "has_runtime_proof"), edges)
            self.assertIn(("phase:0", "runtime:context-pack/runtime/phase0-result-attempt1.json", "has_runtime_proof"), edges)
            self.assertIn(("phase:0", "runtime:context-pack/runtime/phase0-handoff-attempt1.md", "has_runtime_proof"), edges)
            self.assertIn(("phase:0", "runtime:context-pack/runtime/phase0-attempt-manifest.jsonl", "has_runtime_proof"), edges)
            self.assertIn(("phase:0", "runtime:context-pack/runtime/phase0-attempt1-commit.json", "has_runtime_proof"), edges)
            self.assertIn(("architecture:runner", "architecture:phase", "allows_dependency"), edges)

    def test_mermaid_output_contains_relationship_labels(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))

            mermaid = RELATIONSHIP_GRAPH.to_mermaid(RELATIONSHIP_GRAPH.graph_from_task(root, task_path))

            self.assertIn("flowchart LR", mermaid)
            self.assertIn('requires_decision', mermaid)
            self.assertIn('has_runtime_proof', mermaid)

    def test_mermaid_output_uses_unique_node_ids_after_normalization_collisions(self) -> None:
        graph = {
            "nodes": [
                {"id": "path:src/foo-bar.ts", "label": "foo-bar.ts"},
                {"id": "path:src/foo_bar.ts", "label": "foo_bar.ts"},
            ],
            "edges": [
                {"source": "path:src/foo-bar.ts", "target": "path:src/foo_bar.ts", "relation": "related"}
            ],
        }

        mermaid = RELATIONSHIP_GRAPH.to_mermaid(graph)

        self.assertIn('n0["foo-bar.ts"]', mermaid)
        self.assertIn('n1["foo_bar.ts"]', mermaid)
        self.assertIn('n0 -->|"related"| n1', mermaid)

    def test_cli_rejects_absolute_task_path_outside_root_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            external_task = tmp / "external-task"
            external_task.mkdir()
            (external_task / "index.json").write_text(
                json.dumps({"task": "external", "phases": []}) + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(GEN_SCRIPT),
                    str(external_task),
                    "--root",
                    str(root),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("Task directory must be under", result.stderr)

    def test_cli_accepts_root_relative_task_path_from_other_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            outside_cwd = tmp / "outside-cwd"
            outside_cwd.mkdir()

            result = subprocess.run(
                [
                    sys.executable,
                    str(GEN_SCRIPT),
                    "tasks/demo",
                    "--root",
                    str(root),
                ],
                cwd=outside_cwd,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            graph = json.loads(result.stdout)
            task_node = next(node for node in graph["nodes"] if node["id"] == "task:demo")
            self.assertEqual(task_node["metadata"]["path"], "tasks/demo")

    def test_cli_prefers_root_relative_task_path_over_cwd_relative(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            outside_cwd = tmp / "outside-cwd"
            cwd_task = outside_cwd / "tasks" / "demo"
            cwd_task.mkdir(parents=True)
            (cwd_task / "index.json").write_text(
                json.dumps({"task": "wrong-cwd-task", "phases": []}) + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(GEN_SCRIPT),
                    "tasks/demo",
                    "--root",
                    str(root),
                ],
                cwd=outside_cwd,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            graph = json.loads(result.stdout)
            task_node = next(node for node in graph["nodes"] if node["id"] == "task:demo")
            self.assertEqual(task_node["label"], "demo")
            self.assertEqual(task_node["metadata"]["path"], "tasks/demo")

    def test_write_relationship_graph_outputs_writes_runtime_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))

            result = RELATIONSHIP_GRAPH.write_relationship_graph_outputs(root, task_path)

            self.assertEqual(result["status"], "generated")
            self.assertTrue((task_path / "context-pack" / "runtime" / "relationship-graph.json").exists())
            self.assertTrue((task_path / "context-pack" / "runtime" / "relationship-graph.mmd").exists())
            self.assertFalse((task_path / "context-pack" / "runtime" / "relationship-graph-warning.json").exists())

    def test_write_relationship_graph_outputs_warns_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            json_path = task_path / "context-pack" / "runtime" / "relationship-graph.json"
            mermaid_path = task_path / "context-pack" / "runtime" / "relationship-graph.mmd"
            json_path.write_text('{"stale": true}\n', encoding="utf-8")
            mermaid_path.write_text("flowchart LR\n", encoding="utf-8")

            with mock.patch.object(RELATIONSHIP_GRAPH, "graph_from_task", side_effect=ValueError("boom")):
                result = RELATIONSHIP_GRAPH.write_relationship_graph_outputs(root, task_path)

            self.assertEqual(result["status"], "warning")
            self.assertIsNone(result["json"])
            self.assertIsNone(result["mermaid"])
            self.assertFalse(json_path.exists())
            self.assertFalse(mermaid_path.exists())
            warning_path = task_path / "context-pack" / "runtime" / "relationship-graph-warning.json"
            self.assertTrue(warning_path.exists())
            warning = json.loads(warning_path.read_text(encoding="utf-8"))
            self.assertEqual(warning["status"], "warning")

    def test_write_relationship_graph_outputs_warns_when_runtime_path_is_not_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root, task_path = self.make_task(Path(raw_tmp))
            runtime_path = task_path / "context-pack" / "runtime"
            shutil.rmtree(runtime_path)
            runtime_path.write_text("not a directory\n", encoding="utf-8")

            result = RELATIONSHIP_GRAPH.write_relationship_graph_outputs(root, task_path)

            self.assertEqual(result["status"], "warning")
            self.assertIsNone(result["json"])
            self.assertIsNone(result["mermaid"])
            self.assertIsNone(result["warning"])
            self.assertTrue(result["error"])
            self.assertIsNotNone(result["warning_error"])


if __name__ == "__main__":
    unittest.main()
