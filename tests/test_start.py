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
        (repo / "scripts" / "harness" / "skill").mkdir(parents=True)
        (repo / "codex-harness.json").write_text(
            '{"name":"codex-harness","version":"0.1.0"}\n',
            encoding="utf-8",
        )
        (repo / "scripts" / "harness" / "skill" / "SKILL.md").write_text(
            "---\nname: codex-harness\nversion: 0.1.0\n---\n# skill\n",
            encoding="utf-8",
        )
        (repo / "scripts" / "harness" / "start.py").write_text(
            "#!/usr/bin/env python3\n",
            encoding="utf-8",
        )
        (repo / "scripts" / "harness" / "run-phases.py").write_text(
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
        result_paths = sorted((repo / ".codex-harness" / "sessions").glob("*/launcher-result.json"))
        self.assertTrue(result_paths)
        return json.loads(result_paths[-1].read_text(encoding="utf-8"))

    def test_questions_file_sets_questions_needed_status(self) -> None:
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
                    last_message.write_text("questions written\\n", encoding="utf-8")
                    (last_message.parent / "questions.md").write_text("Q?\\n", encoding="utf-8")
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

    def test_docs_approval_request_sets_docs_approval_needed_status(self) -> None:
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
                    last_message.write_text("approval requested\\n", encoding="utf-8")
                    (last_message.parent / "docs-approval-request.md").write_text(
                        "Approve docs?\\n",
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
