#!/usr/bin/env python3
"""Regression tests for task verification helpers."""

from __future__ import annotations

import importlib.util
import json
import subprocess
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
START_SPEC = importlib.util.spec_from_file_location("harness_start", HARNESS_DIR / "start.py")
assert START_SPEC is not None
HARNESS_START = importlib.util.module_from_spec(START_SPEC)
assert START_SPEC.loader is not None
START_SPEC.loader.exec_module(HARNESS_START)
from design_contract import DEFAULT_REVIEW_TAXONOMY_IDS, validate_review_coverage, validate_review_findings  # noqa: E402


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
            "design-contract.json": {
                "schema_version": "1",
                "approved_paths": ["docs/harness/implementation-quality.md"],
                "decision_refs": ["D-001"],
                "open_decision_refs": [],
                "architecture_refs": ["A-001"],
                "obligations": [],
                "state_transitions": [],
                "transaction_boundaries": [],
                "retry_triggers": [],
                "external_environment_mappings": [],
                "artifact_persistence": {
                    "required_paths": [
                        {
                            "id": "artifact.static_context",
                            "path": f"tasks/{task_path.name}/context-pack/static/design-contract.json",
                            "reason": "Design contract must be persisted with task context.",
                        }
                    ]
                },
            },
            "review-taxonomy.json": {
                "checks": [
                    {
                        "id": check_id,
                        "title": check_id.replace("_", " "),
                        "review_prompt": f"Review {check_id}.",
                    }
                    for check_id in DEFAULT_REVIEW_TAXONOMY_IDS
                ]
            },
            "review-findings.json": {
                "findings": [
                    {
                        "taxonomy_id": "concurrency_atomicity",
                        "status": "na",
                        "evidence": "Minimal test task has no state mutation phase.",
                        "rationale": "No implementation phase exists in this fixture.",
                    },
                    {
                        "taxonomy_id": "lifecycle_trigger_completeness",
                        "status": "na",
                        "evidence": "Minimal test task has no lifecycle trigger.",
                        "rationale": "No implementation phase exists in this fixture.",
                    },
                    {
                        "taxonomy_id": "decision_approval_leakage",
                        "status": "pass",
                        "evidence": "Approved decision registry is present.",
                        "evidence_refs": ["decision:D-001"],
                    },
                    {
                        "taxonomy_id": "artifact_persistence",
                        "status": "pass",
                        "evidence": "Design contract persists required static context.",
                        "evidence_refs": [
                            "design:artifact.static_context",
                            "path:docs/harness/implementation-quality.md",
                        ],
                    },
                    {
                        "taxonomy_id": "acceptance_validity",
                        "status": "na",
                        "evidence": "Minimal test task has no phase acceptance command.",
                        "rationale": "No implementation phase exists in this fixture.",
                    },
                    {
                        "taxonomy_id": "implementation_traceability",
                        "status": "na",
                        "evidence": "Minimal test task has no implementation phase.",
                        "rationale": "No implementation phase exists in this fixture.",
                    },
                    {
                        "taxonomy_id": "rollback_idempotency",
                        "status": "na",
                        "evidence": "Minimal test task has no write/retry behavior.",
                        "rationale": "No implementation phase exists in this fixture.",
                    },
                    {
                        "taxonomy_id": "dependency_direction",
                        "status": "pass",
                        "evidence": "Architecture registry is present.",
                        "evidence_refs": ["architecture:A-001"],
                    },
                ]
            },
            "review-coverage.json": {
                "schema_version": "1",
                "taxonomy_coverage": [
                    {
                        "taxonomy_id": "concurrency_atomicity",
                        "status": "not_applicable",
                        "rationale": "No state mutation phase exists in this fixture.",
                    },
                    {
                        "taxonomy_id": "lifecycle_trigger_completeness",
                        "status": "not_applicable",
                        "rationale": "No lifecycle trigger exists in this fixture.",
                    },
                    {
                        "taxonomy_id": "decision_approval_leakage",
                        "status": "checked",
                        "evidence_refs": ["decision:D-001"],
                    },
                    {
                        "taxonomy_id": "artifact_persistence",
                        "status": "checked",
                        "evidence_refs": ["design:artifact.static_context"],
                    },
                    {
                        "taxonomy_id": "acceptance_validity",
                        "status": "not_applicable",
                        "rationale": "No phase acceptance command exists in this fixture.",
                    },
                    {
                        "taxonomy_id": "implementation_traceability",
                        "status": "not_applicable",
                        "rationale": "No implementation phase exists in this fixture.",
                    },
                    {
                        "taxonomy_id": "rollback_idempotency",
                        "status": "not_applicable",
                        "rationale": "No write/retry behavior exists in this fixture.",
                    },
                    {
                        "taxonomy_id": "dependency_direction",
                        "status": "checked",
                        "evidence_refs": ["architecture:A-001"],
                    },
                ],
                "obligation_coverage": [],
                "assumptions": [],
                "residual_risks": [],
            },
            "traceability-matrix.json": {"entries": []},
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

    def write_design_approval(self, root: Path, task_path: Path, *, approved_doc_sha256: str | None = None) -> None:
        info = VERIFY_TASK.design_doc_info(root, task_path)
        self.assertIsNotNone(info)
        assert info is not None
        design_path, design_rel_path, _ = info
        bundle, bundle_errors = VERIFY_TASK.design_approval_bundle_entries(root, task_path, design_rel_path)
        self.assertEqual(bundle_errors, [])
        approved_policy_packs = VERIFY_TASK.sort_policy_pack_fingerprints(
            [VERIFY_TASK.current_policy_pack_fingerprint()]
        )
        active_policy_pack = approved_policy_packs[0]
        approval_path = task_path / "context-pack" / "static" / "design-approval.json"
        approval_path.parent.mkdir(parents=True, exist_ok=True)
        approval_path.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "approved": True,
                    "approved_doc": design_rel_path,
                    "approved_doc_sha256": approved_doc_sha256 or VERIFY_TASK.file_sha256(design_path),
                    "approved_bundle": bundle,
                    "approved_bundle_sha256": VERIFY_TASK.design_approval_bundle_sha256(bundle),
                    "active_policy_pack": active_policy_pack,
                    "approved_policy_packs": approved_policy_packs,
                    "approved_policy_packs_sha256": VERIFY_TASK.policy_pack_lineage_sha256(approved_policy_packs),
                    "design_approval_scope_sha256": VERIFY_TASK.design_approval_scope_sha256(
                        bundle,
                        approved_policy_packs,
                        active_policy_pack,
                        [{**active_policy_pack, "status": "active"}],
                    ),
                    "approved_at": "2026-05-22T10:00:00+09:00",
                    "approval_source": "--design-approved",
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def write_evaluation_artifacts(self, task_path: Path) -> None:
        runtime_dir = task_path / "context-pack" / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        approval = json.loads(
            (task_path / "context-pack" / "static" / "design-approval.json").read_text(encoding="utf-8")
        )
        (runtime_dir / "evaluation-command-results.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "policy_pack": VERIFY_TASK.policy_pack_metadata(),
                    "harness_attestation": VERIFY_TASK.harness_attestation(),
                    "design_approval_scope_sha256": approval["design_approval_scope_sha256"],
                    "commands": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (runtime_dir / "evaluation-prompt.md").write_text("Evaluate this task.\n", encoding="utf-8")
        (runtime_dir / "evaluation-output.jsonl").write_text('{"event":"done"}\n', encoding="utf-8")
        (runtime_dir / "evaluation-stderr.txt").write_text("", encoding="utf-8")
        (runtime_dir / "evaluation-last-message.json").write_text(
            json.dumps({"verdict": "approved", "blockers": [], "required_followups": []}) + "\n",
            encoding="utf-8",
        )
        evaluation_artifacts = []
        for name, filename in [
            ("command_results", "evaluation-command-results.json"),
            ("prompt", "evaluation-prompt.md"),
            ("output", "evaluation-output.jsonl"),
            ("stderr", "evaluation-stderr.txt"),
            ("last_message", "evaluation-last-message.json"),
        ]:
            path = runtime_dir / filename
            evaluation_artifacts.append(
                {
                    "name": name,
                    "path": f"context-pack/runtime/{filename}",
                    "exists": True,
                    "sha256": VERIFY_TASK.file_sha256(path),
                }
            )
        (runtime_dir / "evaluation-commit.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "commit_scope": "evaluation_bundle",
                    "status": "committed",
                    "verdict": "approved",
                    "evaluated_at": "2026-05-22T10:00:00+09:00",
                    "policy_pack": VERIFY_TASK.policy_pack_metadata(),
                    "harness_attestation": VERIFY_TASK.harness_attestation(),
                    "design_approval_scope_sha256": approval["design_approval_scope_sha256"],
                    "task_index": {
                        "name": "task_index",
                        "path": "index.json",
                        "exists": True,
                        "sha256": VERIFY_TASK.file_sha256(task_path / "index.json"),
                    },
                    "phase_proofs": [],
                    "repair_proofs": [],
                    "evaluation_artifacts": evaluation_artifacts,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def write_evaluation_repair_result(
        self,
        root: Path,
        task_path: Path,
        *,
        repo_content: dict[str, object],
        status: str = "completed",
        codex_exit_code: int = 0,
        scope_violations: list[str] | None = None,
        handoff_exists: bool = True,
        changed_files: list[str] | None = None,
        allowed_paths: list[str] | None = None,
        last_message_status: str = "completed",
    ) -> None:
        runtime_dir = task_path / "context-pack" / "runtime"
        handoff_dir = task_path / "context-pack" / "handoffs"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        handoff_dir.mkdir(parents=True, exist_ok=True)
        artifacts = {
            "prompt": runtime_dir / "evaluation-repair1-prompt.md",
            "stdout": runtime_dir / "evaluation-repair1-output.jsonl",
            "stderr": runtime_dir / "evaluation-repair1-stderr.txt",
            "last_message": runtime_dir / "evaluation-repair1-last-message.json",
        }
        for name, path in artifacts.items():
            if name == "last_message":
                path.write_text(
                    json.dumps(
                        {
                            "status": last_message_status,
                            "handoff_path": f"tasks/{task_path.name}/context-pack/handoffs/evaluation-repair1.md",
                            "changed_files": [],
                            "checks_run": [],
                            "remaining_risks": [],
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
            else:
                path.write_text(f"{name}\n", encoding="utf-8")
        handoff = handoff_dir / "evaluation-repair1.md"
        if handoff_exists:
            handoff.write_text("repair handoff\n", encoding="utf-8")
        if changed_files is None:
            changed_files = VERIFY_TASK.repo_content_changed_paths(repo_content)
        if allowed_paths is None:
            allowed_paths = changed_files[:]
        artifact_paths = {**artifacts, "handoff": handoff}
        artifact_refs = []
        for name, path in artifact_paths.items():
            entry: dict[str, object] = {
                "name": name,
                "path": str(path.relative_to(task_path)),
                "exists": path.exists(),
            }
            if path.exists() and path.is_file():
                entry["sha256"] = VERIFY_TASK.file_sha256(path)
            artifact_refs.append(entry)
        (runtime_dir / "evaluation-repair1-result.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "runner_version": VERIFY_TASK.HARNESS_VERSION,
                    "repair_scope": "evaluation_improvement",
                    "iteration": 1,
                    "status": status,
                    "codex_exit_code": codex_exit_code,
                    "changed_files": changed_files,
                    "allowed_paths": allowed_paths,
                    "scope_violations": scope_violations or [],
                    "handoff": str(handoff.relative_to(task_path)),
                    "handoff_exists": handoff_exists,
                    "repo_content": repo_content,
                    "policy_pack": VERIFY_TASK.policy_pack_metadata(),
                    "harness_attestation": VERIFY_TASK.harness_attestation(),
                    "artifacts": {
                        name: str(path.relative_to(task_path))
                        for name, path in artifacts.items()
                    },
                    "artifact_refs": artifact_refs,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def write_phase_runtime_bundle(
        self,
        task_path: Path,
        *,
        phase_number: int = 0,
        attempt: int = 1,
        handoff_text: str = "Completed.\n",
        evidence_state: dict[str, object] | None = None,
        gate_state: dict[str, object] | None = None,
        gate_checks: list[dict[str, object]] | None = None,
        gate_check_status: str = "passed",
    ) -> None:
        runtime_dir = task_path / "context-pack" / "runtime"
        handoff_dir = task_path / "context-pack" / "handoffs"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        handoff_dir.mkdir(parents=True, exist_ok=True)
        contract = {
            "phase": phase_number,
            "instructions": [],
            "scope": {"allowed_paths": []},
            "acceptance_commands": [],
            "required_outputs": [],
            "required_repo_outputs": [],
        }
        recomputed_state = VERIFY_TASK.classify_handoff_text(handoff_text)
        if evidence_state is None:
            evidence_state = {**recomputed_state, "path": f"context-pack/handoffs/phase{phase_number}.md"}
        if gate_state is None:
            gate_state = evidence_state.copy()
        if gate_checks is None:
            gate_checks = [
                {
                    "name": "handoff_status",
                    "status": gate_check_status,
                    "handoff_state": gate_state,
                }
            ]
        files = {
            f"phase{phase_number}-contract-attempt{attempt}.json": contract,
            f"phase{phase_number}-evidence-attempt{attempt}.json": {
                "commands": [],
                "required_outputs": [],
                "required_repo_outputs": [],
                "changed_files": [],
                "handoff_state": evidence_state,
            },
            f"phase{phase_number}-reconciliation-attempt{attempt}.json": {
                "status": "satisfied",
                "instruction_results": [],
            },
            f"phase{phase_number}-gate-attempt{attempt}.json": {
                "status": "passed",
                "checks": gate_checks,
            },
            f"phase{phase_number}-quality-attempt{attempt}.json": {
                "status": "passed",
                "checks": [],
            },
        }
        for filename, value in files.items():
            (runtime_dir / filename).write_text(json.dumps(value) + "\n", encoding="utf-8")
        (runtime_dir / f"phase{phase_number}-handoff-attempt{attempt}.md").write_text(
            handoff_text,
            encoding="utf-8",
        )
        (handoff_dir / f"phase{phase_number}.md").write_text("Completed alias.\n", encoding="utf-8")

    def validate_phase_runtime_bundle(self, root: Path, task_path: Path) -> list[str]:
        return VERIFY_TASK.validate_runtime_contract_bundle(root, task_path, 0, [], [], [], expected_attempt=1)

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

    def test_validate_evaluation_final_rejects_approved_with_open_work(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            path = root / "tasks" / "demo" / "context-pack" / "runtime" / "evaluation-last-message.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "verdict": "approved",
                        "blockers": [],
                        "required_followups": ["Fix residual issue."],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_evaluation_final(root, path)

            self.assertTrue(any("required_followups" in error for error in errors), errors)

    def test_runtime_bundle_accepts_consistent_completed_handoff_proof(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_phase_runtime_bundle(task_path)

            self.assertEqual(self.validate_phase_runtime_bundle(root, task_path), [])

    def test_runtime_bundle_rejects_blocking_canonical_handoff_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            stale_complete = VERIFY_TASK.classify_handoff_text("Completed.\n")
            self.write_phase_runtime_bundle(
                task_path,
                handoff_text="Status: partial\n\nSome required proof is missing.\n",
                evidence_state=stale_complete,
                gate_state=stale_complete,
            )

            errors = self.validate_phase_runtime_bundle(root, task_path)

            self.assertTrue(any("canonical handoff snapshot reports blocking" in error for error in errors), errors)
            self.assertTrue(any("evidence.handoff_state does not match" in error for error in errors), errors)
            self.assertTrue(
                any("gate handoff_status.handoff_state does not match" in error for error in errors),
                errors,
            )

    def test_runtime_bundle_rejects_missing_completed_handoff_evidence_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_phase_runtime_bundle(task_path)
            evidence_path = task_path / "context-pack" / "runtime" / "phase0-evidence-attempt1.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence.pop("handoff_state")
            evidence_path.write_text(json.dumps(evidence) + "\n", encoding="utf-8")

            errors = self.validate_phase_runtime_bundle(root, task_path)

            self.assertTrue(any("missing evidence.handoff_state" in error for error in errors), errors)

    def test_runtime_bundle_rejects_missing_handoff_status_gate_check(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_phase_runtime_bundle(task_path, gate_checks=[])

            errors = self.validate_phase_runtime_bundle(root, task_path)

            self.assertTrue(any("exactly one gate check named handoff_status" in error for error in errors), errors)

    def test_runtime_bundle_rejects_duplicate_handoff_status_gate_checks(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            state = VERIFY_TASK.classify_handoff_text("Completed.\n")
            self.write_phase_runtime_bundle(
                task_path,
                gate_checks=[
                    {"name": "handoff_status", "status": "passed", "handoff_state": state},
                    {"name": "handoff_status", "status": "passed", "handoff_state": state},
                ],
            )

            errors = self.validate_phase_runtime_bundle(root, task_path)

            self.assertTrue(any("found 2" in error for error in errors), errors)

    def test_runtime_bundle_rejects_gate_handoff_status_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_phase_runtime_bundle(task_path, gate_check_status="failed")

            errors = self.validate_phase_runtime_bundle(root, task_path)

            self.assertTrue(any("gate handoff_status.status must be 'passed'" in error for error in errors), errors)

    def test_runtime_bundle_uses_snapshot_not_mutable_handoff_alias_for_completion_proof(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_phase_runtime_bundle(task_path, handoff_text="Completed.\n")
            alias = task_path / "context-pack" / "handoffs" / "phase0.md"
            alias.write_text("Status: blocked\n\nAlias changed after attempt.\n", encoding="utf-8")

            self.assertEqual(self.validate_phase_runtime_bundle(root, task_path), [])

    def test_evaluation_command_results_accepts_policy_lineage_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            self.write_design_approval(root, task_path)
            runtime_dir = task_path / "context-pack" / "runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            approval = json.loads(
                (task_path / "context-pack" / "static" / "design-approval.json").read_text(encoding="utf-8")
            )
            path = runtime_dir / "evaluation-command-results.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "policy_pack": VERIFY_TASK.policy_pack_metadata(),
                        "harness_attestation": VERIFY_TASK.harness_attestation(),
                        "design_approval_scope_sha256": approval["design_approval_scope_sha256"],
                        "commands": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            lineage, lineage_errors = VERIFY_TASK.approved_policy_pack_lineage(root, task_path)
            self.assertEqual(lineage_errors, [])
            errors = VERIFY_TASK.validate_evaluation_command_results(
                root,
                task_path,
                path,
                approved_policy_packs=lineage,
            )

            self.assertEqual(errors, [])

    def test_verify_rejects_symlink_static_context(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root = tmp / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            outside = tmp / "secret.md"
            outside.write_text("SECRET\n", encoding="utf-8")
            context = task_path / "context-pack" / "static" / "original-prompt.md"
            context.unlink()
            context.symlink_to(outside)

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("Unsafe static context symlink" in error for error in errors), errors)
            self.assertFalse(any("SECRET" in error for error in errors), errors)

    def test_evaluation_command_results_rejects_policy_outside_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            self.write_design_approval(root, task_path)
            runtime_dir = task_path / "context-pack" / "runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            approval = json.loads(
                (task_path / "context-pack" / "static" / "design-approval.json").read_text(encoding="utf-8")
            )
            stale_policy = VERIFY_TASK.policy_pack_metadata()
            stale_policy["sha256"] = "stale"
            path = runtime_dir / "evaluation-command-results.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "policy_pack": stale_policy,
                        "harness_attestation": VERIFY_TASK.harness_attestation(),
                        "design_approval_scope_sha256": approval["design_approval_scope_sha256"],
                        "commands": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            lineage, lineage_errors = VERIFY_TASK.approved_policy_pack_lineage(root, task_path)
            self.assertEqual(lineage_errors, [])
            errors = VERIFY_TASK.validate_evaluation_command_results(
                root,
                task_path,
                path,
                approved_policy_packs=lineage,
            )

            self.assertTrue(any("design-approved policy pack lineage" in error for error in errors), errors)

    def test_evaluation_command_results_rejects_legacy_list_when_scope_is_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            self.write_design_approval(root, task_path)
            runtime_dir = task_path / "context-pack" / "runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            path = runtime_dir / "evaluation-command-results.json"
            path.write_text("[]\n", encoding="utf-8")

            errors = VERIFY_TASK.validate_evaluation_command_results(root, task_path, path)

            self.assertTrue(any("schema_version 1 metadata object" in error for error in errors), errors)

    def test_design_approval_requires_matching_hash(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            self.write_design_approval(root, task_path, approved_doc_sha256="stale")

            errors = VERIFY_TASK.validate_design_approval(root, task_path)

            self.assertTrue(any("hash" in error for error in errors), errors)

    def test_design_approval_accepts_current_hash(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            self.write_design_approval(root, task_path)

            self.assertEqual(VERIFY_TASK.validate_design_approval(root, task_path), [])

    def test_design_approval_rejects_static_bundle_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            self.write_design_approval(root, task_path)
            (task_path / "context-pack" / "static" / "design-contract.json").write_text(
                '{"schema_version":"1","approved_paths":[]}\n',
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_design_approval(root, task_path)

            self.assertTrue(any("approved static evidence bundle" in error for error in errors), errors)

    def test_launcher_design_approval_matches_verifier_bundle_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)

            HARNESS_START.write_design_approval(root, task_path)

            approval_path = task_path / "context-pack" / "static" / "design-approval.json"
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            bundle_paths = {entry["path"] for entry in approval["approved_bundle"]}
            self.assertIn("tasks/demo/context-pack/static/review-findings.json", bundle_paths)
            self.assertIn("tasks/demo/context-pack/static/review-coverage.json", bundle_paths)
            self.assertNotIn("tasks/demo/context-pack/static/risk-ledger.json", bundle_paths)
            self.assertEqual(VERIFY_TASK.validate_design_approval(root, task_path), [])

    def test_design_approval_rejects_unsafe_bundle_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            self.write_design_approval(root, task_path)
            approval_path = task_path / "context-pack" / "static" / "design-approval.json"
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            approval["approved_bundle"][0]["path"] = "../implementation-design-review.md"
            approval["approved_bundle_sha256"] = VERIFY_TASK.design_approval_bundle_sha256(approval["approved_bundle"])
            approval_path.write_text(json.dumps(approval) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.validate_design_approval(root, task_path)

            self.assertTrue(any("repo-relative path" in error for error in errors), errors)

    def test_design_approval_requires_static_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            info = VERIFY_TASK.design_doc_info(root, task_path)
            self.assertIsNotNone(info)
            assert info is not None
            design_path, design_rel_path, _ = info
            approval_path = task_path / "context-pack" / "static" / "design-approval.json"
            approval_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "approved": True,
                        "approved_doc": design_rel_path,
                        "approved_doc_sha256": VERIFY_TASK.file_sha256(design_path),
                        "approved_at": "2026-05-22T10:00:00+09:00",
                        "approval_source": "--design-approved",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_design_approval(root, task_path)

            self.assertTrue(any("approved_bundle" in error for error in errors), errors)

    def test_design_approval_v3_requires_policy_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            info = VERIFY_TASK.design_doc_info(root, task_path)
            self.assertIsNotNone(info)
            assert info is not None
            design_path, design_rel_path, _ = info
            bundle, bundle_errors = VERIFY_TASK.design_approval_bundle_entries(root, task_path, design_rel_path)
            self.assertEqual(bundle_errors, [])
            approval_path = task_path / "context-pack" / "static" / "design-approval.json"
            approval_path.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "approved": True,
                        "approved_doc": design_rel_path,
                        "approved_doc_sha256": VERIFY_TASK.file_sha256(design_path),
                        "approved_bundle": bundle,
                        "approved_bundle_sha256": VERIFY_TASK.design_approval_bundle_sha256(bundle),
                        "approved_at": "2026-05-22T10:00:00+09:00",
                        "approval_source": "--design-approved",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_design_approval(root, task_path)

            self.assertTrue(any("approved_policy_packs" in error for error in errors), errors)

    def test_strict_current_rejects_legacy_design_approval_schema(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            self.write_design_approval(root, task_path)
            approval_path = task_path / "context-pack" / "static" / "design-approval.json"
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            approval["schema_version"] = 2
            approval.pop("approved_policy_packs", None)
            approval.pop("approved_policy_packs_sha256", None)
            approval.pop("design_approval_scope_sha256", None)
            approval_path.write_text(json.dumps(approval) + "\n", encoding="utf-8")

            self.assertEqual(VERIFY_TASK.validate_design_approval(root, task_path), [])
            errors = VERIFY_TASK.validate_design_approval(root, task_path, strict_current_harness=True)

            self.assertTrue(any("schema_version` 3" in error for error in errors), errors)

    def test_ac_results_metadata_rejects_phase_policy_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            runtime_dir.mkdir(parents=True)
            stale_policy = VERIFY_TASK.policy_pack_metadata()
            stale_policy["sha256"] = "stale"
            (runtime_dir / "phase0-ac-attempt1.json").write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "policy_pack": stale_policy,
                        "commands": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_ac_results_metadata(
                root,
                task_path,
                0,
                1,
                {"ac_results": "context-pack/runtime/phase0-ac-attempt1.json"},
                VERIFY_TASK.policy_pack_metadata(),
            )

            self.assertTrue(any("policy_pack" in error for error in errors), errors)

    def test_ac_results_metadata_rejects_policy_outside_approved_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            runtime_dir.mkdir(parents=True)
            current = VERIFY_TASK.current_policy_pack_fingerprint()
            stale_policy = dict(VERIFY_TASK.policy_pack_metadata())
            stale_policy["sha256"] = "stale"
            (runtime_dir / "phase0-ac-attempt1.json").write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "policy_pack": stale_policy,
                        "commands": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_ac_results_metadata(
                root,
                task_path,
                0,
                1,
                {"ac_results": "context-pack/runtime/phase0-ac-attempt1.json"},
                stale_policy,
                approved_policy_packs=[current],
            )

            self.assertTrue(any("design-approved policy pack lineage" in error for error in errors), errors)

    def test_ac_results_metadata_accepts_current_runtime_metadata_and_matching_commands(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            runtime_dir.mkdir(parents=True)
            commands = [{"command": "true", "exit_code": 0, "timed_out": False}]
            identities = [VERIFY_TASK.command_result_identity(item) for item in commands]
            (runtime_dir / "phase0-ac-attempt1.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "runner_version": VERIFY_TASK.HARNESS_VERSION,
                        "phase": 0,
                        "attempt": 1,
                        "policy_pack": VERIFY_TASK.policy_pack_metadata(),
                        "harness_attestation": VERIFY_TASK.harness_attestation(),
                        "commands_digest": VERIFY_TASK.stable_json_sha256(identities),
                        "commands": commands,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_ac_results_metadata(
                root,
                task_path,
                0,
                1,
                {"ac_results": "context-pack/runtime/phase0-ac-attempt1.json"},
                VERIFY_TASK.policy_pack_metadata(),
                commands,
                strict_current_harness=True,
            )

            self.assertEqual(errors, [])

    def test_ac_results_metadata_rejects_command_digest_and_phase_command_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            runtime_dir.mkdir(parents=True)
            (runtime_dir / "phase0-ac-attempt1.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "phase": 0,
                        "attempt": 1,
                        "commands_digest": "stale",
                        "commands": [{"command": "false", "exit_code": 1}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_ac_results_metadata(
                root,
                task_path,
                0,
                1,
                {"ac_results": "context-pack/runtime/phase0-ac-attempt1.json"},
                None,
                [{"command": "true", "exit_code": 0}],
            )

            self.assertTrue(any("commands_digest" in error for error in errors), errors)
            self.assertTrue(any("commands do not match" in error for error in errors), errors)

    def test_strict_current_harness_rejects_stale_policy_pack(self) -> None:
        stale_policy = VERIFY_TASK.policy_pack_metadata()
        stale_policy["sha256"] = "stale"

        self.assertEqual(VERIFY_TASK.validate_policy_pack_metadata(stale_policy, "Phase result"), [])
        errors = VERIFY_TASK.validate_policy_pack_metadata(
            stale_policy,
            "Phase result",
            strict_current=True,
        )

        self.assertTrue(any("current harness policy pack" in error for error in errors), errors)

    def test_default_policy_pack_validation_rejects_unapproved_lineage(self) -> None:
        current = VERIFY_TASK.current_policy_pack_fingerprint()
        stale_policy = dict(current)
        stale_policy["sha256"] = "stale"

        errors = VERIFY_TASK.validate_policy_pack_metadata(
            stale_policy,
            "Phase result",
            approved_fingerprints=[current],
        )

        self.assertTrue(any("design-approved policy pack lineage" in error for error in errors), errors)

    def test_policy_pack_lineage_normalization_rejects_duplicates(self) -> None:
        current = VERIFY_TASK.current_policy_pack_fingerprint()

        fingerprints, errors = VERIFY_TASK.normalize_policy_pack_fingerprints(
            [current, dict(current)],
            "lineage",
        )

        self.assertEqual(fingerprints, [current])
        self.assertTrue(any("duplicates" in error for error in errors), errors)

    def test_revoked_policy_pack_is_excluded_from_approved_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            self.write_design_approval(root, task_path)
            approval_path = task_path / "context-pack" / "static" / "design-approval.json"
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            current = VERIFY_TASK.current_policy_pack_fingerprint()
            stale = dict(current)
            stale["sha256"] = "stale"
            approval["approved_policy_packs"].append(
                {**stale, "status": "revoked", "revocation_reason": "superseded by current policy"}
            )
            approval["approved_policy_packs_sha256"] = VERIFY_TASK.policy_pack_lineage_sha256(
                [
                    VERIFY_TASK.policy_pack_fingerprint(item)
                    for item in approval["approved_policy_packs"]
                    if VERIFY_TASK.policy_pack_fingerprint(item) is not None
                ]
            )
            entries, entry_errors = VERIFY_TASK.normalize_policy_pack_lineage_entries(
                approval["approved_policy_packs"],
                "test lineage",
                approval["active_policy_pack"],
            )
            self.assertEqual(entry_errors, [])
            approval["design_approval_scope_sha256"] = VERIFY_TASK.design_approval_scope_sha256(
                approval["approved_bundle"],
                [
                    VERIFY_TASK.policy_pack_fingerprint(item)
                    for item in approval["approved_policy_packs"]
                    if VERIFY_TASK.policy_pack_fingerprint(item) is not None
                ],
                approval["active_policy_pack"],
                entries,
            )
            approval_path.write_text(json.dumps(approval) + "\n", encoding="utf-8")

            lineage, errors = VERIFY_TASK.approved_policy_pack_lineage(root, task_path)

            self.assertEqual(errors, [])
            self.assertNotIn(stale, lineage)

    def test_revoked_policy_pack_requires_revocation_reason(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            self.write_design_approval(root, task_path)
            approval_path = task_path / "context-pack" / "static" / "design-approval.json"
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            current = VERIFY_TASK.current_policy_pack_fingerprint()
            stale = dict(current)
            stale["sha256"] = "stale"
            approval["approved_policy_packs"].append({**stale, "status": "revoked"})
            approval["approved_policy_packs_sha256"] = VERIFY_TASK.policy_pack_lineage_sha256(
                [
                    VERIFY_TASK.policy_pack_fingerprint(item)
                    for item in approval["approved_policy_packs"]
                    if VERIFY_TASK.policy_pack_fingerprint(item) is not None
                ]
            )
            entries, _ = VERIFY_TASK.normalize_policy_pack_lineage_entries(
                approval["approved_policy_packs"],
                "test lineage",
                approval["active_policy_pack"],
            )
            approval["design_approval_scope_sha256"] = VERIFY_TASK.design_approval_scope_sha256(
                approval["approved_bundle"],
                [
                    VERIFY_TASK.policy_pack_fingerprint(item)
                    for item in approval["approved_policy_packs"]
                    if VERIFY_TASK.policy_pack_fingerprint(item) is not None
                ],
                approval["active_policy_pack"],
                entries,
            )
            approval_path.write_text(json.dumps(approval) + "\n", encoding="utf-8")

            _, errors = VERIFY_TASK.approved_policy_pack_lineage(root, task_path)

            self.assertTrue(any("revocation_reason" in error for error in errors), errors)

    def test_strict_current_harness_rejects_stale_attestation(self) -> None:
        attestation = json.loads(json.dumps(VERIFY_TASK.harness_attestation()))
        attestation["entries"][0]["sha256"] = "stale"
        attestation["digest"] = VERIFY_TASK.stable_json_sha256(attestation["entries"])

        self.assertEqual(VERIFY_TASK.validate_harness_attestation_metadata(attestation, "Phase result"), [])
        errors = VERIFY_TASK.validate_harness_attestation_metadata(
            attestation,
            "Phase result",
            strict_current=True,
        )

        self.assertTrue(any("current harness script fingerprint" in error for error in errors), errors)

    def test_runner_version_is_historical_by_default_and_strict_in_ci_mode(self) -> None:
        self.assertEqual(VERIFY_TASK.validate_runner_version("0.1.4", "Phase result"), [])
        errors = VERIFY_TASK.validate_runner_version(
            "0.1.4",
            "Phase result",
            strict_current=True,
        )

        self.assertTrue(any(VERIFY_TASK.HARNESS_VERSION in error for error in errors), errors)

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

    def test_verify_with_evaluation_requirement_accepts_valid_evaluation_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            self.write_design_approval(root, task_path)
            self.write_evaluation_artifacts(task_path)

            errors = VERIFY_TASK.verify(
                root,
                task_path,
                require_evaluation=True,
                require_design_approval=True,
            )

            self.assertEqual(errors, [])

    def test_verify_with_evaluation_requirement_rejects_missing_evaluation_commit(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            self.write_design_approval(root, task_path)
            self.write_evaluation_artifacts(task_path)
            (task_path / "context-pack" / "runtime" / "evaluation-commit.json").unlink()

            errors = VERIFY_TASK.verify(
                root,
                task_path,
                require_evaluation=True,
                require_design_approval=True,
            )

            self.assertTrue(any("Missing evaluation commit" in error for error in errors), errors)

    def test_verify_with_evaluation_requirement_rejects_stale_evaluation_artifact_hash(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            self.write_design_approval(root, task_path)
            self.write_evaluation_artifacts(task_path)
            (task_path / "context-pack" / "runtime" / "evaluation-output.jsonl").write_text(
                '{"event":"changed"}\n',
                encoding="utf-8",
            )

            errors = VERIFY_TASK.verify(
                root,
                task_path,
                require_evaluation=True,
                require_design_approval=True,
            )

            self.assertTrue(any("output sha256 does not match" in error for error in errors), errors)

    def test_evaluation_commit_phase_proofs_must_match_completed_phases(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            self.write_design_approval(root, task_path)
            self.write_evaluation_artifacts(task_path)

            errors = VERIFY_TASK.validate_evaluation_commit(
                root,
                task_path,
                task_path / "context-pack" / "runtime" / "evaluation-commit.json",
                [(0, {"attempt": 1})],
                approved_policy_packs=[VERIFY_TASK.current_policy_pack_fingerprint()],
            )

            self.assertTrue(any("phase_proofs must match completed phases" in error for error in errors), errors)

    def test_evaluation_commit_allows_legacy_missing_repair_proofs_without_repairs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            self.write_design_approval(root, task_path)
            self.write_evaluation_artifacts(task_path)
            commit_path = task_path / "context-pack" / "runtime" / "evaluation-commit.json"
            commit = json.loads(commit_path.read_text(encoding="utf-8"))
            commit.pop("repair_proofs", None)
            commit_path.write_text(json.dumps(commit) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.validate_evaluation_commit(
                root,
                task_path,
                commit_path,
                [],
                approved_policy_packs=[VERIFY_TASK.current_policy_pack_fingerprint()],
            )

            self.assertEqual(errors, [])

    def test_evaluation_commit_repair_proofs_seal_repair_result(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            self.write_design_approval(root, task_path)
            self.write_evaluation_artifacts(task_path)
            runtime_dir = task_path / "context-pack" / "runtime"
            repo_content = {
                "changed_files": [],
                "changed_files_digest": VERIFY_TASK.stable_json_sha256([]),
                "required_repo_outputs": [],
                "required_repo_outputs_digest": VERIFY_TASK.stable_json_sha256([]),
            }
            repo_content["digest"] = VERIFY_TASK.stable_json_sha256(repo_content)
            self.write_evaluation_repair_result(root, task_path, repo_content=repo_content)
            repair_path = runtime_dir / "evaluation-repair1-result.json"
            commit_path = runtime_dir / "evaluation-commit.json"
            commit = json.loads(commit_path.read_text(encoding="utf-8"))
            commit["repair_proofs"] = [
                {
                    "iteration": 1,
                    "result": {
                        "name": "result",
                        "path": "context-pack/runtime/evaluation-repair1-result.json",
                        "exists": True,
                        "sha256": VERIFY_TASK.file_sha256(repair_path),
                    },
                }
            ]
            commit_path.write_text(json.dumps(commit) + "\n", encoding="utf-8")
            tampered = json.loads(repair_path.read_text(encoding="utf-8"))
            tampered["status"] = "failed"
            repair_path.write_text(json.dumps(tampered) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.validate_evaluation_commit(
                root,
                task_path,
                commit_path,
                [],
                approved_policy_packs=[VERIFY_TASK.current_policy_pack_fingerprint()],
            )

            self.assertTrue(any("repair 1 result sha256 does not match" in error for error in errors), errors)

    def test_evaluation_commit_repair_proofs_rejects_duplicates_and_malformed_entries(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            self.write_design_approval(root, task_path)
            self.write_evaluation_artifacts(task_path)
            runtime_dir = task_path / "context-pack" / "runtime"
            repo_content = {
                "changed_files": [],
                "changed_files_digest": VERIFY_TASK.stable_json_sha256([]),
                "required_repo_outputs": [],
                "required_repo_outputs_digest": VERIFY_TASK.stable_json_sha256([]),
            }
            repo_content["digest"] = VERIFY_TASK.stable_json_sha256(repo_content)
            self.write_evaluation_repair_result(root, task_path, repo_content=repo_content)
            repair_path = runtime_dir / "evaluation-repair1-result.json"
            commit_path = runtime_dir / "evaluation-commit.json"
            commit = json.loads(commit_path.read_text(encoding="utf-8"))
            valid_proof = {
                "iteration": 1,
                "result": {
                    "name": "result",
                    "path": "context-pack/runtime/evaluation-repair1-result.json",
                    "exists": True,
                    "sha256": VERIFY_TASK.file_sha256(repair_path),
                },
            }
            commit["repair_proofs"] = [
                valid_proof,
                {**valid_proof},
                {"iteration": 2},
                "not-object",
                {"iteration": 0, "result": {}},
            ]
            commit_path.write_text(json.dumps(commit) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.validate_evaluation_commit(
                root,
                task_path,
                commit_path,
                [],
                approved_policy_packs=[VERIFY_TASK.current_policy_pack_fingerprint()],
            )

            self.assertTrue(any("duplicate iteration 1" in error for error in errors), errors)
            self.assertTrue(any("repair_proofs[2] must include result" in error for error in errors), errors)
            self.assertTrue(any("repair_proofs[3] must be an object" in error for error in errors), errors)
            self.assertTrue(any("repair_proofs[4].iteration must be a positive integer" in error for error in errors), errors)
            self.assertTrue(any("repair_proofs must match evaluation repair results" in error for error in errors), errors)

    def test_evaluation_commit_repair_proofs_must_match_repair_results(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            self.write_design_approval(root, task_path)
            self.write_evaluation_artifacts(task_path)
            repo_content = {
                "changed_files": [],
                "changed_files_digest": VERIFY_TASK.stable_json_sha256([]),
                "required_repo_outputs": [],
                "required_repo_outputs_digest": VERIFY_TASK.stable_json_sha256([]),
            }
            repo_content["digest"] = VERIFY_TASK.stable_json_sha256(repo_content)
            self.write_evaluation_repair_result(root, task_path, repo_content=repo_content)

            errors = VERIFY_TASK.validate_evaluation_commit(
                root,
                task_path,
                task_path / "context-pack" / "runtime" / "evaluation-commit.json",
                [],
                approved_policy_packs=[VERIFY_TASK.current_policy_pack_fingerprint()],
            )

            self.assertTrue(any("repair_proofs must match evaluation repair results" in error for error in errors), errors)

    def test_verify_with_evaluation_requirement_rejects_repair_result_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            self.write_design_approval(root, task_path)
            self.write_evaluation_artifacts(task_path)
            runtime_dir = task_path / "context-pack" / "runtime"
            target = root / "src" / "demo.py"
            target.parent.mkdir(parents=True)
            target.write_text("after repair\n", encoding="utf-8")
            changed_files = [
                {
                    "path": "src/demo.py",
                    "before_digest": "<missing>",
                    "after_digest": VERIFY_TASK.file_sha256(target),
                }
            ]
            required_repo_outputs: list[dict[str, object]] = []
            repo_content = {
                "changed_files": changed_files,
                "changed_files_digest": VERIFY_TASK.stable_json_sha256(changed_files),
                "required_repo_outputs": required_repo_outputs,
                "required_repo_outputs_digest": VERIFY_TASK.stable_json_sha256(required_repo_outputs),
            }
            repo_content["digest"] = VERIFY_TASK.stable_json_sha256(repo_content)
            self.write_evaluation_repair_result(root, task_path, repo_content=repo_content)
            target.write_text("drift after repair\n", encoding="utf-8")

            errors = VERIFY_TASK.verify(
                root,
                task_path,
                require_evaluation=True,
                require_design_approval=True,
            )

            self.assertTrue(any("does not match current file digest" in error for error in errors), errors)

    def test_evaluation_repair_result_rejects_failed_status_and_scope_violations(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime = task_path / "context-pack" / "runtime"
            repo_content = {
                "changed_files": [],
                "changed_files_digest": VERIFY_TASK.stable_json_sha256([]),
                "required_repo_outputs": [],
                "required_repo_outputs_digest": VERIFY_TASK.stable_json_sha256([]),
            }
            repo_content["digest"] = VERIFY_TASK.stable_json_sha256(repo_content)
            self.write_evaluation_repair_result(
                root,
                task_path,
                repo_content=repo_content,
                status="failed",
                codex_exit_code=1,
                scope_violations=["outside.txt"],
                handoff_exists=False,
            )

            errors = VERIFY_TASK.validate_evaluation_repair_results(root, task_path, runtime)

            self.assertTrue(any('status must be "completed"' in error for error in errors), errors)
            self.assertTrue(any("codex_exit_code must be 0" in error for error in errors), errors)
            self.assertTrue(any("scope_violations must be empty" in error for error in errors), errors)
            self.assertTrue(any("handoff_exists must be true" in error for error in errors), errors)

    def test_evaluation_repair_result_requires_current_runtime_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime = task_path / "context-pack" / "runtime"
            repo_content = {
                "changed_files": [],
                "changed_files_digest": VERIFY_TASK.stable_json_sha256([]),
                "required_repo_outputs": [],
                "required_repo_outputs_digest": VERIFY_TASK.stable_json_sha256([]),
            }
            repo_content["digest"] = VERIFY_TASK.stable_json_sha256(repo_content)
            self.write_evaluation_repair_result(root, task_path, repo_content=repo_content)
            result_path = runtime / "evaluation-repair1-result.json"
            data = json.loads(result_path.read_text(encoding="utf-8"))
            data["runner_version"] = "0.0.0"
            data["policy_pack"]["sha256"] = "stale"
            result_path.write_text(json.dumps(data) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.validate_evaluation_repair_results(root, task_path, runtime)

            self.assertTrue(any("runner_version must match current" in error for error in errors), errors)
            self.assertTrue(any("policy_pack does not match current" in error for error in errors), errors)

    def test_evaluation_repair_result_rejects_tampered_repo_content_digest(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime = task_path / "context-pack" / "runtime"
            target = root / "src" / "demo.py"
            target.parent.mkdir(parents=True)
            target.write_text("after repair\n", encoding="utf-8")
            changed_files = [
                {
                    "path": "src/demo.py",
                    "before_digest": "<missing>",
                    "after_digest": VERIFY_TASK.file_sha256(target),
                }
            ]
            repo_content = {
                "changed_files": changed_files,
                "changed_files_digest": VERIFY_TASK.stable_json_sha256(changed_files),
                "required_repo_outputs": [],
                "required_repo_outputs_digest": VERIFY_TASK.stable_json_sha256([]),
                "digest": "tampered",
            }
            self.write_evaluation_repair_result(root, task_path, repo_content=repo_content)

            errors = VERIFY_TASK.validate_evaluation_repair_results(root, task_path, runtime)

            self.assertTrue(any("repo_content.digest does not match" in error for error in errors), errors)

    def test_evaluation_repair_result_recomputes_scope_and_rejects_blocked_last_message(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime = task_path / "context-pack" / "runtime"
            target = root / "outside.txt"
            target.parent.mkdir(parents=True)
            target.write_text("outside\n", encoding="utf-8")
            changed_files = [
                {
                    "path": "outside.txt",
                    "before_digest": "<missing>",
                    "after_digest": VERIFY_TASK.file_sha256(target),
                }
            ]
            repo_content = {
                "changed_files": changed_files,
                "changed_files_digest": VERIFY_TASK.stable_json_sha256(changed_files),
                "required_repo_outputs": [],
                "required_repo_outputs_digest": VERIFY_TASK.stable_json_sha256([]),
            }
            repo_content["digest"] = VERIFY_TASK.stable_json_sha256(repo_content)
            self.write_evaluation_repair_result(
                root,
                task_path,
                repo_content=repo_content,
                changed_files=["outside.txt"],
                allowed_paths=["src"],
                scope_violations=[],
                last_message_status="blocked",
            )

            errors = VERIFY_TASK.validate_evaluation_repair_results(root, task_path, runtime)

            self.assertTrue(any("scope_violations do not match" in error for error in errors), errors)
            self.assertTrue(any('last_message status must be "completed"' in error for error in errors), errors)

    def test_evaluation_repair_repo_content_supersedes_phase_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime = task_path / "context-pack" / "runtime"
            target = root / "src" / "demo.py"
            target.parent.mkdir(parents=True)
            target.write_text("phase output\n", encoding="utf-8")
            phase_digest = VERIFY_TASK.file_sha256(target)
            target.write_text("evaluation repair output\n", encoding="utf-8")
            repair_digest = VERIFY_TASK.file_sha256(target)
            changed_files = [
                {
                    "path": "src/demo.py",
                    "before_digest": phase_digest,
                    "after_digest": repair_digest,
                }
            ]
            repo_content = {
                "changed_files": changed_files,
                "changed_files_digest": VERIFY_TASK.stable_json_sha256(changed_files),
                "required_repo_outputs": [],
                "required_repo_outputs_digest": VERIFY_TASK.stable_json_sha256([]),
            }
            repo_content["digest"] = VERIFY_TASK.stable_json_sha256(repo_content)
            self.write_evaluation_repair_result(root, task_path, repo_content=repo_content)

            errors = VERIFY_TASK.validate_evaluation_repair_results(
                root,
                task_path,
                runtime,
                base_phase_results=[
                    (
                        0,
                        {
                            "repo_content": {
                                "changed_files": [
                                    {
                                        "path": "src/demo.py",
                                        "before_digest": "<missing>",
                                        "after_digest": phase_digest,
                                    }
                                ],
                                "required_repo_outputs": [],
                            }
                        },
                    )
                ],
            )

            self.assertEqual(errors, [])

    def test_phase_attempt_manifest_rejects_tampered_repair_packet_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime = task_path / "context-pack" / "runtime"
            runtime.mkdir(parents=True)
            prompt = runtime / "phase0-prompt-attempt1.md"
            prompt.write_text("prompt\n", encoding="utf-8")
            artifact = {
                "name": "prompt",
                "path": "context-pack/runtime/phase0-prompt-attempt1.md",
                "exists": True,
                "sha256": VERIFY_TASK.file_sha256(prompt),
            }
            failure = {
                "type": "acceptance_commands",
                "message": "AC command failed.",
                "retryable": True,
                "codex_exit_code": None,
                "stderr_tail": "",
            }
            packet_path = runtime / "phase0-repair-packet-attempt1.json"
            summary_path = runtime / "phase0-repair-packet-attempt1.md"
            packet = {
                "phase": 0,
                "attempt": 1,
                "status": "repair_required",
                "failure": failure,
                "failed_attempt_artifacts": [{**artifact, "sha256": "tampered"}],
            }
            packet_path.write_text(json.dumps(packet) + "\n", encoding="utf-8")
            summary_path.write_text("repair summary\n", encoding="utf-8")
            manifest_record = {
                "schema_version": 1,
                "artifact_kind": "phase_attempt_manifest_record",
                "record_type": "attempt_failed",
                "phase": 0,
                "attempt": 1,
                "runner_version": VERIFY_TASK.HARNESS_VERSION,
                "failure": failure,
                "retryable": True,
                "repair_packet": {
                    "name": "repair_packet",
                    "path": "context-pack/runtime/phase0-repair-packet-attempt1.json",
                    "exists": True,
                    "sha256": VERIFY_TASK.file_sha256(packet_path),
                },
                "repair_packet_summary": {
                    "name": "repair_packet_summary",
                    "path": "context-pack/runtime/phase0-repair-packet-attempt1.md",
                    "exists": True,
                    "sha256": VERIFY_TASK.file_sha256(summary_path),
                },
                "artifacts": [artifact],
            }
            (runtime / "phase0-attempt-manifest.jsonl").write_text(
                json.dumps(manifest_record) + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_phase_attempt_manifest(
                root,
                task_path,
                {"phase": 0, "name": "demo", "status": "error", "attempts": 1},
            )

            self.assertTrue(any("failed_attempt_artifacts" in error for error in errors), errors)

    def test_phase_attempt_manifest_rejects_invalid_json_line(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime = task_path / "context-pack" / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "phase0-attempt-manifest.jsonl").write_text("{not json}\n", encoding="utf-8")

            errors = VERIFY_TASK.validate_phase_attempt_manifest(
                root,
                task_path,
                {"phase": 0, "name": "demo", "status": "error", "attempts": 1},
            )

            self.assertTrue(any("Invalid attempt manifest JSON" in error for error in errors), errors)

    def test_completed_phase_rejects_active_repair_alias_without_manifest_records(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime = task_path / "context-pack" / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "phase0-repair-packet.json").write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "status": "repair_required",
                        "failure": {
                            "type": "gate",
                            "message": "failed",
                            "retryable": False,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (runtime / "phase0-repair-packet.md").write_text("repair\n", encoding="utf-8")

            errors = VERIFY_TASK.validate_phase_attempt_manifest(
                root,
                task_path,
                {"phase": 0, "name": "demo", "status": "completed", "attempts": 1},
            )

            self.assertTrue(any("active repair packet alias" in error for error in errors), errors)
            self.assertTrue(any("active repair packet summary alias" in error for error in errors), errors)

    def test_completed_phase_requires_attempt_manifest_records(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            (task_path / "context-pack" / "runtime").mkdir(parents=True)

            errors = VERIFY_TASK.validate_phase_attempt_manifest(
                root,
                task_path,
                {"phase": 0, "name": "demo", "status": "completed", "attempts": 1},
            )

            self.assertTrue(any("missing attempt manifest records" in error for error in errors), errors)

    def test_phase_attempt_manifest_reuses_runtime_protocol_escape_validation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime = task_path / "context-pack" / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "phase0-attempt-manifest.jsonl").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "artifact_kind": "phase_attempt_manifest_record",
                        "record_type": "attempt_committed",
                        "phase": 0,
                        "attempt": 1,
                        "result": {
                            "name": "result",
                            "path": "../outside.json",
                            "exists": True,
                            "sha256": "bad",
                        },
                        "attempt_commit": {
                            "name": "attempt_commit",
                            "path": "context-pack/runtime/missing-commit.json",
                            "exists": False,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_phase_attempt_manifest(
                root,
                task_path,
                {"phase": 0, "name": "demo", "status": "completed", "attempts": 1},
            )

            self.assertTrue(any("inside the task directory" in error for error in errors), errors)

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
            "design_refs": ["txn.demo"],
            "required_repo_outputs": ["scripts/harness/start.py"],
        }

        errors = VERIFY_TASK.validate_contract_against_design(
            Path("/repo"),
            Path("/repo/tasks/demo"),
            0,
            contract,
            "review",
            ["scripts/harness/start.py"],
            {"txn.demo"},
        )

        self.assertTrue(any("scope.allowed_paths" in error for error in errors), errors)

    def test_contract_consistency_accepts_paths_inside_design_paths(self) -> None:
        contract = {
            "scope": {
                "layer": "runner",
                "allowed_paths": ["scripts/harness/*.py"],
            },
            "design_refs": ["txn.demo"],
            "required_repo_outputs": ["scripts/harness/start.py"],
        }

        errors = VERIFY_TASK.validate_contract_against_design(
            Path("/repo"),
            Path("/repo/tasks/demo"),
            0,
            contract,
            "review",
            ["scripts/harness/"],
            {"txn.demo"},
        )

        self.assertEqual(errors, [])

    def test_contract_consistency_accepts_root_files(self) -> None:
        contract = {
            "scope": {
                "layer": "runner",
                "allowed_paths": ["README.md"],
            },
            "design_refs": ["txn.demo"],
            "required_repo_outputs": ["README.md"],
        }

        errors = VERIFY_TASK.validate_contract_against_design(
            Path("/repo"),
            Path("/repo/tasks/demo"),
            0,
            contract,
            "review",
            ["README.md"],
            {"txn.demo"},
        )

        self.assertEqual(errors, [])

    def test_contract_consistency_rejects_different_glob_without_directory_approval(self) -> None:
        contract = {
            "scope": {
                "layer": "runner",
                "allowed_paths": ["scripts/harness/*.py"],
            },
            "design_refs": ["txn.demo"],
            "required_repo_outputs": ["scripts/harness/start.py"],
        }

        errors = VERIFY_TASK.validate_contract_against_design(
            Path("/repo"),
            Path("/repo/tasks/demo"),
            0,
            contract,
            "review",
            ["scripts/harness/**/*.py"],
            {"txn.demo"},
        )

        self.assertTrue(any("scope.allowed_paths" in error for error in errors), errors)

    def test_design_contract_rejects_approval_language_without_decision_refs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            review_path = task_path / "docs" / "implementation-design-review.md"
            review_path.write_text(
                review_path.read_text(encoding="utf-8")
                + "\nAPNs environment mapping requires explicit approval.\n",
                encoding="utf-8",
            )
            contract_path = task_path / "context-pack" / "static" / "design-contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["decision_refs"] = []
            contract["open_decision_refs"] = []
            contract_path.write_text(json.dumps(contract) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("approval" in error for error in errors), errors)

    def test_review_findings_pass_requires_known_evidence_refs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            findings_path = root / "tasks" / "demo" / "context-pack" / "static" / "review-findings.json"
            findings_path.parent.mkdir(parents=True)
            findings_path.write_text(
                json.dumps(
                    {
                        "findings": [
                            {
                                "taxonomy_id": "acceptance_validity",
                                "status": "pass",
                                "evidence": "Reviewer claims this passed.",
                            }
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = validate_review_findings(
                root,
                findings_path,
                {"acceptance_validity"},
                {"section:API Contract"},
            )

            self.assertTrue(any("evidence_refs" in error for error in errors), errors)

            findings_path.write_text(
                json.dumps(
                    {
                        "findings": [
                            {
                                "taxonomy_id": "acceptance_validity",
                                "status": "pass",
                                "evidence": "Reviewer points to a known section.",
                                "evidence_refs": ["obligation:acceptance.validity"],
                            }
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertEqual(
                validate_review_findings(root, findings_path, {"acceptance_validity"}, {"obligation:acceptance.validity"}),
                [],
            )

    def test_review_findings_reject_unknown_evidence_refs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            findings_path = root / "tasks" / "demo" / "context-pack" / "static" / "review-findings.json"
            findings_path.parent.mkdir(parents=True)
            findings_path.write_text(
                json.dumps(
                    {
                        "findings": [
                            {
                                "taxonomy_id": "acceptance_validity",
                                "status": "pass",
                                "evidence": "Reviewer points to an unknown ref.",
                                "evidence_refs": ["unknown.ref"],
                            }
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = validate_review_findings(
                root,
                findings_path,
                {"acceptance_validity"},
                {"section:API Contract"},
            )

            self.assertTrue(any("unknown evidence" in error for error in errors), errors)

    def test_review_coverage_rejects_missing_taxonomy_and_obligation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            coverage_path = root / "tasks" / "demo" / "context-pack" / "static" / "review-coverage.json"
            coverage_path.parent.mkdir(parents=True)
            coverage_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "taxonomy_coverage": [
                            {
                                "taxonomy_id": "acceptance_validity",
                                "status": "checked",
                                "evidence_refs": ["obligation:acceptance.validity"],
                            }
                        ],
                        "obligation_coverage": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = validate_review_coverage(
                root,
                coverage_path,
                {"acceptance_validity", "dependency_direction"},
                {"acceptance.validity"},
                {"obligation:acceptance.validity"},
            )

            self.assertTrue(any("must cover every review taxonomy" in error for error in errors), errors)
            self.assertTrue(any("must cover every design obligation" in error for error in errors), errors)

    def test_review_coverage_checked_obligation_requires_matching_obligation_ref(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            coverage_path = root / "tasks" / "demo" / "context-pack" / "static" / "review-coverage.json"
            coverage_path.parent.mkdir(parents=True)
            coverage_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "taxonomy_coverage": [
                            {
                                "taxonomy_id": "acceptance_validity",
                                "status": "checked",
                                "evidence_refs": ["obligation:acceptance.validity"],
                            }
                        ],
                        "obligation_coverage": [
                            {
                                "obligation_id": "acceptance.validity",
                                "status": "checked",
                                "evidence_refs": ["section:API Contract"],
                            }
                        ],
                        "assumptions": [],
                        "residual_risks": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = validate_review_coverage(
                root,
                coverage_path,
                {"acceptance_validity"},
                {"acceptance.validity"},
                {"obligation:acceptance.validity", "section:API Contract"},
            )

            self.assertTrue(any("must cite at least one obligation:acceptance.validity" in error for error in errors), errors)

    def test_verify_requires_review_coverage_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            (task_path / "context-pack" / "static" / "review-coverage.json").unlink()

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("review-coverage.json" in error for error in errors), errors)

    def test_review_findings_pass_requires_taxonomy_specific_ref_kind(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            findings_path = root / "tasks" / "demo" / "context-pack" / "static" / "review-findings.json"
            findings_path.parent.mkdir(parents=True)
            findings_path.write_text(
                json.dumps(
                    {
                        "findings": [
                            {
                                "taxonomy_id": "concurrency_atomicity",
                                "status": "pass",
                                "evidence": "Reviewer points to a generic section only.",
                                "evidence_refs": ["section:Transaction Boundaries"],
                            }
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = validate_review_findings(
                root,
                findings_path,
                {"concurrency_atomicity"},
                {"section:Transaction Boundaries"},
            )

            self.assertTrue(any("must cite at least one static evidence ref" in error for error in errors), errors)

    def test_verify_accepts_typed_review_finding_static_refs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            contract_path = task_path / "context-pack" / "static" / "design-contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["transaction_boundaries"] = [
                {
                    "id": "txn.demo",
                    "operation": "Demo write.",
                    "concurrency_strategy": "Atomic write.",
                    "idempotency_strategy": "Idempotent retry.",
                    "resources": ["demo-state"],
                }
            ]
            contract["retry_triggers"] = [
                {
                    "id": "retry.demo",
                    "source": "Foreground resume.",
                    "in_flight_guard": "Single active retry.",
                    "retry_policy": "Retry once after auth-ready.",
                    "preconditions": ["auth-ready"],
                }
            ]
            contract_path.write_text(json.dumps(contract) + "\n", encoding="utf-8")

            findings_path = task_path / "context-pack" / "static" / "review-findings.json"
            findings = json.loads(findings_path.read_text(encoding="utf-8"))
            for item in findings["findings"]:
                if item["taxonomy_id"] in {"acceptance_validity", "lifecycle_trigger_completeness", "rollback_idempotency"}:
                    item["status"] = "na"
                    item["rationale"] = "No implementation phase exists in this fixture."
                    item.pop("evidence_refs", None)
                else:
                    item["status"] = "pass"
                    item.pop("rationale", None)
                    item["evidence_refs"] = {
                        "concurrency_atomicity": ["design:txn.demo"],
                        "decision_approval_leakage": ["decision:D-001"],
                        "artifact_persistence": ["design:artifact.static_context"],
                        "implementation_traceability": ["path:docs/harness/implementation-quality.md"],
                        "dependency_direction": ["architecture:A-001"],
                    }[item["taxonomy_id"]]
            findings_path.write_text(json.dumps(findings) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertEqual(errors, [])

    def test_verify_rejects_review_finding_wrong_design_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            findings_path = task_path / "context-pack" / "static" / "review-findings.json"
            findings = json.loads(findings_path.read_text(encoding="utf-8"))
            for item in findings["findings"]:
                if item["taxonomy_id"] == "concurrency_atomicity":
                    item["status"] = "pass"
                    item.pop("rationale", None)
                    item["evidence_refs"] = ["design:artifact.static_context"]
            findings_path.write_text(json.dumps(findings) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("eligible design source/class" in error for error in errors), errors)

    def test_verify_rejects_unsafe_review_finding_static_refs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            findings_path = task_path / "context-pack" / "static" / "review-findings.json"
            findings = json.loads(findings_path.read_text(encoding="utf-8"))
            for item in findings["findings"]:
                if item["taxonomy_id"] == "artifact_persistence":
                    item["evidence_refs"] = ["path:docs/.env"]
            findings_path.write_text(json.dumps(findings) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("unsafe" in error for error in errors), errors)

    def test_verify_rejects_open_decision_as_pass_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)

            contract_path = task_path / "context-pack" / "static" / "design-contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["open_decision_refs"] = ["OD-001"]
            contract_path.write_text(json.dumps(contract) + "\n", encoding="utf-8")

            open_decisions_path = task_path / "context-pack" / "static" / "open-decisions.json"
            open_decisions_path.write_text(
                json.dumps(
                    {
                        "decisions": [
                            {
                                "id": "OD-001",
                                "question": "Unresolved decision.",
                                "blocking_stage": "plan",
                                "status": "open",
                            }
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            findings_path = task_path / "context-pack" / "static" / "review-findings.json"
            findings = json.loads(findings_path.read_text(encoding="utf-8"))
            for item in findings["findings"]:
                if item["taxonomy_id"] == "decision_approval_leakage":
                    item["evidence_refs"] = ["decision:OD-001"]
            findings_path.write_text(json.dumps(findings) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("unknown evidence" in error for error in errors), errors)

    def test_design_contract_requires_transaction_boundary_for_state_mutation_claims(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            review_path = task_path / "docs" / "implementation-design-review.md"
            text = review_path.read_text(encoding="utf-8")
            text = text.replace(
                "## Transaction Boundaries\n\nApproved content.",
                "## Transaction Boundaries\n\nRemove successful pending tokens from UserDefaults.",
            )
            review_path.write_text(text, encoding="utf-8")

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("transaction_boundaries is empty" in error for error in errors), errors)

    def test_design_contract_requires_retry_trigger_for_lifecycle_retry_claims(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            review_path = task_path / "docs" / "implementation-design-review.md"
            text = review_path.read_text(encoding="utf-8")
            text = text.replace(
                "## State And Lifecycle\n\nApproved content.",
                "## State And Lifecycle\n\nRetry pending sync on foreground after authentication.",
            )
            review_path.write_text(text, encoding="utf-8")

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("retry_triggers is empty" in error for error in errors), errors)

    def test_verify_rejects_implementation_phase_without_design_refs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            phase_path = task_path / "phases" / "phase0.md"
            phase_path.parent.mkdir(parents=True)
            contract = {
                "phase": 0,
                "name": "implementation",
                "read_first": {
                    "docs": [
                        "docs/harness/implementation-quality.md",
                        "tasks/demo/docs/implementation-design-review.md",
                    ],
                    "previous_outputs": [],
                },
                "scope": {"layer": "runner", "allowed_paths": ["docs/harness/implementation-quality.md"]},
                "interfaces": [
                    {
                        "path": "docs/harness/implementation-quality.md",
                        "symbol": "policy",
                        "signature": "Markdown policy",
                        "business_rules": ["Follow approved design."],
                    }
                ],
                "decision_refs": ["D-001"],
                "risk_ledger": [
                    {
                        "id": "R0-001",
                        "class": "acceptance_validity",
                        "action": "verifies",
                        "required_evidence": ["python3 -m unittest discover -s tests"],
                    }
                ],
                "architecture_refs": ["A-001"],
                "dependency_policy": {
                    "new_dependencies": "forbidden",
                    "approved_new_dependencies": [],
                    "approved_dependency_manifest_changes": [],
                },
                "instructions": [
                    {
                        "id": "P0-001",
                        "task": "Update implementation quality docs.",
                        "expected_evidence": ["docs/harness/implementation-quality.md"],
                    }
                ],
                "success_criteria": ["Docs are updated."],
                "stop_rules": ["Stop if scope expands."],
                "fallback_behavior": {"if_blocked": "Report blocker.", "if_tests_fail": "Fix in scope."},
                "validation_budget": {"max_attempts": 1, "command_timeout_seconds": 60},
                "missing_evidence_behavior": "Missing evidence blocks completion.",
                "acceptance_commands": ["python3 -m unittest discover -s tests"],
                "required_outputs": ["context-pack/handoffs/phase0.md"],
                "required_repo_outputs": ["docs/harness/implementation-quality.md"],
                "forbidden": [{"rule": "Do not edit task status.", "reason": "Runner owns status."}],
            }
            phase_path.write_text(
                "# Phase 0: implementation\n\n## Contract\n\n```json\n"
                + json.dumps(contract)
                + "\n```\n",
                encoding="utf-8",
            )
            index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            index["totalPhases"] = 1
            index["phases"] = [
                {
                    "phase": 0,
                    "name": "implementation",
                    "status": "pending",
                    "ac_commands": [],
                    "required_outputs": ["context-pack/handoffs/phase0.md"],
                }
            ]
            (task_path / "index.json").write_text(json.dumps(index) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("design_refs" in error for error in errors), errors)

    def test_traceability_matrix_must_cover_phase_design_refs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            phase_path = task_path / "phases" / "phase0.md"
            phase_path.parent.mkdir(parents=True)
            contract = {
                "phase": 0,
                "name": "implementation",
                "read_first": {
                    "docs": [
                        "docs/harness/implementation-quality.md",
                        "tasks/demo/docs/implementation-design-review.md",
                    ],
                    "previous_outputs": [],
                },
                "scope": {"layer": "runner", "allowed_paths": ["docs/harness/implementation-quality.md"]},
                "interfaces": [
                    {
                        "path": "docs/harness/implementation-quality.md",
                        "symbol": "policy",
                        "signature": "Markdown policy",
                        "business_rules": ["Follow approved design."],
                    }
                ],
                "decision_refs": ["D-001"],
                "design_refs": ["artifact.static_context"],
                "risk_ledger": [
                    {
                        "id": "R0-001",
                        "class": "acceptance_validity",
                        "action": "verifies",
                        "required_evidence": ["python3 -m unittest discover -s tests"],
                    }
                ],
                "architecture_refs": ["A-001"],
                "dependency_policy": {
                    "new_dependencies": "forbidden",
                    "approved_new_dependencies": [],
                    "approved_dependency_manifest_changes": [],
                },
                "instructions": [
                    {
                        "id": "P0-001",
                        "task": "Update implementation quality docs.",
                        "expected_evidence": ["docs/harness/implementation-quality.md"],
                    }
                ],
                "success_criteria": ["Docs are updated."],
                "stop_rules": ["Stop if scope expands."],
                "fallback_behavior": {"if_blocked": "Report blocker.", "if_tests_fail": "Fix in scope."},
                "validation_budget": {"max_attempts": 1, "command_timeout_seconds": 60},
                "missing_evidence_behavior": "Missing evidence blocks completion.",
                "acceptance_commands": ["python3 -m unittest discover -s tests"],
                "required_outputs": ["context-pack/handoffs/phase0.md"],
                "required_repo_outputs": ["docs/harness/implementation-quality.md"],
                "forbidden": [{"rule": "Do not edit task status.", "reason": "Runner owns status."}],
            }
            phase_path.write_text(
                "# Phase 0: implementation\n\n## Contract\n\n```json\n"
                + json.dumps(contract)
                + "\n```\n",
                encoding="utf-8",
            )
            index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            index["totalPhases"] = 1
            index["phases"] = [
                {
                    "phase": 0,
                    "name": "implementation",
                    "status": "pending",
                    "ac_commands": [],
                    "required_outputs": ["context-pack/handoffs/phase0.md"],
                }
            ]
            (task_path / "index.json").write_text(json.dumps(index) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("traceability-matrix.json is missing" in error for error in errors), errors)

    def test_design_contract_obligations_must_be_closed_by_phase(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            contract_path = task_path / "context-pack" / "static" / "design-contract.json"
            design_contract = json.loads(contract_path.read_text(encoding="utf-8"))
            design_contract["obligations"] = [
                {
                    "id": "obl.acceptance-validity",
                    "class": "acceptance_validity",
                    "trigger": "Implementation phase changes approved docs.",
                    "required_command_roles": ["acceptance"],
                    "closure_condition": "At least one phase closes this obligation with same-phase acceptance evidence.",
                }
            ]
            contract_path.write_text(json.dumps(design_contract) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("obligations must be closed" in error for error in errors), errors)

    def test_runtime_risk_evidence_requires_passed_command_ref(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            runtime_dir.mkdir(parents=True)
            (runtime_dir / "phase0-result.json").write_text(
                json.dumps(
                    {
                        "commands_run": [
                            {
                                "command": "python3 tests/validate_boundary.py",
                                "id": "boundary-validator",
                                "exit_code": 1,
                            }
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            contract = {
                "risk_ledger": [
                    {
                        "id": "R0-001",
                        "action": "verifies",
                        "required_evidence": ["boundary-validator"],
                    }
                ]
            }

            errors = VERIFY_TASK.validate_runtime_risk_evidence(root, task_path, 0, contract)

            self.assertTrue(any("was not closed by passed runtime commands" in error for error in errors), errors)

    def test_command_expectation_metadata_must_match_contract(self) -> None:
        commands_run = [
            {
                "command": "python3 -m unittest discover -s tests",
                "id": "unit-tests",
                "role": "acceptance",
                "target": "tests",
                "repo_scan": False,
                "exit_code": 0,
            }
        ]
        contract = {
            "command_expectations": [
                {
                    "id": "unit-tests",
                    "command": "python3 -m unittest discover -s tests",
                    "role": "fixture",
                    "target": "tests",
                    "repo_scan": False,
                }
            ]
        }

        errors = VERIFY_TASK.validate_command_expectation_metadata(commands_run, contract)

        self.assertTrue(any("commands_run[0].role" in error for error in errors), errors)

    def test_command_expectation_metadata_rejects_undeclared_runtime_role(self) -> None:
        commands_run = [
            {
                "command": "python3 -m unittest discover -s tests",
                "role": "acceptance",
                "exit_code": 0,
            }
        ]

        errors = VERIFY_TASK.validate_command_expectation_metadata(
            commands_run,
            {
                "command_expectations": [
                    {
                        "id": "lint",
                        "command": "python3 -m py_compile scripts/harness/verify-task.py",
                        "role": "build",
                    }
                ]
            },
        )

        self.assertTrue(any("not declared" in error for error in errors), errors)

    def test_command_expectation_metadata_rejects_metadata_without_contract_expectations(self) -> None:
        commands_run = [
            {
                "command": "python3 -m unittest discover -s tests",
                "id": "unit-tests",
                "role": "acceptance",
                "exit_code": 0,
            }
        ]

        errors = VERIFY_TASK.validate_command_expectation_metadata(
            commands_run,
            {"command_expectations": []},
        )

        self.assertTrue(any("Contract.command_expectations is empty" in error for error in errors), errors)

    def test_design_contract_validates_obligation_closure_command_refs_shape(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            contract_path = task_path / "context-pack" / "static" / "design-contract.json"
            design_contract = json.loads(contract_path.read_text(encoding="utf-8"))
            design_contract["obligations"] = [
                {
                    "id": "obl.acceptance",
                    "class": "acceptance_validity",
                    "trigger": "Acceptance command required.",
                    "closure_condition": "Specific command evidence passes.",
                    "required_command_roles": ["acceptance"],
                    "closure_command_refs": [],
                }
            ]
            contract_path.write_text(json.dumps(design_contract) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("closure_command_refs" in error for error in errors), errors)

    def test_design_contract_closure_output_requires_command_refs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            contract_path = task_path / "context-pack" / "static" / "design-contract.json"
            design_contract = json.loads(contract_path.read_text(encoding="utf-8"))
            design_contract["obligations"] = [
                {
                    "id": "obl.acceptance",
                    "class": "acceptance_validity",
                    "trigger": "Acceptance command required.",
                    "closure_condition": "Specific command evidence passes.",
                    "required_command_roles": ["acceptance"],
                    "closure_output_contains": ["BOUNDARY_OK"],
                }
            ]
            contract_path.write_text(json.dumps(design_contract) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("closure_output_contains" in error for error in errors), errors)

    def test_design_contract_closure_output_assertions_require_command_refs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            contract_path = task_path / "context-pack" / "static" / "design-contract.json"
            design_contract = json.loads(contract_path.read_text(encoding="utf-8"))
            design_contract["obligations"] = [
                {
                    "id": "obl.acceptance",
                    "class": "acceptance_validity",
                    "trigger": "Acceptance command required.",
                    "closure_condition": "Specific command evidence passes.",
                    "required_command_roles": ["acceptance"],
                    "closure_output_assertions": [
                        {"type": "exact_line", "value": "BOUNDARY_OK"}
                    ],
                }
            ]
            contract_path.write_text(json.dumps(design_contract) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("closure_output_assertions" in error for error in errors), errors)

    def test_design_contract_validates_closure_output_assertions_shape(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            contract_path = task_path / "context-pack" / "static" / "design-contract.json"
            design_contract = json.loads(contract_path.read_text(encoding="utf-8"))
            design_contract["obligations"] = [
                {
                    "id": "obl.acceptance",
                    "class": "acceptance_validity",
                    "trigger": "Acceptance command required.",
                    "closure_condition": "Specific command evidence passes.",
                    "required_command_roles": ["acceptance"],
                    "closure_command_refs": ["unit-tests"],
                    "closure_output_assertions": [
                        {"type": "regex", "value": "BOUNDARY_OK"},
                        {"type": "exact_line", "value": ""},
                        {"type": "exact_line", "value": "BOUNDARY_OK", "command_ref": "unknown"},
                        "BOUNDARY_OK",
                    ],
                }
            ]
            contract_path.write_text(json.dumps(design_contract) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any(".type" in error and "regex" not in error for error in errors), errors)
            self.assertTrue(any(".value" in error for error in errors), errors)
            self.assertTrue(any(".command_ref" in error for error in errors), errors)
            self.assertTrue(any("must be an object" in error for error in errors), errors)

    def test_design_contract_accepts_closure_output_assertion_command_ref(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            contract_path = task_path / "context-pack" / "static" / "design-contract.json"
            design_contract = json.loads(contract_path.read_text(encoding="utf-8"))
            design_contract["obligations"] = [
                {
                    "id": "obl.acceptance",
                    "class": "acceptance_validity",
                    "trigger": "Acceptance command required.",
                    "closure_condition": "Specific command evidence passes.",
                    "required_command_roles": ["acceptance"],
                    "closure_command_refs": ["unit-tests"],
                    "closure_output_assertions": [
                        {
                            "type": "exact_line",
                            "value": "BOUNDARY_OK",
                            "command_ref": "unit-tests",
                        }
                    ],
                }
            ]
            contract_path.write_text(json.dumps(design_contract) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertFalse(any("closure_output_assertions" in error for error in errors), errors)

    def test_design_contract_rejects_sensitive_closure_output_matchers(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            contract_path = task_path / "context-pack" / "static" / "design-contract.json"
            design_contract = json.loads(contract_path.read_text(encoding="utf-8"))
            design_contract["obligations"] = [
                {
                    "id": "obl.acceptance",
                    "class": "acceptance_validity",
                    "trigger": "Acceptance command required.",
                    "closure_condition": "Specific command evidence passes.",
                    "required_command_roles": ["acceptance"],
                    "closure_command_refs": ["unit-tests"],
                    "closure_output_contains": ["token-abc"],
                }
            ]
            contract_path.write_text(json.dumps(design_contract) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("sensitive-looking text" in error for error in errors), errors)

    def test_design_contract_rejects_sensitive_closure_output_assertions(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            contract_path = task_path / "context-pack" / "static" / "design-contract.json"
            design_contract = json.loads(contract_path.read_text(encoding="utf-8"))
            design_contract["obligations"] = [
                {
                    "id": "obl.acceptance",
                    "class": "acceptance_validity",
                    "trigger": "Acceptance command required.",
                    "closure_condition": "Specific command evidence passes.",
                    "required_command_roles": ["acceptance"],
                    "closure_command_refs": ["unit-tests"],
                    "closure_output_assertions": [
                        {"type": "exact_line", "value": "token-abc"}
                    ],
                }
            ]
            contract_path.write_text(json.dumps(design_contract) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("sensitive-looking text" in error for error in errors), errors)

    def test_design_contract_rejects_contains_for_security_sensitive_obligations(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            contract_path = task_path / "context-pack" / "static" / "design-contract.json"
            design_contract = json.loads(contract_path.read_text(encoding="utf-8"))
            design_contract["obligations"] = [
                {
                    "id": "obl.secret-boundary",
                    "class": "secret_sdk_boundary",
                    "trigger": "Secret SDK boundary must be enforced.",
                    "closure_condition": "Boundary validator emits exact proof line.",
                    "required_command_roles": ["acceptance"],
                    "closure_command_refs": ["boundary-validator"],
                    "closure_output_assertions": [
                        {"type": "contains", "value": "BOUNDARY_OK"}
                    ],
                },
                {
                    "id": "obl.secret-boundary-legacy",
                    "class": "secret_sdk_boundary",
                    "trigger": "Secret SDK boundary must be enforced.",
                    "closure_condition": "Boundary validator emits exact proof line.",
                    "required_command_roles": ["acceptance"],
                    "closure_command_refs": ["boundary-validator"],
                    "closure_output_contains": ["BOUNDARY_OK"],
                },
            ]
            contract_path.write_text(json.dumps(design_contract) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("must not be contains" in error for error in errors), errors)
            self.assertTrue(any("not allowed for security-sensitive" in error for error in errors), errors)

    def test_completed_phase_result_requires_attempt_commit_marker(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            handoff_dir = task_path / "context-pack" / "handoffs"
            runtime_dir.mkdir(parents=True)
            handoff_dir.mkdir(parents=True)
            for relative in [
                "context-pack/runtime/phase0-prompt.md",
                "context-pack/runtime/phase0-output-attempt1.jsonl",
                "context-pack/runtime/phase0-stderr-attempt1.txt",
                "context-pack/runtime/phase0-ac-attempt1.json",
                "context-pack/runtime/phase0-quality.json",
                "context-pack/handoffs/phase0.md",
            ]:
                path = task_path / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("ok\n", encoding="utf-8")
            (runtime_dir / "phase0-result.json").write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "status": "completed",
                        "attempt": 1,
                        "codex_exit_code": 0,
                        "changed_files": [],
                        "commands_run": [{"command": "true", "exit_code": 0}],
                        "tests_passed": True,
                        "required_outputs": [
                            {"path": "context-pack/handoffs/phase0.md", "exists": True}
                        ],
                        "artifacts": {
                            "prompt": "context-pack/runtime/phase0-prompt.md",
                            "stdout": "context-pack/runtime/phase0-output-attempt1.jsonl",
                            "stderr": "context-pack/runtime/phase0-stderr-attempt1.txt",
                            "ac_results": "context-pack/runtime/phase0-ac-attempt1.json",
                            "quality": "context-pack/runtime/phase0-quality.json",
                            "handoff": "context-pack/handoffs/phase0.md",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_phase_result(
                root,
                task_path,
                0,
                ["true"],
                ["context-pack/handoffs/phase0.md"],
                [],
            )

            self.assertTrue(any("attempt_commit" in error for error in errors), errors)

    def test_completed_phase_result_requires_obligation_closure_ledger_when_contract_closes_obligations(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            handoff_dir = task_path / "context-pack" / "handoffs"
            runtime_dir.mkdir(parents=True)
            handoff_dir.mkdir(parents=True)
            for relative in [
                "context-pack/runtime/phase0-prompt.md",
                "context-pack/runtime/phase0-output-attempt1.jsonl",
                "context-pack/runtime/phase0-stderr-attempt1.txt",
                "context-pack/runtime/phase0-ac-attempt1.json",
                "context-pack/runtime/phase0-quality.json",
                "context-pack/handoffs/phase0.md",
            ]:
                path = task_path / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("ok\n", encoding="utf-8")
            (runtime_dir / "phase0-contract.json").write_text(
                json.dumps({"phase": 0, "closes_obligations": ["obl.runtime-proof"]}) + "\n",
                encoding="utf-8",
            )
            result_path = runtime_dir / "phase0-result.json"
            result = {
                "phase": 0,
                "status": "completed",
                "attempt": 1,
                "codex_exit_code": 0,
                "changed_files": [],
                "commands_run": [{"command": "true", "exit_code": 0}],
                "tests_passed": True,
                "required_outputs": [
                    {"path": "context-pack/handoffs/phase0.md", "exists": True}
                ],
                "artifacts": {
                    "prompt": "context-pack/runtime/phase0-prompt.md",
                    "stdout": "context-pack/runtime/phase0-output-attempt1.jsonl",
                    "stderr": "context-pack/runtime/phase0-stderr-attempt1.txt",
                    "ac_results": "context-pack/runtime/phase0-ac-attempt1.json",
                    "quality": "context-pack/runtime/phase0-quality.json",
                    "handoff": "context-pack/handoffs/phase0.md",
                    "attempt_commit": "context-pack/runtime/phase0-attempt1-commit.json",
                },
            }
            result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
            (runtime_dir / "phase0-attempt1-commit.json").write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "result": {
                            "path": "context-pack/runtime/phase0-result.json",
                            "sha256": VERIFY_TASK.file_sha256(result_path),
                        },
                        "artifacts": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_phase_result(
                root,
                task_path,
                0,
                ["true"],
                ["context-pack/handoffs/phase0.md"],
                [],
            )

            self.assertTrue(any("obligation_closure" in error for error in errors), errors)

    def test_obligation_closure_ledger_validation_rejects_contract_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            static_dir = task_path / "context-pack" / "static"
            runtime_dir.mkdir(parents=True)
            static_dir.mkdir(parents=True)
            (runtime_dir / "phase0-contract.json").write_text('{"phase":0}\n', encoding="utf-8")
            (static_dir / "design-contract.json").write_text('{"schema_version":"1"}\n', encoding="utf-8")
            output_sha = VERIFY_TASK.text_sha256("BOUNDARY_OK")
            (runtime_dir / "phase0-ac-attempt1.json").write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "commands": [
                            {
                                "id": "unit-tests",
                                "command": "python3 -m unittest",
                                "role": "acceptance",
                                "exit_code": 0,
                                "output": "BOUNDARY_OK",
                                "command_output_sha256": output_sha,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (runtime_dir / "phase0-obligation-closure-attempt1.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "phase": 0,
                        "attempt": 1,
                        "runner_version": "0.1.5",
                        "phase_contract_sha256": "wrong",
                        "design_contract_sha256": VERIFY_TASK.file_sha256(static_dir / "design-contract.json"),
                        "assertions": [
                            {
                                "obligation_id": "obl.acceptance",
                                "assertion_key": "abc",
                                "type": "exact_line",
                                "passed": True,
                                "source": "runner_full_output",
                                "candidate_command_refs": ["unit-tests"],
                                "attempt": 1,
                                "runner_version": "0.1.5",
                                "phase_contract_sha256": "wrong",
                                "design_contract_sha256": VERIFY_TASK.file_sha256(static_dir / "design-contract.json"),
                                "command_ref": "unit-tests",
                                "command_output_sha256": output_sha,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_obligation_closure_ledger(
                root,
                task_path,
                0,
                1,
                {
                    "ac_results": "context-pack/runtime/phase0-ac-attempt1.json",
                    "obligation_closure": "context-pack/runtime/phase0-obligation-closure-attempt1.json",
                },
            )

            self.assertTrue(any("phase_contract_sha256 does not match" in error for error in errors), errors)

    def test_obligation_closure_ledger_validation_accepts_valid_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            static_dir = task_path / "context-pack" / "static"
            runtime_dir.mkdir(parents=True)
            static_dir.mkdir(parents=True)
            (runtime_dir / "phase0-contract.json").write_text('{"phase":0}\n', encoding="utf-8")
            (static_dir / "design-contract.json").write_text('{"schema_version":"1"}\n', encoding="utf-8")
            phase_sha = VERIFY_TASK.file_sha256(runtime_dir / "phase0-contract.json")
            design_sha = VERIFY_TASK.file_sha256(static_dir / "design-contract.json")
            output_sha = VERIFY_TASK.text_sha256("BOUNDARY_OK")
            (runtime_dir / "phase0-ac-attempt1.json").write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "commands": [
                            {
                                "id": "unit-tests",
                                "command": "python3 -m unittest",
                                "role": "acceptance",
                                "exit_code": 0,
                                "output": "BOUNDARY_OK",
                                "command_output_sha256": output_sha,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (runtime_dir / "phase0-obligation-closure-attempt1.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "phase": 0,
                        "attempt": 1,
                        "runner_version": "0.1.5",
                        "phase_contract_sha256": phase_sha,
                        "design_contract_sha256": design_sha,
                        "assertions": [
                            {
                                "obligation_id": "obl.acceptance",
                                "assertion_key": "abc",
                                "type": "exact_line",
                                "passed": True,
                                "source": "runner_full_output",
                                "candidate_command_refs": ["unit-tests"],
                                "attempt": 1,
                                "runner_version": "0.1.5",
                                "phase_contract_sha256": phase_sha,
                                "design_contract_sha256": design_sha,
                                "command_ref": "unit-tests",
                                "command_output_sha256": output_sha,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_obligation_closure_ledger(
                root,
                task_path,
                0,
                1,
                {
                    "ac_results": "context-pack/runtime/phase0-ac-attempt1.json",
                    "obligation_closure": "context-pack/runtime/phase0-obligation-closure-attempt1.json",
                },
            )

            self.assertEqual(errors, [])

    def test_obligation_closure_ledger_validation_rejects_output_digest_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            static_dir = task_path / "context-pack" / "static"
            runtime_dir.mkdir(parents=True)
            static_dir.mkdir(parents=True)
            (runtime_dir / "phase0-contract.json").write_text('{"phase":0}\n', encoding="utf-8")
            (static_dir / "design-contract.json").write_text('{"schema_version":"1"}\n', encoding="utf-8")
            phase_sha = VERIFY_TASK.file_sha256(runtime_dir / "phase0-contract.json")
            design_sha = VERIFY_TASK.file_sha256(static_dir / "design-contract.json")
            (runtime_dir / "phase0-ac-attempt1.json").write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "commands": [
                            {
                                "id": "unit-tests",
                                "command": "python3 -m unittest",
                                "role": "acceptance",
                                "exit_code": 0,
                                "output": "BOUNDARY_OK",
                                "command_output_sha256": VERIFY_TASK.text_sha256("BOUNDARY_OK"),
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (runtime_dir / "phase0-obligation-closure-attempt1.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "phase": 0,
                        "attempt": 1,
                        "runner_version": "0.1.5",
                        "phase_contract_sha256": phase_sha,
                        "design_contract_sha256": design_sha,
                        "assertions": [
                            {
                                "obligation_id": "obl.acceptance",
                                "assertion_key": "abc",
                                "type": "exact_line",
                                "passed": True,
                                "source": "runner_full_output",
                                "candidate_command_refs": ["unit-tests"],
                                "attempt": 1,
                                "runner_version": "0.1.5",
                                "phase_contract_sha256": phase_sha,
                                "design_contract_sha256": design_sha,
                                "command_ref": "unit-tests",
                                "command_output_sha256": "wrong",
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_obligation_closure_ledger(
                root,
                task_path,
                0,
                1,
                {
                    "ac_results": "context-pack/runtime/phase0-ac-attempt1.json",
                    "obligation_closure": "context-pack/runtime/phase0-obligation-closure-attempt1.json",
                },
            )

            self.assertTrue(any("does not match AC command output digest" in error for error in errors), errors)

    def test_obligation_closure_ledger_validation_rejects_design_approval_bundle_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            static_dir = task_path / "context-pack" / "static"
            runtime_dir.mkdir(parents=True)
            static_dir.mkdir(parents=True)
            (runtime_dir / "phase0-contract.json").write_text('{"phase":0}\n', encoding="utf-8")
            (static_dir / "design-contract.json").write_text('{"schema_version":"1"}\n', encoding="utf-8")
            (static_dir / "design-approval.json").write_text(
                json.dumps({"approved_bundle_sha256": "approved-bundle"})
                + "\n",
                encoding="utf-8",
            )
            phase_sha = VERIFY_TASK.file_sha256(runtime_dir / "phase0-contract.json")
            design_sha = VERIFY_TASK.file_sha256(static_dir / "design-contract.json")
            output_sha = VERIFY_TASK.text_sha256("BOUNDARY_OK")
            (runtime_dir / "phase0-ac-attempt1.json").write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "commands": [
                            {
                                "id": "unit-tests",
                                "command": "python3 -m unittest",
                                "role": "acceptance",
                                "exit_code": 0,
                                "output": "BOUNDARY_OK",
                                "command_output_sha256": output_sha,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (runtime_dir / "phase0-obligation-closure-attempt1.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "phase": 0,
                        "attempt": 1,
                        "runner_version": "0.1.5",
                        "phase_contract_sha256": phase_sha,
                        "design_contract_sha256": design_sha,
                        "design_approval_bundle_sha256": "stale-bundle",
                        "assertions": [
                            {
                                "obligation_id": "obl.acceptance",
                                "assertion_key": "abc",
                                "type": "exact_line",
                                "passed": True,
                                "source": "runner_full_output",
                                "candidate_command_refs": ["unit-tests"],
                                "attempt": 1,
                                "runner_version": "0.1.5",
                                "phase_contract_sha256": phase_sha,
                                "design_contract_sha256": design_sha,
                                "design_approval_bundle_sha256": "stale-bundle",
                                "command_ref": "unit-tests",
                                "command_output_sha256": output_sha,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_obligation_closure_ledger(
                root,
                task_path,
                0,
                1,
                {
                    "ac_results": "context-pack/runtime/phase0-ac-attempt1.json",
                    "obligation_closure": "context-pack/runtime/phase0-obligation-closure-attempt1.json",
                },
            )

            self.assertTrue(any("design_approval_bundle_sha256" in error for error in errors), errors)

    def test_obligation_closure_ledger_validation_strict_rejects_stale_runner_version(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            static_dir = task_path / "context-pack" / "static"
            runtime_dir.mkdir(parents=True)
            static_dir.mkdir(parents=True)
            (runtime_dir / "phase0-contract.json").write_text('{"phase":0}\n', encoding="utf-8")
            (static_dir / "design-contract.json").write_text('{"schema_version":"1"}\n', encoding="utf-8")
            phase_sha = VERIFY_TASK.file_sha256(runtime_dir / "phase0-contract.json")
            design_sha = VERIFY_TASK.file_sha256(static_dir / "design-contract.json")
            output_sha = VERIFY_TASK.text_sha256("BOUNDARY_OK")
            (runtime_dir / "phase0-ac-attempt1.json").write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "commands": [
                            {
                                "id": "unit-tests",
                                "command": "python3 -m unittest",
                                "role": "acceptance",
                                "exit_code": 0,
                                "output": "BOUNDARY_OK",
                                "command_output_sha256": output_sha,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (runtime_dir / "phase0-obligation-closure-attempt1.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "phase": 0,
                        "attempt": 1,
                        "runner_version": "0.1.4",
                        "phase_contract_sha256": phase_sha,
                        "design_contract_sha256": design_sha,
                        "assertions": [
                            {
                                "obligation_id": "obl.acceptance",
                                "assertion_key": "abc",
                                "type": "exact_line",
                                "passed": True,
                                "source": "runner_full_output",
                                "candidate_command_refs": ["unit-tests"],
                                "attempt": 1,
                                "runner_version": "0.1.4",
                                "phase_contract_sha256": phase_sha,
                                "design_contract_sha256": design_sha,
                                "command_ref": "unit-tests",
                                "command_output_sha256": output_sha,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            default_errors = VERIFY_TASK.validate_obligation_closure_ledger(
                root,
                task_path,
                0,
                1,
                {
                    "ac_results": "context-pack/runtime/phase0-ac-attempt1.json",
                    "obligation_closure": "context-pack/runtime/phase0-obligation-closure-attempt1.json",
                },
            )
            strict_errors = VERIFY_TASK.validate_obligation_closure_ledger(
                root,
                task_path,
                0,
                1,
                {
                    "ac_results": "context-pack/runtime/phase0-ac-attempt1.json",
                    "obligation_closure": "context-pack/runtime/phase0-obligation-closure-attempt1.json",
                },
                strict_current_harness=True,
            )

            self.assertEqual(default_errors, [])
            self.assertTrue(any(VERIFY_TASK.HARNESS_VERSION in error for error in strict_errors), strict_errors)

    def test_phase_attempt_commit_detects_obligation_closure_ledger_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            runtime_dir.mkdir(parents=True)
            ledger_path = runtime_dir / "phase0-obligation-closure-attempt1.json"
            ledger_path.write_text('{"schema_version":1,"assertions":[]}\n', encoding="utf-8")
            repo_content = {
                "changed_files": [],
                "changed_files_digest": VERIFY_TASK.stable_json_sha256([]),
                "required_repo_outputs": [],
                "required_repo_outputs_digest": VERIFY_TASK.stable_json_sha256([]),
            }
            repo_content["digest"] = VERIFY_TASK.stable_json_sha256(
                {
                    "changed_files": repo_content["changed_files"],
                    "changed_files_digest": repo_content["changed_files_digest"],
                    "required_repo_outputs": repo_content["required_repo_outputs"],
                    "required_repo_outputs_digest": repo_content["required_repo_outputs_digest"],
                }
            )
            result_data = {
                "phase": 0,
                "status": "completed",
                "attempt": 1,
                "repo_content": repo_content,
                "changed_files": [],
                "required_repo_outputs": [],
                "artifacts": {
                    "attempt_commit": "context-pack/runtime/phase0-attempt1-commit.json",
                    "obligation_closure": "context-pack/runtime/phase0-obligation-closure-attempt1.json",
                },
            }
            result_path = runtime_dir / "phase0-result.json"
            result_path.write_text(json.dumps(result_data) + "\n", encoding="utf-8")
            commit_path = runtime_dir / "phase0-attempt1-commit.json"
            commit_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "runner_version": "0.1.5",
                        "commit_scope": "runtime_attempt_bundle",
                        "phase": 0,
                        "attempt": 1,
                        "status": "committed",
                        "policy_pack": {},
                        "result": {
                            "path": "context-pack/runtime/phase0-result.json",
                            "sha256": VERIFY_TASK.file_sha256(result_path),
                        },
                        "repo_content": repo_content,
                        "artifacts": [
                            {
                                "name": "obligation_closure",
                                "path": "context-pack/runtime/phase0-obligation-closure-attempt1.json",
                                "sha256": VERIFY_TASK.file_sha256(ledger_path),
                                "exists": True,
                            }
                        ],
                        "artifact_count": 1,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            ledger_path.write_text('{"schema_version":1,"assertions":[{"tampered":true}]}\n', encoding="utf-8")

            errors = VERIFY_TASK.validate_phase_attempt_commit(
                root,
                task_path,
                0,
                1,
                result_path,
                result_data,
                result_data["artifacts"],
            )

            self.assertTrue(any("obligation_closure sha256 does not match" in error for error in errors), errors)

    def test_phase_attempt_commit_detects_reset_generation_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            runtime_dir.mkdir(parents=True)
            result_data = {
                "phase": 0,
                "status": "completed",
                "attempt": 1,
                "reset_generation": 2,
                "artifacts": {"attempt_commit": "context-pack/runtime/phase0-attempt1-commit.json"},
            }
            result_path = runtime_dir / "phase0-result.json"
            result_path.write_text(json.dumps(result_data) + "\n", encoding="utf-8")
            commit_path = runtime_dir / "phase0-attempt1-commit.json"
            commit_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "runner_version": "0.1.5",
                        "commit_scope": "runtime_attempt_bundle",
                        "phase": 0,
                        "attempt": 1,
                        "reset_generation": 1,
                        "status": "committed",
                        "policy_pack": {},
                        "result": {
                            "path": "context-pack/runtime/phase0-result.json",
                            "sha256": VERIFY_TASK.file_sha256(result_path),
                        },
                        "artifacts": [],
                        "artifact_count": 0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_phase_attempt_commit(
                root,
                task_path,
                0,
                1,
                result_path,
                result_data,
                result_data["artifacts"],
            )

            self.assertTrue(any("reset_generation" in error for error in errors), errors)

    def test_phase_attempt_commit_rejects_paths_escaping_task(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            runtime_dir.mkdir(parents=True)
            result_path = runtime_dir / "phase0-result.json"
            result_data = {
                "phase": 0,
                "status": "completed",
                "attempt": 1,
                "artifacts": {"attempt_commit": "../../outside-commit.json"},
            }
            result_path.write_text(json.dumps(result_data) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.validate_phase_attempt_commit(
                root,
                task_path,
                0,
                1,
                result_path,
                result_data,
                result_data["artifacts"],
            )

            self.assertTrue(any("must not escape" in error for error in errors), errors)

    def test_phase_attempt_commit_rejects_result_pointer_escape(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            runtime_dir.mkdir(parents=True)
            result_data = {
                "phase": 0,
                "status": "completed",
                "attempt": 1,
                "artifacts": {"attempt_commit": "context-pack/runtime/phase0-attempt1-commit.json"},
            }
            result_path = runtime_dir / "phase0-result.json"
            result_path.write_text(json.dumps(result_data) + "\n", encoding="utf-8")
            commit_path = runtime_dir / "phase0-attempt1-commit.json"
            commit_path.write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "result": {
                            "path": "../../outside-result.json",
                            "sha256": VERIFY_TASK.file_sha256(result_path),
                        },
                        "artifacts": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_phase_attempt_commit(
                root,
                task_path,
                0,
                1,
                result_path,
                result_data,
                result_data["artifacts"],
            )

            self.assertTrue(any("attempt_commit.result.path" in error for error in errors), errors)

    def test_phase_attempt_commit_rejects_result_pointer_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            runtime_dir.mkdir(parents=True)
            other_result = runtime_dir / "phase0-other-result.json"
            other_result.write_text('{"phase":0}\n', encoding="utf-8")
            result_data = {
                "phase": 0,
                "status": "completed",
                "attempt": 1,
                "artifacts": {"attempt_commit": "context-pack/runtime/phase0-attempt1-commit.json"},
            }
            result_path = runtime_dir / "phase0-result.json"
            result_path.write_text(json.dumps(result_data) + "\n", encoding="utf-8")
            commit_path = runtime_dir / "phase0-attempt1-commit.json"
            commit_path.write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "result": {
                            "path": "context-pack/runtime/phase0-other-result.json",
                            "sha256": VERIFY_TASK.file_sha256(result_path),
                        },
                        "artifacts": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_phase_attempt_commit(
                root,
                task_path,
                0,
                1,
                result_path,
                result_data,
                result_data["artifacts"],
            )

            self.assertTrue(any("result path does not match" in error for error in errors), errors)

    def test_phase_attempt_commit_accepts_canonical_attempt_result_with_phase_alias(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            runtime_dir.mkdir(parents=True)
            result_data = {
                "phase": 0,
                "status": "completed",
                "attempt": 1,
                "artifacts": {"attempt_commit": "context-pack/runtime/phase0-attempt1-commit.json"},
            }
            alias_result_path = runtime_dir / "phase0-result.json"
            canonical_result_path = runtime_dir / "phase0-result-attempt1.json"
            alias_result_path.write_text(json.dumps(result_data) + "\n", encoding="utf-8")
            canonical_result_path.write_text(json.dumps(result_data) + "\n", encoding="utf-8")
            commit_path = runtime_dir / "phase0-attempt1-commit.json"
            commit_path.write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "result": {
                            "path": "context-pack/runtime/phase0-result-attempt1.json",
                            "sha256": VERIFY_TASK.file_sha256(canonical_result_path),
                        },
                        "artifacts": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_phase_attempt_commit(
                root,
                task_path,
                0,
                1,
                alias_result_path,
                result_data,
                result_data["artifacts"],
            )

            self.assertEqual(errors, [])

    def test_strict_phase_result_rejects_stale_runtime_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            handoff_dir = task_path / "context-pack" / "handoffs"
            runtime_dir.mkdir(parents=True)
            handoff_dir.mkdir(parents=True)
            for relative in [
                "context-pack/runtime/phase0-prompt.md",
                "context-pack/runtime/phase0-output-attempt1.jsonl",
                "context-pack/runtime/phase0-stderr-attempt1.txt",
                "context-pack/runtime/phase0-quality.json",
                "context-pack/handoffs/phase0.md",
            ]:
                path = task_path / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("ok\n", encoding="utf-8")
            current_policy = VERIFY_TASK.policy_pack_metadata()
            stale_policy = {
                key: value
                for key, value in current_policy.items()
                if key in {"id", "schema_version", "sha256"}
            }
            stale_policy["sha256"] = "stale"
            stale_attestation = VERIFY_TASK.harness_attestation()
            stale_attestation["digest"] = "stale"
            ac_path = runtime_dir / "phase0-ac-attempt1.json"
            ac_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "phase": 0,
                        "attempt": 1,
                        "policy_pack": current_policy,
                        "commands": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            result_path = runtime_dir / "phase0-result.json"
            result = {
                "phase": 0,
                "status": "completed",
                "attempt": 1,
                "runner_version": "0.0.0",
                "policy_pack": stale_policy,
                "harness_attestation": stale_attestation,
                "codex_exit_code": 0,
                "changed_files": [],
                "commands_run": [{"command": "true", "exit_code": 0}],
                "tests_passed": True,
                "required_outputs": [{"path": "context-pack/handoffs/phase0.md", "exists": True}],
                "artifacts": {
                    "prompt": "context-pack/runtime/phase0-prompt.md",
                    "stdout": "context-pack/runtime/phase0-output-attempt1.jsonl",
                    "stderr": "context-pack/runtime/phase0-stderr-attempt1.txt",
                    "ac_results": "context-pack/runtime/phase0-ac-attempt1.json",
                    "quality": "context-pack/runtime/phase0-quality.json",
                    "handoff": "context-pack/handoffs/phase0.md",
                    "attempt_commit": "context-pack/runtime/phase0-attempt1-commit.json",
                },
            }
            result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
            (runtime_dir / "phase0-attempt1-commit.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "runner_version": "0.0.0",
                        "commit_scope": "runtime_attempt_bundle",
                        "phase": 0,
                        "attempt": 1,
                        "status": "committed",
                        "policy_pack": stale_policy,
                        "harness_attestation": stale_attestation,
                        "result": {
                            "path": "context-pack/runtime/phase0-result.json",
                            "sha256": VERIFY_TASK.file_sha256(result_path),
                        },
                        "artifacts": [],
                        "artifact_count": 0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_phase_result(
                root,
                task_path,
                0,
                ["true"],
                ["context-pack/handoffs/phase0.md"],
                [],
                strict_current_harness=True,
            )

            self.assertTrue(any("runner_version must match current" in error for error in errors), errors)
            self.assertTrue(any("policy_pack does not match current" in error for error in errors), errors)
            self.assertTrue(any("harness_attestation" in error for error in errors), errors)

    def test_completed_phase_result_rejects_alias_fallback_when_expected_attempt_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            runtime_dir.mkdir(parents=True)
            (runtime_dir / "phase0-result.json").write_text(
                json.dumps({"phase": 0, "status": "completed", "attempt": 2}) + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_phase_result(
                root,
                task_path,
                0,
                [],
                [],
                [],
                expected_attempt=1,
            )

            self.assertTrue(any("phase0-result-attempt1.json" in error for error in errors), errors)

    def test_completed_phase_result_uses_canonical_attempt_result_when_alias_missing_or_stale(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            handoff_dir = task_path / "context-pack" / "handoffs"
            runtime_dir.mkdir(parents=True)
            handoff_dir.mkdir(parents=True)
            for relative in [
                "context-pack/runtime/phase0-contract-attempt1.json",
                "context-pack/runtime/phase0-checklist-attempt1.md",
                "context-pack/runtime/phase0-prompt-attempt1.md",
                "context-pack/runtime/phase0-output-attempt1.jsonl",
                "context-pack/runtime/phase0-stderr-attempt1.txt",
                "context-pack/runtime/phase0-ac-attempt1.json",
                "context-pack/runtime/phase0-quality-attempt1.json",
                "context-pack/runtime/phase0-evidence-attempt1.json",
                "context-pack/runtime/phase0-reconciliation-attempt1.json",
                "context-pack/runtime/phase0-reconciliation-attempt1.md",
                "context-pack/runtime/phase0-gate-attempt1.json",
                "context-pack/runtime/phase0-handoff-attempt1.md",
                "context-pack/handoffs/phase0.md",
            ]:
                path = task_path / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("ok\n", encoding="utf-8")
            result_path = runtime_dir / "phase0-result-attempt1.json"
            result = {
                "phase": 0,
                "status": "completed",
                "attempt": 1,
                "codex_exit_code": 0,
                "changed_files": [],
                "commands_run": [{"command": "true", "exit_code": 0}],
                "tests_passed": True,
                "required_outputs": [{"path": "context-pack/handoffs/phase0.md", "exists": True}],
                "artifacts": {
                    "contract": "context-pack/runtime/phase0-contract-attempt1.json",
                    "checklist": "context-pack/runtime/phase0-checklist-attempt1.md",
                    "prompt": "context-pack/runtime/phase0-prompt-attempt1.md",
                    "stdout": "context-pack/runtime/phase0-output-attempt1.jsonl",
                    "stderr": "context-pack/runtime/phase0-stderr-attempt1.txt",
                    "ac_results": "context-pack/runtime/phase0-ac-attempt1.json",
                    "quality": "context-pack/runtime/phase0-quality-attempt1.json",
                    "evidence": "context-pack/runtime/phase0-evidence-attempt1.json",
                    "reconciliation": "context-pack/runtime/phase0-reconciliation-attempt1.json",
                    "reconciliation_summary": "context-pack/runtime/phase0-reconciliation-attempt1.md",
                    "gate": "context-pack/runtime/phase0-gate-attempt1.json",
                    "handoff": "context-pack/runtime/phase0-handoff-attempt1.md",
                    "attempt_commit": "context-pack/runtime/phase0-attempt1-commit.json",
                },
            }
            result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
            (runtime_dir / "phase0-result.json").write_text(
                json.dumps({**result, "attempt": 2}) + "\n",
                encoding="utf-8",
            )
            commit_artifacts = []
            for name, relative in result["artifacts"].items():
                if name == "attempt_commit":
                    continue
                artifact_path = task_path / relative
                commit_artifacts.append(
                    {
                        "name": name,
                        "path": relative,
                        "exists": True,
                        "sha256": VERIFY_TASK.file_sha256(artifact_path),
                    }
                )
            (runtime_dir / "phase0-attempt1-commit.json").write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "result": {
                            "path": "context-pack/runtime/phase0-result-attempt1.json",
                            "sha256": VERIFY_TASK.file_sha256(result_path),
                        },
                        "artifacts": commit_artifacts,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_phase_result(
                root,
                task_path,
                0,
                ["true"],
                ["context-pack/handoffs/phase0.md"],
                [],
                expected_attempt=1,
            )

            self.assertEqual(errors, [])

            (runtime_dir / "phase0-result.json").unlink()
            errors = VERIFY_TASK.validate_phase_result(
                root,
                task_path,
                0,
                ["true"],
                ["context-pack/handoffs/phase0.md"],
                [],
                expected_attempt=1,
            )

            self.assertEqual(errors, [])

    def test_phase_attempt_commit_rejects_internal_artifact_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            runtime_dir.mkdir(parents=True)
            result_data = {
                "phase": 0,
                "status": "completed",
                "attempt": 1,
                "artifacts": {
                    "attempt_commit": "context-pack/runtime/phase0-attempt1-commit.json",
                    "gate": "../../outside-gate.json",
                },
            }
            result_path = runtime_dir / "phase0-result.json"
            result_path.write_text(json.dumps(result_data) + "\n", encoding="utf-8")
            commit_path = runtime_dir / "phase0-attempt1-commit.json"
            commit_path.write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "result": {
                            "path": "context-pack/runtime/phase0-result.json",
                            "sha256": VERIFY_TASK.file_sha256(result_path),
                        },
                        "artifacts": [{"name": "gate", "path": "../../outside-gate.json", "exists": False}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_phase_attempt_commit(
                root,
                task_path,
                0,
                1,
                result_path,
                result_data,
                result_data["artifacts"],
            )

            self.assertTrue(any("must not escape" in error for error in errors), errors)

    def test_phase_attempt_commit_rejects_commit_entry_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            runtime_dir.mkdir(parents=True)
            gate_path = runtime_dir / "phase0-gate-attempt1.json"
            gate_path.write_text('{"status":"passed"}\n', encoding="utf-8")
            result_data = {
                "phase": 0,
                "status": "completed",
                "attempt": 1,
                "artifacts": {
                    "attempt_commit": "context-pack/runtime/phase0-attempt1-commit.json",
                    "gate": "context-pack/runtime/phase0-gate-attempt1.json",
                },
            }
            result_path = runtime_dir / "phase0-result.json"
            result_path.write_text(json.dumps(result_data) + "\n", encoding="utf-8")
            commit_path = runtime_dir / "phase0-attempt1-commit.json"
            commit_path.write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "result": {
                            "path": "context-pack/runtime/phase0-result.json",
                            "sha256": VERIFY_TASK.file_sha256(result_path),
                        },
                        "artifacts": [
                            {
                                "name": "gate",
                                "path": "../../outside-gate.json",
                                "sha256": VERIFY_TASK.file_sha256(gate_path),
                                "exists": True,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_phase_attempt_commit(
                root,
                task_path,
                0,
                1,
                result_path,
                result_data,
                result_data["artifacts"],
            )

            self.assertTrue(any("must not escape" in error for error in errors), errors)
            self.assertTrue(any("path does not match" in error for error in errors), errors)

    def test_phase_attempt_commit_rejects_missing_committed_artifact_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime_dir = task_path / "context-pack" / "runtime"
            runtime_dir.mkdir(parents=True)
            result_data = {
                "phase": 0,
                "status": "completed",
                "attempt": 1,
                "artifacts": {
                    "attempt_commit": "context-pack/runtime/phase0-attempt1-commit.json",
                    "gate": "context-pack/runtime/phase0-gate-attempt1.json",
                },
            }
            result_path = runtime_dir / "phase0-result-attempt1.json"
            result_path.write_text(json.dumps(result_data) + "\n", encoding="utf-8")
            commit_path = runtime_dir / "phase0-attempt1-commit.json"
            commit_path.write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "attempt": 1,
                        "result": {
                            "path": "context-pack/runtime/phase0-result-attempt1.json",
                            "sha256": VERIFY_TASK.file_sha256(result_path),
                        },
                        "artifacts": [
                            {
                                "name": "gate",
                                "path": "context-pack/runtime/phase0-gate-attempt1.json",
                                "sha256": "missing",
                                "exists": True,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_phase_attempt_commit(
                root,
                task_path,
                0,
                1,
                result_path,
                result_data,
                result_data["artifacts"],
            )

            self.assertTrue(any("artifact path does not exist" in error for error in errors), errors)

    def test_latest_repo_content_attestation_rejects_current_file_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            target = root / "src" / "demo.py"
            target.parent.mkdir(parents=True)
            target.write_text("after\n", encoding="utf-8")
            attested_digest = VERIFY_TASK.file_sha256(target)
            target.write_text("drift\n", encoding="utf-8")

            errors = VERIFY_TASK.validate_latest_repo_content_matches_current(
                root,
                [
                    (
                        0,
                        {
                            "repo_content": {
                                "changed_files": [
                                    {
                                        "path": "src/demo.py",
                                        "before_digest": "<deleted>",
                                        "after_digest": attested_digest,
                                    }
                                ],
                                "required_repo_outputs": [],
                            }
                        },
                    )
                ],
            )

            self.assertTrue(any("does not match current file digest" in error for error in errors), errors)

    def test_later_phase_supersedes_repo_content_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            target = root / "src" / "demo.py"
            target.parent.mkdir(parents=True)
            target.write_text("phase one\n", encoding="utf-8")
            phase_one_digest = VERIFY_TASK.file_sha256(target)
            target.write_text("phase two\n", encoding="utf-8")
            phase_two_digest = VERIFY_TASK.file_sha256(target)

            errors = VERIFY_TASK.validate_latest_repo_content_matches_current(
                root,
                [
                    (
                        0,
                        {
                            "repo_content": {
                                "changed_files": [
                                    {
                                        "path": "src/demo.py",
                                        "before_digest": "<deleted>",
                                        "after_digest": phase_one_digest,
                                    }
                                ],
                                "required_repo_outputs": [],
                            }
                        },
                    ),
                    (
                        1,
                        {
                            "repo_content": {
                                "changed_files": [
                                    {
                                        "path": "src/demo.py",
                                        "before_digest": phase_one_digest,
                                        "after_digest": phase_two_digest,
                                    }
                                ],
                                "required_repo_outputs": [],
                            }
                        },
                    ),
                ],
            )

            self.assertEqual(errors, [])

    def test_verify_rejects_completed_phase_repo_content_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            runtime = task_path / "context-pack" / "runtime"
            handoffs = task_path / "context-pack" / "handoffs"
            phases = task_path / "phases"
            runtime.mkdir(parents=True, exist_ok=True)
            handoffs.mkdir(parents=True, exist_ok=True)
            phases.mkdir(parents=True, exist_ok=True)

            target = root / "src" / "demo.py"
            target.parent.mkdir(parents=True)
            target.write_text("attested\n", encoding="utf-8")
            attested_digest = VERIFY_TASK.file_sha256(target)
            target.write_text("drifted\n", encoding="utf-8")

            contract = {
                "phase": 0,
                "name": "implementation",
                "phase_kind": "implementation",
                "read_first": {
                    "docs": [
                        "docs/harness/implementation-quality.md",
                        "tasks/demo/docs/implementation-design-review.md",
                    ],
                    "previous_outputs": [],
                },
                "scope": {"layer": "app", "allowed_paths": ["src/demo.py"]},
                "interfaces": [
                    {
                        "path": "src/demo.py",
                        "symbol": "demo",
                        "signature": "demo file",
                        "business_rules": ["The demo file is generated by the phase."],
                    }
                ],
                "instructions": [
                    {
                        "id": "I0-001",
                        "task": "Write demo file.",
                        "expected_evidence": ["src/demo.py"],
                    }
                ],
                "success_criteria": ["Demo file exists."],
                "stop_rules": ["Stop on failed acceptance."],
                "fallback_behavior": "Fail closed.",
                "validation_budget": {"max_attempts": 1, "timeout_seconds": 60},
                "missing_evidence_behavior": "Missing evidence blocks completion.",
                "command_expectations": [
                    {"id": "acceptance", "command": "true", "role": "acceptance"}
                ],
                "acceptance_commands": ["true"],
                "required_outputs": ["context-pack/handoffs/phase0.md"],
                "required_repo_outputs": ["src/demo.py"],
                "forbidden": [{"rule": "Do not edit unrelated files.", "reason": "Scope must remain auditable."}],
            }
            (phases / "phase0.md").write_text(
                "# Phase 0: implementation\n\n## Contract\n\n```json\n"
                + json.dumps(contract)
                + "\n```\n",
                encoding="utf-8",
            )
            index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            index["totalPhases"] = 1
            index["phases"] = [
                {
                    "phase": 0,
                    "name": "implementation",
                    "status": "completed",
                    "ac_commands": ["true"],
                    "required_outputs": ["context-pack/handoffs/phase0.md"],
                }
            ]
            (task_path / "index.json").write_text(json.dumps(index) + "\n", encoding="utf-8")

            artifact_contents = {
                "phase0-contract.json": json.dumps(contract) + "\n",
                "phase0-checklist.md": "checklist\n",
                "phase0-prompt.md": "prompt\n",
                "phase0-output-attempt1.jsonl": "{}\n",
                "phase0-stderr-attempt1.txt": "",
                "phase0-ac-attempt1.json": json.dumps({"commands": [{"command": "true", "exit_code": 0}]}) + "\n",
                "phase0-quality.json": json.dumps({"status": "passed", "checks": []}) + "\n",
                "phase0-evidence.json": json.dumps({"commands": [], "required_outputs": []}) + "\n",
                "phase0-reconciliation.json": json.dumps({"status": "passed", "unverified_instructions": []}) + "\n",
                "phase0-reconciliation.md": "reconciled\n",
                "phase0-gate.json": json.dumps({"status": "passed", "checks": []}) + "\n",
                "docs-diff.md": "docs diff\n",
            }
            for filename, content in artifact_contents.items():
                (runtime / filename).write_text(content, encoding="utf-8")
            (handoffs / "phase0.md").write_text("## Change Trace\n\n- src/demo.py: I0-001\n", encoding="utf-8")

            result = {
                "phase": 0,
                "status": "completed",
                "attempt": 1,
                "codex_exit_code": 0,
                "changed_files": ["src/demo.py"],
                "commands_run": [{"command": "true", "exit_code": 0}],
                "tests_passed": True,
                "required_outputs": [{"path": "context-pack/handoffs/phase0.md", "exists": True}],
                "required_repo_outputs": [{"path": "src/demo.py", "exists": True}],
                "repo_content": {
                    "changed_files": [
                        {
                            "path": "src/demo.py",
                            "before_digest": "<deleted>",
                            "after_digest": attested_digest,
                        }
                    ],
                    "required_repo_outputs": [],
                },
                "artifacts": {
                    "contract": "context-pack/runtime/phase0-contract.json",
                    "checklist": "context-pack/runtime/phase0-checklist.md",
                    "prompt": "context-pack/runtime/phase0-prompt.md",
                    "stdout": "context-pack/runtime/phase0-output-attempt1.jsonl",
                    "stderr": "context-pack/runtime/phase0-stderr-attempt1.txt",
                    "ac_results": "context-pack/runtime/phase0-ac-attempt1.json",
                    "quality": "context-pack/runtime/phase0-quality.json",
                    "handoff": "context-pack/handoffs/phase0.md",
                    "evidence": "context-pack/runtime/phase0-evidence.json",
                    "reconciliation": "context-pack/runtime/phase0-reconciliation.json",
                    "reconciliation_summary": "context-pack/runtime/phase0-reconciliation.md",
                    "gate": "context-pack/runtime/phase0-gate.json",
                    "attempt_commit": "context-pack/runtime/phase0-attempt1-commit.json",
                },
            }
            result_path = runtime / "phase0-result.json"
            result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
            artifact_entries = []
            for name, raw_path in result["artifacts"].items():
                if name == "attempt_commit":
                    continue
                artifact_path = task_path / raw_path
                artifact_entries.append(
                    {
                        "name": name,
                        "path": raw_path,
                        "exists": True,
                        "sha256": VERIFY_TASK.file_sha256(artifact_path),
                    }
                )
            (runtime / "phase0-attempt1-commit.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "phase": 0,
                        "attempt": 1,
                        "status": "committed",
                        "commit_scope": "runtime_attempt_bundle",
                        "result": {
                            "path": "context-pack/runtime/phase0-result.json",
                            "sha256": VERIFY_TASK.file_sha256(result_path),
                        },
                        "artifacts": artifact_entries,
                        "repo_content": result["repo_content"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("Repo content attestation for src/demo.py" in error for error in errors), errors)

    def test_evaluation_repair_result_rejects_current_file_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            runtime = task_path / "context-pack" / "runtime"
            runtime.mkdir(parents=True)
            target = root / "src" / "demo.py"
            target.parent.mkdir(parents=True)
            target.write_text("after repair\n", encoding="utf-8")
            attested_digest = VERIFY_TASK.file_sha256(target)
            changed_files = [
                {
                    "path": "src/demo.py",
                    "before_digest": "<missing>",
                    "after_digest": attested_digest,
                }
            ]
            required_repo_outputs: list[dict[str, object]] = []
            repo_content = {
                "changed_files": changed_files,
                "changed_files_digest": VERIFY_TASK.stable_json_sha256(changed_files),
                "required_repo_outputs": required_repo_outputs,
                "required_repo_outputs_digest": VERIFY_TASK.stable_json_sha256(required_repo_outputs),
            }
            repo_content["digest"] = VERIFY_TASK.stable_json_sha256(repo_content)
            self.write_evaluation_repair_result(root, task_path, repo_content=repo_content)
            target.write_text("drift after repair\n", encoding="utf-8")

            errors = VERIFY_TASK.validate_evaluation_repair_results(root, task_path, runtime)

            self.assertTrue(any("does not match current file digest" in error for error in errors), errors)

    def test_completed_phase_reconciliation_rejects_unverified_instruction(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            reconciliation_path = root / "tasks" / "demo" / "context-pack" / "runtime" / "phase0-reconciliation.json"
            reconciliation_path.parent.mkdir(parents=True)
            reconciliation_path.write_text(
                json.dumps(
                    {
                        "phase": 0,
                        "status": "satisfied",
                        "instruction_results": [
                            {"id": "I-1", "status": "unverified"},
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            errors = VERIFY_TASK.validate_phase_reconciliation(root, reconciliation_path)

            self.assertTrue(any("instruction_results" in error for error in errors), errors)

    def test_phase_closes_obligations_must_reference_design_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)
            phase_path = task_path / "phases" / "phase0.md"
            phase_path.parent.mkdir(parents=True)
            contract = {
                "phase": 0,
                "name": "implementation",
                "read_first": {
                    "docs": [
                        "docs/harness/implementation-quality.md",
                        "tasks/demo/docs/implementation-design-review.md",
                    ],
                    "previous_outputs": [],
                },
                "scope": {"layer": "runner", "allowed_paths": ["docs/harness/implementation-quality.md"]},
                "interfaces": [
                    {
                        "path": "docs/harness/implementation-quality.md",
                        "symbol": "policy",
                        "signature": "Markdown policy",
                        "business_rules": ["Follow approved design."],
                    }
                ],
                "decision_refs": ["D-001"],
                "design_refs": ["artifact.static_context"],
                "closes_obligations": ["obl.unknown"],
                "risk_ledger": [
                    {
                        "id": "R0-001",
                        "class": "acceptance_validity",
                        "action": "verifies",
                        "required_evidence": ["python3 -m unittest discover -s tests"],
                    }
                ],
                "architecture_refs": ["A-001"],
                "dependency_policy": {
                    "new_dependencies": "forbidden",
                    "approved_new_dependencies": [],
                    "approved_dependency_manifest_changes": [],
                },
                "instructions": [
                    {
                        "id": "P0-001",
                        "task": "Update implementation quality docs.",
                        "expected_evidence": ["docs/harness/implementation-quality.md"],
                    }
                ],
                "success_criteria": ["Docs are updated."],
                "stop_rules": ["Stop if scope expands."],
                "fallback_behavior": {"if_blocked": "Report blocker.", "if_tests_fail": "Fix in scope."},
                "validation_budget": {"max_attempts": 1, "command_timeout_seconds": 60},
                "missing_evidence_behavior": "Missing evidence blocks completion.",
                "acceptance_commands": ["python3 -m unittest discover -s tests"],
                "required_outputs": ["context-pack/handoffs/phase0.md"],
                "required_repo_outputs": ["docs/harness/implementation-quality.md"],
                "forbidden": [{"rule": "Do not edit task status.", "reason": "Runner owns status."}],
            }
            phase_path.write_text(
                "# Phase 0: implementation\n\n## Contract\n\n```json\n"
                + json.dumps(contract)
                + "\n```\n",
                encoding="utf-8",
            )
            index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            index["totalPhases"] = 1
            index["phases"] = [
                {
                    "phase": 0,
                    "name": "implementation",
                    "status": "pending",
                    "ac_commands": [],
                    "required_outputs": ["context-pack/handoffs/phase0.md"],
                }
            ]
            (task_path / "index.json").write_text(json.dumps(index) + "\n", encoding="utf-8")

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("closes_obligations entry is not" in error for error in errors), errors)

    def test_design_contract_rejects_gitignored_persistent_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            root.mkdir(parents=True)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            (root / ".gitignore").write_text("tasks/*/context-pack/\n", encoding="utf-8")
            task_path = root / "tasks" / "demo"
            self.write_minimal_task(root, task_path)

            errors = VERIFY_TASK.verify(root, task_path, False, False)

            self.assertTrue(any("ignored by git" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
