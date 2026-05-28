#!/usr/bin/env python3
"""Regression tests for harness policy pack loading."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))

import policy_pack  # noqa: E402


class PolicyPackTest(unittest.TestCase):
    def test_default_policy_pack_exposes_security_sections(self) -> None:
        command = policy_pack.command_policy()
        environment = policy_pack.environment_policy()
        redaction = policy_pack.redaction_policy()
        metadata = policy_pack.policy_pack_metadata()

        self.assertIn("curl", command["forbidden_executables"])
        self.assertIn("&&", command["shell_control_tokens"])
        self.assertIn(".env", command["sensitive_path_markers"])
        self.assertIn("PATH", environment["allowed_names"])
        self.assertTrue(environment["sensitive_name_patterns"])
        self.assertEqual(redaction["replacement"], "[REDACTED]")
        self.assertTrue(redaction["secret_patterns"])
        self.assertEqual(metadata["id"], "default-security")
        self.assertEqual(metadata["schema_version"], "1")
        self.assertEqual(len(metadata["sha256"]), 64)

    def test_can_load_explicit_custom_policy_pack(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "policy.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "id": "custom",
                        "command": {
                            "shell_control_tokens": [";"],
                            "forbidden_executables": ["example"],
                            "sensitive_path_markers": ["secret-dir"],
                        },
                        "environment": {
                            "allowed_names": ["PATH"],
                            "sensitive_name_patterns": ["TOKEN"],
                        },
                        "redaction": {
                            "replacement": "[REDACTED]",
                            "secret_patterns": ["secret=.*"],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            loaded = policy_pack.load_policy_pack(str(path))
            metadata = policy_pack.policy_pack_metadata(str(path))

        self.assertEqual(loaded["id"], "custom")
        self.assertIn("example", loaded["command"]["forbidden_executables"])
        self.assertIn("curl", loaded["command"]["forbidden_executables"])
        self.assertIn("secret=.*", loaded["redaction"]["secret_patterns"])
        self.assertTrue(any("api" in pattern.lower() for pattern in loaded["redaction"]["secret_patterns"]))
        self.assertEqual(len(metadata["source_sha256"]), 64)
        self.assertEqual(len(metadata["baseline_sha256"]), 64)
        self.assertNotEqual(metadata["sha256"], metadata["source_sha256"])

    def test_custom_policy_pack_cannot_remove_default_command_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "policy.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "id": "custom",
                        "command": {
                            "shell_control_tokens": [],
                            "forbidden_executables": [],
                            "sensitive_path_markers": [],
                        },
                        "environment": {
                            "allowed_names": [],
                            "sensitive_name_patterns": [],
                        },
                        "redaction": {
                            "replacement": "[CUSTOM]",
                            "secret_patterns": [],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            loaded = policy_pack.load_policy_pack(str(path))

        self.assertIn("sh", loaded["command"]["forbidden_executables"])
        self.assertIn("&&", loaded["command"]["shell_control_tokens"])
        self.assertIn(".env", loaded["command"]["sensitive_path_markers"])
        self.assertTrue(loaded["redaction"]["secret_patterns"])

    def test_env_override_is_rejected_without_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "policy.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "id": "override",
                        "command": {"forbidden_executables": ["blocked-by-override"]},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["PYTHONPATH"] = str(HARNESS_DIR)
            env["CODEX_HARNESS_POLICY_PACK"] = str(path)
            env.pop("CODEX_HARNESS_ALLOW_POLICY_PACK_OVERRIDE", None)

            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import policy_pack; print(policy_pack.command_policy())",
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CODEX_HARNESS_ALLOW_POLICY_PACK_OVERRIDE=1", result.stderr)

    def test_env_override_must_resolve_under_trusted_policy_dir(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            (tmp / "codex-harness.json").write_text(
                json.dumps({"policy_pack_env_override": {"allow_env_override": True}}) + "\n",
                encoding="utf-8",
            )
            path = tmp / "policy.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "id": "override",
                        "command": {"forbidden_executables": ["blocked-by-override"]},
                        "environment": {"allowed_names": ["PATH"], "sensitive_name_patterns": ["TOKEN"]},
                        "redaction": {"replacement": "[REDACTED]", "secret_patterns": ["secret=.*"]},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["PYTHONPATH"] = str(HARNESS_DIR)
            env["CODEX_HARNESS_POLICY_PACK"] = str(path)
            env["CODEX_HARNESS_ALLOW_POLICY_PACK_OVERRIDE"] = "1"

            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import policy_pack; print(policy_pack.command_policy())",
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
                cwd=tmp,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must resolve under the harness policy-packs directory", result.stderr)

    def test_env_override_requires_project_config_opt_in(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(HARNESS_DIR)
        env["CODEX_HARNESS_POLICY_PACK"] = str(HARNESS_DIR / "policy-packs" / "default-security.json")
        env["CODEX_HARNESS_ALLOW_POLICY_PACK_OVERRIDE"] = "1"

        with tempfile.TemporaryDirectory() as raw_tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import policy_pack; print(policy_pack.policy_pack_metadata()['id'])",
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
                cwd=raw_tmp,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("policy_pack_env_override.allow_env_override: true", result.stderr)

    def test_env_override_can_select_trusted_policy_pack_with_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            (tmp / "codex-harness.json").write_text(
                json.dumps({"policy_pack_env_override": {"allow_env_override": True}}) + "\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["PYTHONPATH"] = str(HARNESS_DIR)
            env["CODEX_HARNESS_POLICY_PACK"] = str(HARNESS_DIR / "policy-packs" / "default-security.json")
            env["CODEX_HARNESS_ALLOW_POLICY_PACK_OVERRIDE"] = "1"

            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import policy_pack; print(policy_pack.policy_pack_metadata()['id'])",
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
                cwd=tmp,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "default-security")

    def test_env_override_uses_explicit_harness_root_instead_of_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as raw_target, tempfile.TemporaryDirectory() as raw_cwd:
            target = Path(raw_target)
            (target / "codex-harness.json").write_text(
                json.dumps({"policy_pack_env_override": {"allow_env_override": True}}) + "\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["PYTHONPATH"] = str(HARNESS_DIR)
            env["CODEX_HARNESS_ROOT"] = str(target)
            env["CODEX_HARNESS_POLICY_PACK"] = str(HARNESS_DIR / "policy-packs" / "default-security.json")
            env["CODEX_HARNESS_ALLOW_POLICY_PACK_OVERRIDE"] = "1"

            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import policy_pack; print(policy_pack.policy_pack_metadata()['id'])",
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
                cwd=raw_cwd,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "default-security")

    def test_cli_help_does_not_load_invalid_policy_at_import_time(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(HARNESS_DIR)
        env["CODEX_HARNESS_POLICY_PACK"] = "/tmp/does-not-exist.json"
        env["CODEX_HARNESS_ALLOW_POLICY_PACK_OVERRIDE"] = "1"

        for script in ["start.py", "run-phases.py", "evaluate-task.py", "verify-task.py"]:
            result = subprocess.run(
                [sys.executable, str(HARNESS_DIR / script), "--help"],
                env=env,
                text=True,
                capture_output=True,
                check=False,
                cwd=ROOT,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_policy_pack_missing_security_sections_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "weak.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "id": "weak",
                        "command": {"forbidden_executables": []},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as error:
                policy_pack.load_policy_pack(str(path))

        self.assertIn("must include `environment` object", str(error.exception))


if __name__ == "__main__":
    unittest.main()
