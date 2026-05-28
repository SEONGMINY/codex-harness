#!/usr/bin/env python3
"""Regression tests for harness command execution policy."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "harness"))

from command_policy import parse_command  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
