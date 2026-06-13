#!/usr/bin/env python3
"""Regression tests for the launcher entrypoint."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
START = ROOT / "scripts" / "harness" / "start.py"
HARNESS_VERSION = "0.1.5"
sys.path.insert(0, str(HARNESS_DIR))

import policy_lineage  # noqa: E402
import harness_attestation  # noqa: E402
import docs_review  # noqa: E402
import start as harness_start  # noqa: E402


class StartLauncherTest(unittest.TestCase):
    def make_repo(self, tmp: Path) -> Path:
        repo = tmp / "repo"
        (repo / ".codex" / "harness" / "scripts" / "skill").mkdir(parents=True)
        (repo / "codex-harness.json").write_text(
            json.dumps({"name": "codex-harness", "version": HARNESS_VERSION}) + "\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "skill" / "SKILL.md").write_text(
            f"---\nname: codex-harness\nversion: {HARNESS_VERSION}\n---\n# skill\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "start.py").write_text(
            "#!/usr/bin/env python3\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "run-phases.py").write_text(
            "#!/usr/bin/env python3\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "verify-task.py").write_text(
            "#!/usr/bin/env python3\nraise SystemExit(0)\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "review-phase-plan.py").write_text(
            "#!/usr/bin/env python3\nraise SystemExit(0)\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "artifact_io.py").write_text(
            "# artifact io helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "codex_exec.py").write_text(
            "# codex exec helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "command_policy.py").write_text(
            "# command policy helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "decision_registry.py").write_text(
            "# decision registry helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "env_policy.py").write_text(
            "# env policy helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "evaluate-task.py").write_text(
            "#!/usr/bin/env python3\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "evidence_obligations.py").write_text(
            "# evidence obligations helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "file_lock.py").write_text(
            "# file lock helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "harness_attestation.py").write_text(
            "# harness attestation helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "install_preflight.py").write_text(
            "# install preflight helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "phase_contract.py").write_text(
            "# phase contract helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "policy_pack.py").write_text(
            "# policy pack helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "process_runner.py").write_text(
            "# process runner helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "policy-packs").mkdir(parents=True)
        (repo / ".codex" / "harness" / "scripts" / "policy-packs" / "default-security.json").write_text(
            "{}\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "design_contract.py").write_text(
            "# design contract helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "reference_resolver.py").write_text(
            "# reference resolver helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "obligation_ledger.py").write_text(
            "# obligation ledger helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "redaction.py").write_text(
            "# redaction helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "phase_semantics.py").write_text(
            "# phase semantics helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "scope_policy.py").write_text(
            "# scope policy helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "task_paths.py").write_text(
            "# task path helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "policy_lineage.py").write_text(
            "# policy lineage helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "relationship_graph.py").write_text(
            "# relationship graph helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "runtime_protocol.py").write_text(
            "# runtime protocol helper\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "gen-relationship-graph.py").write_text(
            "#!/usr/bin/env python3\n",
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "run-quality-checks.py").write_text(
            "#!/usr/bin/env python3\n",
            encoding="utf-8",
        )
        schemas = repo / ".codex" / "harness" / "scripts" / "schemas"
        schemas.mkdir(parents=True)
        for name in [
            "launcher-final.schema.json",
            "phase-final.schema.json",
            "evaluation-final.schema.json",
        ]:
            (schemas / name).write_text("{}\n", encoding="utf-8")
        (repo / ".codex" / "harness" / "install-manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "harness_version": HARNESS_VERSION,
                    "runtime_attestation": harness_attestation.harness_attestation(
                        repo / ".codex" / "harness" / "scripts"
                    ),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return repo

    def refresh_install_manifest(self, repo: Path) -> None:
        (repo / ".codex" / "harness" / "install-manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "harness_version": HARNESS_VERSION,
                    "runtime_attestation": harness_attestation.harness_attestation(
                        repo / ".codex" / "harness" / "scripts"
                    ),
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def make_fake_codex(self, tmp: Path, body: str) -> Path:
        path = tmp / "fake-codex.py"
        path.write_text(
            "#!/usr/bin/env python3\n"
            "from __future__ import annotations\n"
            "import sys\n"
            "from pathlib import Path\n"
            + body,
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | 0o111)
        return path

    def task_artifact_setup_code(self) -> str:
        return textwrap.dedent(
            """
            common_docs = [
                "docs/harness/runner-contract.md",
                "docs/harness/testing.md",
                "docs/harness/document-scope.md",
                "docs/harness/implementation-quality.md",
            ]
            task_docs = [
                "tasks/demo/docs/prd.md",
                "tasks/demo/docs/flow.md",
                "tasks/demo/docs/data-schema.md",
                "tasks/demo/docs/code-architecture.md",
                "tasks/demo/docs/adr.md",
                "tasks/demo/docs/implementation-design-review.md",
            ]
            for raw in common_docs + task_docs:
                path = root / raw
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# Doc\\n", encoding="utf-8")
            static_files = [
                "original-prompt.md",
                "product.md",
                "decisions.md",
                "decisions.json",
                "open-decisions.json",
                "architecture.json",
                "dependency-policy.json",
                "design-contract.json",
                "review-taxonomy.json",
                "review-findings.json",
                "review-coverage.json",
                "traceability-matrix.json",
                "context-gathering-budget.json",
                "rejected-options.md",
                "constraints.md",
                "test-policy.md",
                "clarify-review.md",
                "docs-approval.md",
                "context-gathering.md",
                "docs-index.md",
            ]
            for name in static_files:
                path = task / "context-pack" / "static" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\\n" if name.endswith(".json") else "# Static\\n", encoding="utf-8")
            (root / "tasks").mkdir(parents=True, exist_ok=True)
            (root / "tasks" / "index.json").write_text('{"tasks":[{"dir":"demo"}]}\\n', encoding="utf-8")
            (task / "index.json").write_text(
                '{"project":"demo","task":"demo","common_docs":["docs/harness/runner-contract.md","docs/harness/testing.md","docs/harness/document-scope.md","docs/harness/implementation-quality.md"],"docs":["tasks/demo/docs/prd.md","tasks/demo/docs/flow.md","tasks/demo/docs/data-schema.md","tasks/demo/docs/code-architecture.md","tasks/demo/docs/adr.md","tasks/demo/docs/implementation-design-review.md"],"totalPhases":0,"phases":[]}\\n',
                encoding="utf-8",
            )
            """
        )

    def write_minimal_task_artifacts(self, repo: Path, *, docs_review_verdict: str | None = "clean") -> Path:
        task = repo / "tasks" / "demo"
        common_docs = [
            "docs/harness/runner-contract.md",
            "docs/harness/testing.md",
            "docs/harness/document-scope.md",
            "docs/harness/implementation-quality.md",
        ]
        task_docs = [
            "tasks/demo/docs/prd.md",
            "tasks/demo/docs/flow.md",
            "tasks/demo/docs/data-schema.md",
            "tasks/demo/docs/code-architecture.md",
            "tasks/demo/docs/adr.md",
            "tasks/demo/docs/implementation-design-review.md",
        ]
        for raw in common_docs + task_docs:
            path = repo / raw
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Doc\n", encoding="utf-8")
        static_dir = task / "context-pack" / "static"
        static_dir.mkdir(parents=True, exist_ok=True)
        for name in [
            "original-prompt.md",
            "product.md",
            "decisions.md",
            "decisions.json",
            "open-decisions.json",
            "architecture.json",
            "dependency-policy.json",
            "design-contract.json",
            "review-taxonomy.json",
            "review-findings.json",
            "review-coverage.json",
            "traceability-matrix.json",
            "context-gathering-budget.json",
            "rejected-options.md",
            "constraints.md",
            "test-policy.md",
            "clarify-review.md",
            "docs-approval.md",
            "context-gathering.md",
            "docs-index.md",
        ]:
            (static_dir / name).write_text("{}\n" if name.endswith(".json") else "# Static\n", encoding="utf-8")
        (repo / "tasks").mkdir(parents=True, exist_ok=True)
        (repo / "tasks" / "index.json").write_text('{"tasks":[{"dir":"demo"}]}\n', encoding="utf-8")
        (task / "index.json").write_text(
            '{"project":"demo","task":"demo","common_docs":["docs/harness/runner-contract.md","docs/harness/testing.md","docs/harness/document-scope.md","docs/harness/implementation-quality.md"],"docs":["tasks/demo/docs/prd.md","tasks/demo/docs/flow.md","tasks/demo/docs/data-schema.md","tasks/demo/docs/code-architecture.md","tasks/demo/docs/adr.md","tasks/demo/docs/implementation-design-review.md"],"totalPhases":0,"phases":[]}\n',
            encoding="utf-8",
        )
        if docs_review_verdict is not None:
            status_path = task / "context-pack" / "runtime" / "docs-review-status.json"
            status_path.parent.mkdir(parents=True, exist_ok=True)
            runtime_dir = task / "context-pack" / "runtime"
            proof_paths = {
                "docs-review-attempt1-prompt": runtime_dir / "docs-review-attempt1-prompt.md",
                "docs-review-attempt1-output": runtime_dir / "docs-review-attempt1-output.jsonl",
                "docs-review-attempt1-last-message": runtime_dir / "docs-review-attempt1-last-message.json",
                "docs-review-findings-attempt1": runtime_dir / "docs-review-findings-attempt1.json",
            }
            if docs_review_verdict == "clean":
                for name, path in proof_paths.items():
                    path.write_text(f"{name}\n", encoding="utf-8")
            status_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "verdict": docs_review_verdict,
                        "max_iterations": 3,
                        "iterations_completed": 1,
                        "reviewed_at": "2026-06-02T20:15:50+09:00",
                        "reviewed_files": docs_review.reviewed_file_entries(repo, task),
                        "findings": [],
                        "resolved_blockers": [],
                        "open_blockers": [],
                        "required_decisions": [],
                        "artifact_refs": [
                            docs_review.artifact_ref(task, path, name)
                            for name, path in proof_paths.items()
                        ]
                        if docs_review_verdict == "clean"
                        else [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        return task

    def latest_launcher_result(self, repo: Path) -> dict[str, object]:
        result_paths = sorted((repo / ".codex" / "harness" / "sessions").glob("*/launcher-result.json"))
        self.assertTrue(result_paths)
        return json.loads(result_paths[-1].read_text(encoding="utf-8"))

    def test_missing_verify_task_script_fails_install_validation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            (repo / ".codex" / "harness" / "scripts" / "verify-task.py").unlink()

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "invalid install",
                    "--codex-bin",
                    str(tmp / "unused-codex"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(".codex/harness/scripts/verify-task.py", result.stderr)

    def test_missing_artifact_io_fails_install_validation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            (repo / ".codex" / "harness" / "scripts" / "artifact_io.py").unlink()

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "invalid install",
                    "--codex-bin",
                    str(tmp / "unused-codex"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(".codex/harness/scripts/artifact_io.py", result.stderr)

    def test_missing_phase_plan_review_script_fails_install_validation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            (repo / ".codex" / "harness" / "scripts" / "review-phase-plan.py").unlink()

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "invalid install",
                    "--codex-bin",
                    str(tmp / "unused-codex"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(".codex/harness/scripts/review-phase-plan.py", result.stderr)

    def test_missing_relationship_graph_script_fails_install_validation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            (repo / ".codex" / "harness" / "scripts" / "relationship_graph.py").unlink()

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "invalid install",
                    "--codex-bin",
                    str(tmp / "unused-codex"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(".codex/harness/scripts/relationship_graph.py", result.stderr)

    def test_installed_runtime_drift_fails_install_validation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            (repo / ".codex" / "harness" / "scripts" / "scope_policy.py").write_text(
                "# stale installed runtime\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "invalid install",
                    "--codex-bin",
                    str(tmp / "unused-codex"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("installed runtime drift detected", result.stderr)

    def test_installed_schema_drift_fails_install_validation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            (repo / ".codex" / "harness" / "scripts" / "schemas" / "launcher-final.schema.json").write_text(
                '{"stale":true}\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "invalid install",
                    "--codex-bin",
                    str(tmp / "unused-codex"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("installed runtime drift detected", result.stderr)

    def test_rejects_negative_subprocess_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "invalid timeout",
                    "--subprocess-timeout",
                    "-1",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("value must be non-negative", result.stderr)

    def test_launcher_task_path_resolution_rejects_non_task_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            repo = Path(raw_tmp) / "repo"
            (repo / "not-tasks" / "demo").mkdir(parents=True)

            resolved = harness_start.resolve_task_path(
                repo,
                {"task_path": "not-tasks/demo"},
            )

            self.assertIsNone(resolved)

    def test_questions_artifact_in_final_output_sets_questions_needed_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    args = sys.argv
                    assert "--output-schema" in args, args
                    assert args[args.index("--output-schema") + 1].endswith("launcher-final.schema.json")
                    prompt = sys.stdin.read()
                    assert "Write user-facing Markdown artifacts and task documents in Korean" in prompt
                    assert "recommended direction, tradeoffs, and why" in prompt
                    assert "점수 부족 지점" in prompt
                    assert "return missing decisions through `artifact.content`" in prompt
                    assert "Before docs approval, write missing decisions" not in prompt
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    last_message.write_text(
                        '{"status":"questions_needed","task_path":null,"files_to_read_next":[".codex/harness/sessions/run/questions.md"],"blockers":[],"artifact":{"path":".codex/harness/sessions/run/questions.md","content":"Q?\\\\n"}}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "needs questions",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "questions_needed")
            questions_path = Path(repo, launcher_result["questions"])
            self.assertEqual(questions_path.read_text(encoding="utf-8"), "Q?\n")
            self.assertEqual(
                launcher_result["documents"],
                [
                    {
                        "path": launcher_result["questions"],
                        "content": "Q?\n",
                        "truncated": False,
                    }
                ],
            )

    def test_launcher_documents_exclude_sensitive_files_to_read_next(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            (repo / ".env").write_text("OPENAI_API_KEY=sk-testsecretsecretsecret\n", encoding="utf-8")
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    args = sys.argv
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    last_message.write_text(
                        '{"status":"blocked","task_path":null,"files_to_read_next":[".env","tasks/demo/docs/../../.env"],"blockers":["blocked"],"artifact":null}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "blocked",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["documents"], [])

    def test_answer_file_must_stay_inside_repo_and_avoid_sensitive_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            safe_answer = repo / "answers.md"
            safe_answer.write_text("safe\n", encoding="utf-8")
            outside_answer = tmp / "outside.md"
            outside_answer.write_text("outside\n", encoding="utf-8")
            sensitive_answer = repo / ".env"
            sensitive_answer.write_text("OPENAI_API_KEY=sk-testsecretsecretsecret\n", encoding="utf-8")

            self.assertEqual(harness_start.resolve_answer_path(repo, str(safe_answer)), safe_answer.resolve())
            with self.assertRaisesRegex(ValueError, "inside the repository"):
                harness_start.resolve_answer_path(repo, str(outside_answer))
            with self.assertRaisesRegex(ValueError, "sensitive"):
                harness_start.resolve_answer_path(repo, str(sensitive_answer))

    def test_launcher_prompt_artifact_redacts_secret_content(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "harness-prompt.md"

            harness_start.write_prompt_artifact(path, "Use API_KEY=sk-1234567890abcdefghijklmnop.\n")

            content = path.read_text(encoding="utf-8")
            self.assertIn("[REDACTED]", content)
            self.assertNotIn("sk-1234567890abcdefghijklmnop", content)

    def test_docs_approval_artifact_in_final_output_sets_docs_approval_needed_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    args = sys.argv
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    last_message.write_text(
                        '{"status":"docs_approval_needed","task_path":null,"files_to_read_next":[".codex/harness/sessions/run/docs-approval-request.md"],"blockers":[],"artifact":{"path":".codex/harness/sessions/run/docs-approval-request.md","content":"Approve docs?\\\\n"}}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "needs approval",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "docs_approval_needed")
            approval_path = Path(repo, launcher_result["docs_approval_request"])
            self.assertEqual(approval_path.read_text(encoding="utf-8"), "Approve docs?\n")
            self.assertEqual(
                launcher_result["documents"],
                [
                    {
                        "path": launcher_result["docs_approval_request"],
                        "content": "Approve docs?\n",
                        "truncated": False,
                    }
                ],
            )

    def test_blocked_final_output_sets_blocked_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    args = sys.argv
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    last_message.write_text(
                        '{"status":"blocked","task_path":null,"files_to_read_next":[],"blockers":["cannot proceed"],"artifact":null}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "blocked request",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "blocked")

    def test_planned_without_task_path_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    args = sys.argv
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    last_message.write_text(
                        '{"status":"planned","task_path":null,"files_to_read_next":[],"blockers":[],"artifact":null}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "invalid planned request",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "blocked")

    def test_run_phases_requested_executes_runner_after_planned(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            self.write_minimal_task_artifacts(repo, docs_review_verdict="clean")
            runner_argv = repo / "runner-argv.json"
            (repo / ".codex" / "harness" / "scripts" / "run-phases.py").write_text(
                textwrap.dedent(
                    f"""
                    #!/usr/bin/env python3
                    from __future__ import annotations
                    import json
                    import sys
                    from pathlib import Path
                    Path({str(runner_argv)!r}).write_text(json.dumps(sys.argv), encoding="utf-8")
                    raise SystemExit(0)
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            self.refresh_install_manifest(repo)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    args = sys.argv
                    prompt = sys.stdin.read()
                    assert "--dangerously-bypass-approvals-and-sandbox" not in args, args
                    assert "Do not run Generate from this Codex orchestration session." in prompt
                    assert "The Python launcher process will run `.codex/harness/scripts/run-phases.py`" in prompt
                    root = Path.cwd()
                    task = root / "tasks" / "demo"
                    task.mkdir(parents=True, exist_ok=True)
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    last_message.write_text(
                        '{"status":"planned","task_path":"tasks/demo","files_to_read_next":["tasks/demo/index.json"],"blockers":[],"artifact":null}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "generate with yolo",
                    "--docs-approved",
                    "--design-approved",
                    "--run-phases",
                    "--evaluate",
                    "--strict-current-harness",
                    "--full-auto",
                    "--codex-bin",
                    str(fake),
                    "--codex-max-runtime",
                    "7",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "generated")
            self.assertEqual(launcher_result["dry_run_returncode"], 0)
            self.assertEqual(launcher_result["runner_returncode"], 0)
            graph = launcher_result["relationship_graph"]
            self.assertEqual(graph["status"], "generated")
            self.assertTrue((repo / graph["json"]).exists())
            self.assertTrue((repo / graph["mermaid"]).exists())
            argv = json.loads(runner_argv.read_text(encoding="utf-8"))
            self.assertEqual(
                Path(argv[0]).resolve(),
                (repo / ".codex" / "harness" / "scripts" / "run-phases.py").resolve(),
            )
            self.assertIn("tasks/demo", argv)
            self.assertIn("--root", argv)
            self.assertEqual(Path(argv[argv.index("--root") + 1]).resolve(), repo.resolve())
            self.assertIn("--codex-bin", argv)
            self.assertEqual(Path(argv[argv.index("--codex-bin") + 1]).resolve(), fake.resolve())
            self.assertIn("--full-auto", argv)
            self.assertIn("--evaluate", argv)
            self.assertIn("--strict-current-harness", argv)
            self.assertIn("--codex-max-runtime", argv)
            self.assertEqual(argv[argv.index("--codex-max-runtime") + 1], "7")
            self.assertIn("--subprocess-timeout", argv)
            self.assertEqual(argv[argv.index("--subprocess-timeout") + 1], "1920")
            self.assertNotIn("--yolo", argv)

    def test_launcher_codex_max_runtime_bounds_active_process(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            run_dir = repo / ".codex" / "harness" / "sessions" / "active-timeout"
            run_dir.mkdir(parents=True)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    import time
                    sys.stdin.read()
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        print('{"event":"active"}', flush=True)
                        time.sleep(0.1)
                    raise SystemExit(0)
                    """
                ),
            )
            args = argparse.Namespace(
                codex_bin=str(fake),
                model=None,
                reasoning_effort="",
                yolo=False,
                full_auto=False,
                docs_approved=False,
                codex_idle_timeout=10,
                codex_max_runtime=1,
            )

            started = time.monotonic()
            returncode = harness_start.run_codex(repo, "prompt", run_dir, args)
            elapsed = time.monotonic() - started

            self.assertEqual(returncode, 124)
            self.assertLess(elapsed, 3.0)
            self.assertIn('{"event":"active"}', (run_dir / "harness-output.jsonl").read_text(encoding="utf-8"))
            self.assertIn("max runtime timeout", (run_dir / "harness-stderr.txt").read_text(encoding="utf-8"))

    def test_planned_with_design_approval_requires_verify_task_success(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            self.write_minimal_task_artifacts(repo, docs_review_verdict="clean")
            (repo / ".codex" / "harness" / "scripts" / "verify-task.py").write_text(
                "import sys\nprint('verify failed')\nraise SystemExit(9)\n",
                encoding="utf-8",
            )
            self.refresh_install_manifest(repo)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    root = Path.cwd()
                    task = root / "tasks" / "demo"
                    task.mkdir(parents=True, exist_ok=True)
                    args = sys.argv
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    last_message.write_text(
                        '{"status":"planned","task_path":"tasks/demo","files_to_read_next":[],"blockers":[],"artifact":null}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "planned with bad verification",
                    "--docs-approved",
                    "--design-approved",
                    "--full-auto",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 9, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "blocked")
            self.assertEqual(launcher_result["verifier_returncode"], 9)
            violation_path = Path(repo, launcher_result["orchestration_violation"])
            self.assertTrue(violation_path.exists())
            verify_output = Path(repo, launcher_result["verify_task_output"])
            self.assertIn("verify failed", verify_output.read_text(encoding="utf-8"))

    def test_launcher_times_out_planned_verification_and_writes_result(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            self.write_minimal_task_artifacts(repo, docs_review_verdict="clean")
            marker = tmp / "verify-heartbeat.txt"
            child = tmp / "verify_child.py"
            child.write_text(
                textwrap.dedent(
                    """
                    import signal
                    import sys
                    import time
                    from pathlib import Path

                    signal.signal(signal.SIGTERM, signal.SIG_IGN)
                    marker = Path(sys.argv[1])
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        with marker.open("a", encoding="utf-8") as handle:
                            handle.write("tick\\n")
                            handle.flush()
                        time.sleep(0.1)
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            (repo / ".codex" / "harness" / "scripts" / "verify-task.py").write_text(
                textwrap.dedent(
                    f"""
                    import subprocess
                    import sys
                    import time
                    from pathlib import Path

                    marker = Path({str(marker)!r})
                    subprocess.Popen([sys.executable, {str(child)!r}, str(marker)])
                    deadline = time.monotonic() + 5
                    while not marker.exists() and time.monotonic() < deadline:
                        time.sleep(0.05)
                    time.sleep(10)
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            self.refresh_install_manifest(repo)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    root = Path.cwd()
                    task = root / "tasks" / "demo"
                    task.mkdir(parents=True, exist_ok=True)
                    args = sys.argv
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    last_message.write_text(
                        '{"status":"planned","task_path":"tasks/demo","files_to_read_next":[],"blockers":[],"artifact":null}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "planned with stuck verification",
                    "--docs-approved",
                    "--design-approved",
                    "--full-auto",
                    "--codex-bin",
                    str(fake),
                    "--subprocess-timeout",
                    "1",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 124, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "blocked")
            self.assertEqual(launcher_result["verifier_returncode"], 124)
            verify_stderr = Path(repo, launcher_result["verify_task_stderr"])
            self.assertIn("Timed out after 1 seconds.", verify_stderr.read_text(encoding="utf-8"))
            self.assertTrue(marker.exists())
            before = marker.read_text(encoding="utf-8")
            time.sleep(0.5)
            self.assertEqual(marker.read_text(encoding="utf-8"), before)

    def test_planned_with_design_approval_requires_phase_plan_review_success(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            self.write_minimal_task_artifacts(repo, docs_review_verdict="clean")
            (repo / ".codex" / "harness" / "scripts" / "review-phase-plan.py").write_text(
                "import sys\nprint('phase plan failed')\nraise SystemExit(8)\n",
                encoding="utf-8",
            )
            self.refresh_install_manifest(repo)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    root = Path.cwd()
                    task = root / "tasks" / "demo"
                    task.mkdir(parents=True, exist_ok=True)
                    args = sys.argv
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    last_message.write_text(
                        '{"status":"planned","task_path":"tasks/demo","files_to_read_next":[],"blockers":[],"artifact":null}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "planned with bad phase review",
                    "--docs-approved",
                    "--design-approved",
                    "--full-auto",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 8, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "blocked")
            self.assertEqual(launcher_result["phase_plan_review_returncode"], 8)
            self.assertIsNone(launcher_result["dry_run_returncode"])
            violation_path = Path(repo, launcher_result["orchestration_violation"])
            self.assertTrue(violation_path.exists())
            review_output = Path(repo, launcher_result["phase_plan_review_output"])
            self.assertIn("phase plan failed", review_output.read_text(encoding="utf-8"))

    def test_planned_with_design_approval_requires_phase_runner_dry_run_success(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            self.write_minimal_task_artifacts(repo, docs_review_verdict="clean")
            (repo / ".codex" / "harness" / "scripts" / "run-phases.py").write_text(
                "import sys\nprint('dry-run failed')\nraise SystemExit(6)\n",
                encoding="utf-8",
            )
            self.refresh_install_manifest(repo)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    root = Path.cwd()
                    task = root / "tasks" / "demo"
                    task.mkdir(parents=True, exist_ok=True)
                    args = sys.argv
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    last_message.write_text(
                        '{"status":"planned","task_path":"tasks/demo","files_to_read_next":[],"blockers":[],"artifact":null}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "planned with bad dry-run",
                    "--docs-approved",
                    "--design-approved",
                    "--full-auto",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 6, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "blocked")
            self.assertEqual(launcher_result["dry_run_returncode"], 6)
            self.assertIsNone(launcher_result["runner_returncode"])
            violation_path = Path(repo, launcher_result["orchestration_violation"])
            self.assertTrue(violation_path.exists())
            dry_run_output = Path(repo, launcher_result["run_phases_dry_run_output"])
            self.assertIn("dry-run failed", dry_run_output.read_text(encoding="utf-8"))

    def test_planned_generates_relationship_graph_without_option(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            self.write_minimal_task_artifacts(repo, docs_review_verdict="clean")
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    root = Path.cwd()
                    task = root / "tasks" / "demo"
                    task.mkdir(parents=True, exist_ok=True)
                    args = sys.argv
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    last_message.write_text(
                        '{"status":"planned","task_path":"tasks/demo","files_to_read_next":[],"blockers":[],"artifact":null}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "planned graph",
                    "--docs-approved",
                    "--design-approved",
                    "--full-auto",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "planned")
            self.assertEqual(launcher_result["dry_run_returncode"], 0)
            graph = launcher_result["relationship_graph"]
            self.assertEqual(graph["status"], "generated")
            self.assertTrue((repo / graph["json"]).exists())
            self.assertTrue((repo / graph["mermaid"]).exists())

    def test_launcher_overwrites_design_approval_after_planned(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            self.write_minimal_task_artifacts(repo, docs_review_verdict="clean")
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    root = Path.cwd()
                    task = root / "tasks" / "demo"
                    task.mkdir(parents=True, exist_ok=True)
                    """
                )
                + self.task_artifact_setup_code()
                + textwrap.dedent(
                    """
                    approval_path = task / "context-pack" / "static" / "design-approval.json"
                    approval_path.write_text('{"schema_version":3,"approved":false,"approval_source":"agent"}\\n', encoding="utf-8")
                    args = sys.argv
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    last_message.write_text(
                        '{"status":"planned","task_path":"tasks/demo","files_to_read_next":[],"blockers":[],"artifact":null}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "planned approval seal",
                    "--docs-approved",
                    "--design-approved",
                    "--full-auto",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "planned")
            approval = json.loads(
                (repo / "tasks" / "demo" / "context-pack" / "static" / "design-approval.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(approval["approved"])
            self.assertEqual(approval["approval_source"], "launcher --design-approved")
            self.assertEqual(approval["approved_doc"], "tasks/demo/docs/implementation-design-review.md")
            self.assertIn("approved_bundle_sha256", approval)
            self.assertIn("design_approval_scope_sha256", approval)
            active_policy = approval["active_policy_pack"]
            approved_policies = approval["approved_policy_packs"]
            approved_policy_entries = [{**active_policy, "status": "active"}]
            self.assertEqual(
                approval["approved_policy_packs_sha256"],
                policy_lineage.policy_pack_lineage_sha256(approved_policies),
            )
            self.assertEqual(
                approval["design_approval_scope_sha256"],
                policy_lineage.design_approval_scope_sha256(
                    approval["approved_bundle"],
                    approved_policies,
                    active_policy,
                    approved_policy_entries,
                ),
            )

    def test_design_approved_planning_rejects_missing_docs_review_before_codex(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            self.write_minimal_task_artifacts(repo, docs_review_verdict=None)
            marker = tmp / "codex-invoked.txt"
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    f"""
                    Path({str(marker)!r}).write_text("invoked\\n", encoding="utf-8")
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "plan tasks/demo",
                    "--docs-approved",
                    "--design-approved",
                    "--full-auto",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            self.assertFalse(marker.exists())
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "blocked")
            self.assertIsNone(launcher_result["returncode"])
            self.assertIsNone(launcher_result["docs_blocked"])
            self.assertTrue(
                any("Missing docs review status" in blocker for blocker in launcher_result["documents"][0]["content"].splitlines())
            )

    def test_design_approved_planning_rejects_non_clean_docs_review_before_codex(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            self.write_minimal_task_artifacts(repo, docs_review_verdict="failed")
            marker = tmp / "codex-invoked.txt"
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    f"""
                    Path({str(marker)!r}).write_text("invoked\\n", encoding="utf-8")
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "plan tasks/demo",
                    "--docs-approved",
                    "--design-approved",
                    "--full-auto",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            self.assertFalse(marker.exists())
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "blocked")
            self.assertIsNone(launcher_result["returncode"])
            self.assertIsNone(launcher_result["docs_blocked"])
            self.assertIn('docs-review-status.json verdict must be "clean"', launcher_result["documents"][0]["content"])

    def test_design_approved_planning_rejects_ambiguous_task_before_codex(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            self.write_minimal_task_artifacts(repo, docs_review_verdict="clean")
            other_task = repo / "tasks" / "other"
            other_task.mkdir(parents=True)
            (other_task / "index.json").write_text('{"project":"other","task":"other","phases":[]}\n', encoding="utf-8")
            marker = tmp / "codex-invoked.txt"
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    f"""
                    Path({str(marker)!r}).write_text("invoked\\n", encoding="utf-8")
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "plan the approved task",
                    "--docs-approved",
                    "--design-approved",
                    "--full-auto",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            self.assertFalse(marker.exists())
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "blocked")
            self.assertIsNone(launcher_result["returncode"])
            self.assertIsNone(launcher_result["docs_blocked"])
            self.assertIn(
                "Unable to resolve exactly one task path before design-approved planning.",
                launcher_result["documents"][0]["content"],
            )

    def test_run_phases_failure_blocks_launcher_result(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            self.write_minimal_task_artifacts(repo, docs_review_verdict="clean")
            (repo / ".codex" / "harness" / "scripts" / "run-phases.py").write_text(
                "import sys\n"
                "if '--dry-run' in sys.argv:\n"
                "    print('dry-run ok')\n"
                "    raise SystemExit(0)\n"
                "print('phase failed')\n"
                "raise SystemExit(7)\n",
                encoding="utf-8",
            )
            self.refresh_install_manifest(repo)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    root = Path.cwd()
                    task = root / "tasks" / "demo"
                    task.mkdir(parents=True, exist_ok=True)
                    args = sys.argv
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    last_message.write_text(
                        '{"status":"planned","task_path":"tasks/demo","files_to_read_next":[],"blockers":[],"artifact":null}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "generate and fail",
                    "--docs-approved",
                    "--design-approved",
                    "--run-phases",
                    "--full-auto",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 7, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "blocked")
            self.assertEqual(launcher_result["dry_run_returncode"], 0)
            self.assertEqual(launcher_result["runner_returncode"], 7)

    def test_generated_from_orchestrator_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    root = Path.cwd()
                    task = root / "tasks" / "demo"
                    task.mkdir(parents=True, exist_ok=True)
                    args = sys.argv
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    last_message.write_text(
                        '{"status":"generated","task_path":"tasks/demo","files_to_read_next":[],"blockers":[],"artifact":null}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "orchestrator generated",
                    "--docs-approved",
                    "--design-approved",
                    "--run-phases",
                    "--full-auto",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "blocked")
            violation_path = Path(repo, launcher_result["orchestration_violation"])
            self.assertTrue(violation_path.exists())

    def test_docs_approved_without_design_approval_stops_for_design_review(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    args = sys.argv
                    prompt = sys.stdin.read()
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    if prompt.startswith("# Docs Review Attempt"):
                        last_message.parent.mkdir(parents=True, exist_ok=True)
                        last_message.write_text(
                            '{"verdict":"clean","findings":[],"required_decisions":[]}\\n',
                            encoding="utf-8",
                        )
                        print('{"type":"message","message":"fake-review"}')
                        raise SystemExit(0)
                    assert "design_approval_needed" in prompt
                    assert "Generate is disabled until the launcher is rerun with `--design-approved`." in prompt
                    root = Path.cwd()
                    task = root / "tasks" / "demo"
                    (root / "tasks").mkdir(parents=True, exist_ok=True)
                    (root / "tasks" / "index.json").write_text('{"tasks":[{"dir":"demo"}]}\\n', encoding="utf-8")
                    common_docs = [
                        "docs/harness/runner-contract.md",
                        "docs/harness/testing.md",
                        "docs/harness/document-scope.md",
                        "docs/harness/implementation-quality.md",
                    ]
                    task_docs = [
                        "tasks/demo/docs/prd.md",
                        "tasks/demo/docs/flow.md",
                        "tasks/demo/docs/data-schema.md",
                        "tasks/demo/docs/code-architecture.md",
                        "tasks/demo/docs/adr.md",
                        "tasks/demo/docs/implementation-design-review.md",
                    ]
                    for raw in common_docs + task_docs:
                        path = root / raw
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text("# Doc\\n", encoding="utf-8")
                    static_files = [
                        "original-prompt.md",
                        "product.md",
                        "decisions.md",
                        "decisions.json",
                        "open-decisions.json",
                        "architecture.json",
                        "dependency-policy.json",
                        "design-contract.json",
                        "review-taxonomy.json",
                        "review-findings.json",
                        "review-coverage.json",
                        "traceability-matrix.json",
                        "context-gathering-budget.json",
                        "rejected-options.md",
                        "constraints.md",
                        "test-policy.md",
                        "clarify-review.md",
                        "docs-approval.md",
                        "context-gathering.md",
                        "docs-index.md",
                    ]
                    for name in static_files:
                        path = task / "context-pack" / "static" / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text("{}\\n" if name.endswith(".json") else "# Static\\n", encoding="utf-8")
                    (task / "index.json").write_text(
                        '{"project":"demo","task":"demo","common_docs":["docs/harness/runner-contract.md","docs/harness/testing.md","docs/harness/document-scope.md","docs/harness/implementation-quality.md"],"docs":["tasks/demo/docs/prd.md","tasks/demo/docs/flow.md","tasks/demo/docs/data-schema.md","tasks/demo/docs/code-architecture.md","tasks/demo/docs/adr.md","tasks/demo/docs/implementation-design-review.md"],"totalPhases":0,"phases":[]}\\n',
                        encoding="utf-8",
                    )
                    review = task / "docs" / "implementation-design-review.md"
                    review.write_text("# Implementation Design Review\\n", encoding="utf-8")
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    last_message.write_text(
                        '{"status":"design_approval_needed","task_path":"tasks/demo","files_to_read_next":["tasks/demo/docs/implementation-design-review.md"],"blockers":[],"artifact":null}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "needs design review",
                    "--docs-approved",
                    "--run-phases",
                    "--full-auto",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "design_approval_needed")
            self.assertIsNone(launcher_result["runner_returncode"])
            document_paths = [item["path"] for item in launcher_result["documents"]]
            self.assertEqual(len(document_paths), 2)
            self.assertTrue(document_paths[0].endswith("design-approval-request.md"))
            self.assertEqual(document_paths[1], "tasks/demo/docs/implementation-design-review.md")
            approval_request = launcher_result["documents"][0]["content"]
            self.assertIn("## 이번 문서에 고정된 결정", approval_request)
            self.assertIn("## 주요 product / scope / non-goal 결정", approval_request)
            self.assertIn("## 구현 agent에게 넘길 계약", approval_request)
            self.assertIn("Data model", approval_request)
            self.assertIn("API", approval_request)
            self.assertIn("Storage", approval_request)
            self.assertIn("Dependency", approval_request)
            self.assertIn("UX flow", approval_request)
            self.assertIn("## 리뷰에서 발견되어 해결된 주요 blocker", approval_request)
            self.assertIn("## 남아 있는 open decision", approval_request)
            self.assertIn("phase agent", approval_request)
            self.assertIn("재리뷰와 재승인", approval_request)
            self.assertEqual(launcher_result["documents"][1]["content"], "# Implementation Design Review\n")

    def test_docs_approved_design_review_is_docs_blocked_when_docs_review_requires_decision(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    import json

                    args = sys.argv
                    prompt = sys.stdin.read()
                    root = Path.cwd()
                    task = root / "tasks" / "demo"
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    if prompt.startswith("# Docs Review Attempt"):
                        last_message.write_text(
                            json.dumps(
                                {
                                    "verdict": "blocked",
                                    "findings": [
                                        {
                                            "id": "DR-001",
                                            "severity": "blocker",
                                            "category": "decision_approval_leakage",
                                            "evidence_file": "tasks/demo/docs/implementation-design-review.md",
                                            "evidence_summary": "The draft introduces an unapproved API behavior.",
                                            "auto_fixable": False,
                                            "requires_user_decision": True,
                                            "status": "open",
                                        }
                                    ],
                                    "required_decisions": [
                                        {
                                            "id": "RD-001",
                                            "question": "Should the launcher expose the new API behavior?",
                                            "category": "api_contract",
                                            "evidence_file": "tasks/demo/docs/implementation-design-review.md",
                                            "evidence_summary": "The draft introduces an unapproved API behavior.",
                                            "recommended_direction": "Approve the API behavior explicitly or remove it from the docs.",
                                            "tradeoffs": [
                                                "Approving it expands the public launcher contract.",
                                                "Removing it keeps this phase limited to the approved docs_blocked flow.",
                                            ],
                                            "blocking_stage": "docs_review",
                                        }
                                    ],
                                },
                                ensure_ascii=False,
                            )
                            + "\\n",
                            encoding="utf-8",
                        )
                        print('{"type":"message","message":"fake-review"}')
                        raise SystemExit(0)
                    """
                )
                + self.task_artifact_setup_code()
                + textwrap.dedent(
                    """
                    review = task / "docs" / "implementation-design-review.md"
                    review.write_text("# Implementation Design Review\\n", encoding="utf-8")
                    last_message.write_text(
                        '{"status":"design_approval_needed","task_path":"tasks/demo","files_to_read_next":["tasks/demo/docs/implementation-design-review.md"],"blockers":[],"artifact":null}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "needs blocked docs review",
                    "--docs-approved",
                    "--full-auto",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "docs_blocked")
            self.assertIsNone(launcher_result["runner_returncode"])
            docs_blocked = launcher_result["docs_blocked"]
            self.assertEqual(docs_blocked["verdict"], "blocked")
            self.assertEqual(docs_blocked["required_decisions"][0]["id"], "RD-001")
            self.assertEqual(
                docs_blocked["required_decisions"][0]["evidence_file"],
                "tasks/demo/docs/implementation-design-review.md",
            )
            self.assertEqual(
                docs_blocked["required_decisions"][0]["tradeoffs"],
                [
                    "Approving it expands the public launcher contract.",
                    "Removing it keeps this phase limited to the approved docs_blocked flow.",
                ],
            )
            document_paths = [item["path"] for item in launcher_result["documents"]]
            self.assertEqual(len(document_paths), 1)
            self.assertTrue(document_paths[0].endswith("docs-blocked.md"))
            self.assertNotIn("tasks/demo/docs/implementation-design-review.md", document_paths)
            blocked_doc = launcher_result["documents"][0]["content"]
            self.assertIn("## Required Decisions", blocked_doc)
            self.assertIn("evidence_summary: The draft introduces an unapproved API behavior.", blocked_doc)
            self.assertIn("Approving it expands the public launcher contract.", blocked_doc)
            self.assertIn("Removing it keeps this phase limited to the approved docs_blocked flow.", blocked_doc)

    def test_docs_approved_failed_docs_review_is_blocked_not_docs_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    import json

                    args = sys.argv
                    prompt = sys.stdin.read()
                    root = Path.cwd()
                    task = root / "tasks" / "demo"
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    if prompt.startswith("# Docs Review Attempt"):
                        last_message.write_text(
                            json.dumps(
                                {
                                    "verdict": "failed",
                                    "findings": [],
                                    "required_decisions": [],
                                },
                                ensure_ascii=False,
                            )
                            + "\\n",
                            encoding="utf-8",
                        )
                        print('{"type":"message","message":"fake-review"}')
                        raise SystemExit(0)
                    """
                )
                + self.task_artifact_setup_code()
                + textwrap.dedent(
                    """
                    review = task / "docs" / "implementation-design-review.md"
                    review.write_text("# Implementation Design Review\\n", encoding="utf-8")
                    last_message.write_text(
                        '{"status":"design_approval_needed","task_path":"tasks/demo","files_to_read_next":["tasks/demo/docs/implementation-design-review.md"],"blockers":[],"artifact":null}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "needs failed docs review handling",
                    "--docs-approved",
                    "--full-auto",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "blocked")
            self.assertIsNone(launcher_result["runner_returncode"])
            self.assertIsNone(launcher_result["docs_blocked"])
            self.assertTrue(Path(repo, launcher_result["orchestration_violation"]).exists())
            document_paths = [item["path"] for item in launcher_result["documents"]]
            self.assertEqual(len(document_paths), 1)
            self.assertTrue(document_paths[0].endswith("docs-review-failed.md"))
            self.assertIn("reviewer/cleanup process failed", launcher_result["documents"][0]["content"])
            self.assertNotIn("tasks/demo/docs/implementation-design-review.md", document_paths)

    def test_docs_blocked_self_report_is_blocked_without_docs_review_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            self.write_minimal_task_artifacts(repo, docs_review_verdict=None)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    args = sys.argv
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    last_message.write_text(
                        '{"status":"docs_blocked","task_path":"tasks/demo","files_to_read_next":[],"blockers":["self reported"],"artifact":null}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "self reports docs blocked",
                    "--docs-approved",
                    "--full-auto",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            self.assertFalse((repo / "tasks" / "demo" / "context-pack" / "runtime" / "docs-review-status.json").exists())
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "blocked")
            self.assertIsNone(launcher_result["docs_blocked"])
            violation = json.loads(Path(repo, launcher_result["orchestration_violation"]).read_text(encoding="utf-8"))
            self.assertIn("docs review loop", violation["reason"])

    def test_design_approval_needed_without_task_structure_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    root = Path.cwd()
                    task = root / "tasks" / "demo"
                    review = task / "docs" / "implementation-design-review.md"
                    review.parent.mkdir(parents=True, exist_ok=True)
                    review.write_text("# Implementation Design Review\\n", encoding="utf-8")
                    args = sys.argv
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    last_message.write_text(
                        '{"status":"design_approval_needed","task_path":"tasks/demo","files_to_read_next":["tasks/demo/docs/implementation-design-review.md"],"blockers":[],"artifact":null}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "incomplete design review",
                    "--docs-approved",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "blocked")

    def test_planned_without_design_approval_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    root = Path.cwd()
                    task = root / "tasks" / "demo"
                    task.mkdir(parents=True, exist_ok=True)
                    args = sys.argv
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    last_message.write_text(
                        '{"status":"planned","task_path":"tasks/demo","files_to_read_next":[],"blockers":[],"artifact":null}\\n',
                        encoding="utf-8",
                    )
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "planned too early",
                    "--docs-approved",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "blocked")
            violation_path = Path(repo, launcher_result["orchestration_violation"])
            self.assertTrue(violation_path.exists())

    def test_pre_approval_changes_outside_run_dir_fail_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    root = Path.cwd()
                    target = root / "tasks" / "unauthorized" / "index.json"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text('{"bad":true}\\n', encoding="utf-8")
                    args = sys.argv
                    last_message = Path(args[args.index("--output-last-message") + 1])
                    last_message.parent.mkdir(parents=True, exist_ok=True)
                    last_message.write_text("done\\n", encoding="utf-8")
                    print('{"type":"message","message":"fake"}')
                    raise SystemExit(0)
                    """
                ),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(START),
                    "--root",
                    str(repo),
                    "--request",
                    "unauthorized write",
                    "--codex-bin",
                    str(fake),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            launcher_result = self.latest_launcher_result(repo)
            self.assertEqual(launcher_result["status"], "protocol_violation")
            self.assertIn(
                "tasks/unauthorized/index.json",
                launcher_result["protocol_violations"],
            )


if __name__ == "__main__":
    unittest.main()
