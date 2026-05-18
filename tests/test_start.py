#!/usr/bin/env python3
"""Regression tests for the launcher entrypoint."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START = ROOT / "scripts" / "harness" / "start.py"


class StartLauncherTest(unittest.TestCase):
    def make_repo(self, tmp: Path) -> Path:
        repo = tmp / "repo"
        (repo / ".codex" / "harness" / "scripts" / "skill").mkdir(parents=True)
        (repo / "codex-harness.json").write_text(
            '{"name":"codex-harness","version":"0.1.0"}\n',
            encoding="utf-8",
        )
        (repo / ".codex" / "harness" / "scripts" / "skill" / "SKILL.md").write_text(
            "---\nname: codex-harness\nversion: 0.1.0\n---\n# skill\n",
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
        return repo

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

    def latest_launcher_result(self, repo: Path) -> dict[str, object]:
        result_paths = sorted((repo / ".codex" / "harness" / "sessions").glob("*/launcher-result.json"))
        self.assertTrue(result_paths)
        return json.loads(result_paths[-1].read_text(encoding="utf-8"))

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
                    "--run-phases",
                    "--evaluate",
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
            self.assertEqual(launcher_result["status"], "generated")
            self.assertEqual(launcher_result["runner_returncode"], 0)
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
            self.assertNotIn("--yolo", argv)

    def test_run_phases_failure_blocks_launcher_result(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = self.make_repo(tmp)
            (repo / ".codex" / "harness" / "scripts" / "run-phases.py").write_text(
                "import sys\nprint('phase failed')\nraise SystemExit(7)\n",
                encoding="utf-8",
            )
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
