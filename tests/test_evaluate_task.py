#!/usr/bin/env python3
"""Regression tests for evaluation Codex execution."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))
SPEC = importlib.util.spec_from_file_location("evaluate_task", HARNESS_DIR / "evaluate-task.py")
assert SPEC is not None
EVALUATE_TASK = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(EVALUATE_TASK)


class EvaluateTaskTest(unittest.TestCase):
    def make_fake_codex(self, tmp: Path) -> Path:
        path = tmp / "fake-codex.py"
        path.write_text(
            "#!/usr/bin/env python3\n"
            "from __future__ import annotations\n"
            "import sys\n"
            + textwrap.dedent(
                """
                assert "--output-schema" in sys.argv, sys.argv
                assert sys.argv[sys.argv.index("--output-schema") + 1].endswith("evaluation-final.schema.json")
                sys.stdin.read()
                print('{"event":"done"}', flush=True)
                raise SystemExit(0)
                """
            ),
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | 0o111)
        return path

    def test_evaluation_codex_uses_output_schema(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            fake = self.make_fake_codex(tmp)
            output_path = tmp / "evaluation-output.jsonl"
            stderr_path = tmp / "evaluation-stderr.txt"

            returncode = EVALUATE_TASK.run_codex(
                tmp,
                "prompt",
                output_path,
                stderr_path,
                str(fake),
                False,
                False,
                10,
                [tmp],
            )

            self.assertEqual(returncode, 0, stderr_path.read_text(encoding="utf-8"))
            self.assertIn('{"event":"done"}', output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
