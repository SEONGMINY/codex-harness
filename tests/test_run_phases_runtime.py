#!/usr/bin/env python3
"""Runtime tests for run-phases child Codex handling."""

from __future__ import annotations

import importlib.util
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


if __name__ == "__main__":
    unittest.main()
