#!/usr/bin/env python3
"""Regression tests for harness command execution policy."""

from __future__ import annotations

import shlex
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "harness"))

from command_policy import parse_command, run_command  # noqa: E402
from process_runner import PROCESS_TIMEOUT_EXIT_CODE  # noqa: E402


class CommandPolicyTest(unittest.TestCase):
    def assert_rejected(self, command: str) -> None:
        _, errors = parse_command(command)
        self.assertTrue(errors, command)

    def test_rejects_shell_execution_modes(self) -> None:
        for command in [
            "sh -c 'echo ok'",
            "bash -lc 'printf ok'",
            "zsh -c 'echo ok'",
        ]:
            self.assert_rejected(command)

    def test_rejects_interpreter_eval_modes(self) -> None:
        for command in [
            "python3 -c 'print(123)'",
            "python3 -cprint(123)",
            "python -c 'print(123)'",
            "node -e 'console.log(123)'",
            "node --eval=console.log(123)",
            "ruby -e 'puts 123'",
            "ruby -eputs 123",
            "perl -e 'print 123'",
            "perl -eprint 123",
        ]:
            self.assert_rejected(command)

    @unittest.skipIf(sys.platform == "win32", "process group cleanup is POSIX-specific")
    def test_timeout_kills_child_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            marker = tmp / "heartbeat.txt"
            child = tmp / "child.py"
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
            parent = tmp / "parent.py"
            parent.write_text(
                textwrap.dedent(
                    """
                    import subprocess
                    import sys
                    import time
                    from pathlib import Path

                    marker = Path(sys.argv[1])
                    subprocess.Popen([sys.executable, sys.argv[2], str(marker)])
                    deadline = time.monotonic() + 5
                    while not marker.exists() and time.monotonic() < deadline:
                        time.sleep(0.05)
                    print("child started", flush=True)
                    time.sleep(30)
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            command = (
                f"{shlex.quote(sys.executable)} "
                f"{shlex.quote(str(parent))} "
                f"{shlex.quote(str(marker))} "
                f"{shlex.quote(str(child))}"
            )

            started = time.monotonic()
            code, output, timed_out, _argv = run_command(command, tmp, timeout=1)
            elapsed = time.monotonic() - started

            self.assertEqual(code, PROCESS_TIMEOUT_EXIT_CODE, output)
            self.assertLess(elapsed, 3.0)
            self.assertTrue(timed_out)
            self.assertIn("[timeout]", output)
            self.assertTrue(marker.exists())
            before = marker.read_text(encoding="utf-8")
            time.sleep(0.5)
            self.assertEqual(marker.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
