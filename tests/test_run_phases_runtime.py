#!/usr/bin/env python3
"""Runtime tests for run-phases child Codex handling."""

from __future__ import annotations

import importlib.util
import argparse
import json
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))
SPEC = importlib.util.spec_from_file_location("run_phases", HARNESS_DIR / "run-phases.py")
assert SPEC is not None
RUN_PHASES = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RUN_PHASES)


class RunCodexRuntimeTest(unittest.TestCase):
    def make_fake_codex(self, tmp: Path, body: str) -> Path:
        path = tmp / "fake-codex.py"
        path.write_text(
            "#!/usr/bin/env python3\n"
            "from __future__ import annotations\n"
            "import sys\n"
            "import time\n"
            + body,
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | 0o111)
        return path

    def make_task(self, tmp: Path) -> tuple[Path, Path]:
        root = tmp / "repo"
        task_path = root / "tasks" / "demo"
        (task_path / "context-pack" / "runtime").mkdir(parents=True)
        return root, task_path

    def write_contract(self, root: Path, task_path: Path, allowed_paths: list[str]) -> None:
        contract_path = task_path / "context-pack" / "runtime" / "phase1-contract.json"
        contract_path.write_text(
            (
                '{"phase":1,"scope":{"allowed_paths":'
                + repr(allowed_paths).replace("'", '"')
                + '}}\n'
            ),
            encoding="utf-8",
        )

    def test_codex_output_streams_before_process_exits(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    assert "--output-schema" in sys.argv, sys.argv
                    assert sys.argv[sys.argv.index("--output-schema") + 1].endswith("phase-final.schema.json")
                    sys.stdin.read()
                    print('{"event":"first"}', flush=True)
                    time.sleep(1.5)
                    print('{"event":"second"}', flush=True)
                    raise SystemExit(0)
                    """
                ),
            )
            output_path = task_path / "context-pack" / "runtime" / "phase1-output-attempt1.jsonl"
            stderr_path = task_path / "context-pack" / "runtime" / "phase1-stderr-attempt1.txt"
            result: dict[str, int] = {}

            thread = threading.Thread(
                target=lambda: result.setdefault(
                    "returncode",
                    RUN_PHASES.run_codex(
                        root,
                        task_path,
                        1,
                        "prompt",
                        output_path,
                        stderr_path,
                        str(fake),
                        False,
                        False,
                        10,
                    ),
                )
            )
            thread.start()

            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                if output_path.exists() and '{"event":"first"}' in output_path.read_text(encoding="utf-8"):
                    break
                time.sleep(0.05)
            self.assertTrue(output_path.exists())
            self.assertIn('{"event":"first"}', output_path.read_text(encoding="utf-8"))
            self.assertTrue(thread.is_alive())

            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result["returncode"], 0)
            self.assertIn('{"event":"second"}', output_path.read_text(encoding="utf-8"))

    def test_codex_idle_timeout_kills_silent_process(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    sys.stdin.read()
                    time.sleep(5)
                    raise SystemExit(0)
                    """
                ),
            )
            output_path = task_path / "context-pack" / "runtime" / "phase1-output-attempt1.jsonl"
            stderr_path = task_path / "context-pack" / "runtime" / "phase1-stderr-attempt1.txt"

            returncode = RUN_PHASES.run_codex(
                root,
                task_path,
                1,
                "prompt",
                output_path,
                stderr_path,
                str(fake),
                False,
                False,
                1,
            )

            self.assertEqual(returncode, RUN_PHASES.CODEX_IDLE_EXIT_CODE)
            self.assertIn("idle timeout", stderr_path.read_text(encoding="utf-8"))

    def test_codex_idle_timeout_covers_blocked_stdin_write(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    time.sleep(5)
                    raise SystemExit(0)
                    """
                ),
            )
            output_path = task_path / "context-pack" / "runtime" / "phase1-output-attempt1.jsonl"
            stderr_path = task_path / "context-pack" / "runtime" / "phase1-stderr-attempt1.txt"

            returncode = RUN_PHASES.run_codex(
                root,
                task_path,
                1,
                "x" * (1024 * 1024),
                output_path,
                stderr_path,
                str(fake),
                False,
                False,
                1,
            )

            self.assertEqual(returncode, RUN_PHASES.CODEX_IDLE_EXIT_CODE)
            self.assertIn("idle timeout", stderr_path.read_text(encoding="utf-8"))

    def test_allowed_path_file_change_counts_as_activity(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root, task_path = self.make_task(tmp)
            self.write_contract(root, task_path, ["src"])
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    sys.stdin.read()
                    time.sleep(0.7)
                    from pathlib import Path
                    target = Path.cwd() / "src" / "out.txt"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("ok\\n", encoding="utf-8")
                    time.sleep(1.2)
                    raise SystemExit(0)
                    """
                ),
            )
            output_path = task_path / "context-pack" / "runtime" / "phase1-output-attempt1.jsonl"
            stderr_path = task_path / "context-pack" / "runtime" / "phase1-stderr-attempt1.txt"

            returncode = RUN_PHASES.run_codex(
                root,
                task_path,
                1,
                "prompt",
                output_path,
                stderr_path,
                str(fake),
                False,
                False,
                2,
            )

            self.assertEqual(returncode, 0, stderr_path.read_text(encoding="utf-8"))
            self.assertEqual((root / "src" / "out.txt").read_text(encoding="utf-8"), "ok\n")

    def test_contract_validation_budget_overrides_cli_defaults(self) -> None:
        args = argparse.Namespace(max_attempts=3, ac_timeout=600)
        contract = {
            "validation_budget": {
                "max_attempts": 1,
                "command_timeout_seconds": 5,
            }
        }

        self.assertEqual(RUN_PHASES.contract_validation_budget(contract, args), (1, 5))

    def test_contract_validation_budget_falls_back_to_cli_defaults(self) -> None:
        args = argparse.Namespace(max_attempts=3, ac_timeout=600)

        self.assertEqual(RUN_PHASES.contract_validation_budget({}, args), (3, 600))

    def test_execute_phase_uses_contract_attempt_budget(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root = tmp / "repo"
            task_path = root / "tasks" / "demo"
            (root / "scripts" / "harness").mkdir(parents=True)
            (task_path / "phases").mkdir(parents=True)
            (task_path / "context-pack" / "runtime").mkdir(parents=True)
            (task_path / "context-pack" / "handoffs").mkdir(parents=True)
            for static_file in RUN_PHASES.MANDATORY_STATIC_FILES:
                target = task_path / "context-pack" / "static" / static_file
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("content\n", encoding="utf-8")
            docs = []
            for index in range(5):
                doc_path = root / f"doc{index}.md"
                doc_path.write_text("doc\n", encoding="utf-8")
                docs.append(doc_path.name)
            subprocess_result = subprocess.run(
                ["git", "init"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(subprocess_result.returncode, 0, subprocess_result.stderr)

            contract = {
                "phase": 0,
                "name": "demo",
                "read_first": {"docs": docs, "previous_outputs": []},
                "scope": {"layer": "docs", "allowed_paths": ["src"]},
                "interfaces": [],
                "instructions": [
                    {
                        "id": "P0-001",
                        "task": "Write the handoff.",
                        "expected_evidence": ["context-pack/handoffs/phase0.md"],
                    }
                ],
                "success_criteria": ["The handoff exists."],
                "stop_rules": ["Stop if required context is missing."],
                "fallback_behavior": {
                    "if_blocked": "Write the blocker to the handoff.",
                    "if_tests_fail": "Fix failures inside allowed_paths.",
                },
                "validation_budget": {
                    "max_attempts": 1,
                    "command_timeout_seconds": 600,
                },
                "missing_evidence_behavior": "Treat missing evidence as unresolved.",
                "acceptance_commands": ["false"],
                "required_outputs": ["context-pack/handoffs/phase0.md"],
                "forbidden": [
                    {
                        "rule": "Do not update task status.",
                        "reason": "The runner owns status.",
                    }
                ],
            }
            (task_path / "phases" / "phase0.md").write_text(
                "# Phase 0: demo\n\n## Contract\n\n```json\n"
                + json.dumps(contract, indent=2)
                + "\n```\n",
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "project": "demo",
                        "task": "demo",
                        "docs": docs,
                        "common_docs": [],
                        "phases": [{"phase": 0, "name": "demo", "status": "pending"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            fake = self.make_fake_codex(
                tmp,
                textwrap.dedent(
                    """
                    sys.stdin.read()
                    from pathlib import Path
                    Path.cwd().joinpath("tasks/demo/context-pack/handoffs/phase0.md").write_text(
                        "handoff\\n",
                        encoding="utf-8",
                    )
                    raise SystemExit(0)
                    """
                ),
            )
            args = argparse.Namespace(
                dry_run=False,
                max_attempts=3,
                ac_timeout=600,
                codex_bin=str(fake),
                full_auto=False,
                yolo=False,
                codex_idle_timeout=10,
                failed=False,
            )

            self.assertFalse(RUN_PHASES.execute_phase(root, task_path, args))
            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(task_index["phases"][0]["attempts"], 1)
            self.assertEqual(task_index["phases"][0]["status"], "error")
            repair_packet = json.loads(
                (task_path / "context-pack" / "runtime" / "phase0-repair-packet.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(repair_packet["failure"]["retryable"])

    def test_execute_phase_marks_error_when_attempt_budget_already_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            root = tmp / "repo"
            task_path = root / "tasks" / "demo"
            (root / "scripts" / "harness").mkdir(parents=True)
            (task_path / "phases").mkdir(parents=True)
            (task_path / "context-pack" / "runtime").mkdir(parents=True)
            (task_path / "context-pack" / "handoffs").mkdir(parents=True)
            for static_file in RUN_PHASES.MANDATORY_STATIC_FILES:
                target = task_path / "context-pack" / "static" / static_file
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("content\n", encoding="utf-8")
            docs = []
            for index in range(5):
                doc_path = root / f"doc{index}.md"
                doc_path.write_text("doc\n", encoding="utf-8")
                docs.append(doc_path.name)
            subprocess.run(["git", "init"], cwd=root, text=True, capture_output=True, check=False)

            contract = {
                "phase": 0,
                "name": "demo",
                "read_first": {"docs": docs, "previous_outputs": []},
                "scope": {"layer": "docs", "allowed_paths": ["src"]},
                "interfaces": [],
                "instructions": [
                    {
                        "id": "P0-001",
                        "task": "Write the handoff.",
                        "expected_evidence": ["context-pack/handoffs/phase0.md"],
                    }
                ],
                "success_criteria": ["The handoff exists."],
                "stop_rules": ["Stop if required context is missing."],
                "fallback_behavior": {
                    "if_blocked": "Write the blocker to the handoff.",
                    "if_tests_fail": "Fix failures inside allowed_paths.",
                },
                "validation_budget": {
                    "max_attempts": 1,
                    "command_timeout_seconds": 600,
                },
                "missing_evidence_behavior": "Treat missing evidence as unresolved.",
                "acceptance_commands": ["true"],
                "required_outputs": ["context-pack/handoffs/phase0.md"],
                "forbidden": [
                    {
                        "rule": "Do not update task status.",
                        "reason": "The runner owns status.",
                    }
                ],
            }
            (task_path / "phases" / "phase0.md").write_text(
                "# Phase 0: demo\n\n## Contract\n\n```json\n"
                + json.dumps(contract, indent=2)
                + "\n```\n",
                encoding="utf-8",
            )
            (task_path / "index.json").write_text(
                json.dumps(
                    {
                        "project": "demo",
                        "task": "demo",
                        "docs": docs,
                        "common_docs": [],
                        "phases": [
                            {
                                "phase": 0,
                                "name": "demo",
                                "status": "running",
                                "attempts": 1,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                dry_run=False,
                max_attempts=3,
                ac_timeout=600,
                codex_bin=str(tmp / "unused-codex"),
                full_auto=False,
                yolo=False,
                codex_idle_timeout=10,
                failed=False,
            )

            self.assertFalse(RUN_PHASES.execute_phase(root, task_path, args))
            task_index = json.loads((task_path / "index.json").read_text(encoding="utf-8"))
            phase = task_index["phases"][0]
            self.assertEqual(phase["status"], "error")
            self.assertIn("attempt budget exhausted", phase["error_message"])
            self.assertIn(
                "attempt budget exhausted",
                (task_path / "context-pack" / "runtime" / "phase0-last-error.md").read_text(
                    encoding="utf-8"
                ),
            )


if __name__ == "__main__":
    unittest.main()
