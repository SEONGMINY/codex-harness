"""Regression tests for design obligation closure checks."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))

from obligation_ledger import (  # noqa: E402
    assertion_command_refs,
    build_phase_obligation_assertion_outcomes,
    closure_command_refs,
    closure_output_assertions,
    closure_output_contains,
    command_output,
    command_output_truncated,
    design_obligations_by_id,
    display_value,
    output_satisfies_assertion,
    passed_commands_by_ref,
    passed_command_refs,
    passed_command_roles,
    phase_obligation_closure_errors,
)


class ObligationLedgerTest(unittest.TestCase):
    def test_phase_closure_requires_passed_command_role(self) -> None:
        obligations = design_obligations_by_id(
            {
                "obligations": [
                    {
                        "id": "obl.acceptance",
                        "class": "acceptance_validity",
                        "required_command_roles": ["acceptance"],
                    }
                ]
            }
        )

        errors = phase_obligation_closure_errors(
            phase_number=0,
            contract={"closes_obligations": ["obl.acceptance"]},
            phase_result={
                "commands_run": [
                    {"id": "unit-tests", "role": "fixture", "exit_code": 0},
                    {"id": "acceptance", "role": "acceptance", "exit_code": 1},
                ]
            },
            obligations=obligations,
        )

        self.assertTrue(any("missing required roles" in error for error in errors), errors)

    def test_phase_closure_accepts_passed_required_role(self) -> None:
        obligations = design_obligations_by_id(
            {
                "obligations": [
                    {
                        "id": "obl.acceptance",
                        "class": "acceptance_validity",
                        "required_command_roles": ["acceptance"],
                    }
                ]
            }
        )

        errors = phase_obligation_closure_errors(
            phase_number=0,
            contract={"closes_obligations": ["obl.acceptance"]},
            phase_result={
                "commands_run": [
                    {"id": "unit-tests", "role": "acceptance", "exit_code": 0},
                ]
            },
            obligations=obligations,
        )

        self.assertEqual(errors, [])

    def test_phase_closure_requires_specific_command_ref_when_declared(self) -> None:
        obligations = design_obligations_by_id(
            {
                "obligations": [
                    {
                        "id": "obl.acceptance",
                        "class": "acceptance_validity",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["unit-tests"],
                    }
                ]
            }
        )

        errors = phase_obligation_closure_errors(
            phase_number=0,
            contract={"closes_obligations": ["obl.acceptance"]},
            phase_result={
                "commands_run": [
                    {"id": "different-tests", "role": "acceptance", "exit_code": 0},
                ]
            },
            obligations=obligations,
        )

        self.assertTrue(any("closure_command_refs" in error for error in errors), errors)

    def test_phase_closure_accepts_specific_passed_command_ref(self) -> None:
        obligations = design_obligations_by_id(
            {
                "obligations": [
                    {
                        "id": "obl.acceptance",
                        "class": "acceptance_validity",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["unit-tests"],
                    }
                ]
            }
        )

        errors = phase_obligation_closure_errors(
            phase_number=0,
            contract={"closes_obligations": ["obl.acceptance"]},
            phase_result={
                "commands_run": [
                    {"id": "unit-tests", "role": "acceptance", "exit_code": 0},
                ]
            },
            obligations=obligations,
        )

        self.assertEqual(errors, [])

    def test_closure_output_contains_must_match_referenced_command_output(self) -> None:
        obligations = design_obligations_by_id(
            {
                "obligations": [
                    {
                        "id": "obl.acceptance",
                        "class": "acceptance_validity",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["unit-tests"],
                        "closure_output_contains": ["BOUNDARY_OK"],
                    }
                ]
            }
        )

        errors = phase_obligation_closure_errors(
            phase_number=0,
            contract={"closes_obligations": ["obl.acceptance"]},
            phase_result={
                "commands_run": [
                    {
                        "id": "unit-tests",
                        "role": "acceptance",
                        "exit_code": 0,
                        "output_tail": "tests passed",
                    },
                ]
            },
            obligations=obligations,
        )

        self.assertTrue(any("closure_output_assertions" in error for error in errors), errors)

    def test_closure_output_contains_accepts_referenced_command_output(self) -> None:
        obligations = design_obligations_by_id(
            {
                "obligations": [
                    {
                        "id": "obl.acceptance",
                        "class": "acceptance_validity",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["unit-tests"],
                        "closure_output_contains": ["BOUNDARY_OK"],
                    }
                ]
            }
        )

        errors = phase_obligation_closure_errors(
            phase_number=0,
            contract={"closes_obligations": ["obl.acceptance"]},
            phase_result={
                "commands_run": [
                    {
                        "id": "unit-tests",
                        "role": "acceptance",
                        "exit_code": 0,
                        "output_tail": "BOUNDARY_OK",
                    },
                ]
            },
            obligations=obligations,
        )

        self.assertEqual(errors, [])

    def test_closure_output_assertions_exact_line_rejects_substring_false_positive(self) -> None:
        obligations = design_obligations_by_id(
            {
                "obligations": [
                    {
                        "id": "obl.acceptance",
                        "class": "acceptance_validity",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["unit-tests"],
                        "closure_output_assertions": [
                            {"type": "exact_line", "value": "BOUNDARY_OK"}
                        ],
                    }
                ]
            }
        )

        errors = phase_obligation_closure_errors(
            phase_number=0,
            contract={"closes_obligations": ["obl.acceptance"]},
            phase_result={
                "commands_run": [
                    {
                        "id": "unit-tests",
                        "role": "acceptance",
                        "exit_code": 0,
                        "output_tail": "BOUNDARY_OK missing",
                    },
                ]
            },
            obligations=obligations,
        )

        self.assertTrue(any("exact_line:" in error for error in errors), errors)
        self.assertFalse(any("BOUNDARY_OK" in error for error in errors), errors)

    def test_closure_output_assertions_exact_line_accepts_trimmed_line(self) -> None:
        obligations = design_obligations_by_id(
            {
                "obligations": [
                    {
                        "id": "obl.acceptance",
                        "class": "acceptance_validity",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["unit-tests"],
                        "closure_output_assertions": [
                            {"type": "exact_line", "value": "BOUNDARY_OK"}
                        ],
                    }
                ]
            }
        )

        errors = phase_obligation_closure_errors(
            phase_number=0,
            contract={"closes_obligations": ["obl.acceptance"]},
            phase_result={
                "commands_run": [
                    {
                        "id": "unit-tests",
                        "role": "acceptance",
                        "exit_code": 0,
                        "output_tail": "setup\n  BOUNDARY_OK  \nteardown",
                    },
                ]
            },
            obligations=obligations,
        )

        self.assertEqual(errors, [])

    def test_closure_output_assertions_fail_closed_for_truncated_output(self) -> None:
        obligations = design_obligations_by_id(
            {
                "obligations": [
                    {
                        "id": "obl.acceptance",
                        "class": "acceptance_validity",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["unit-tests"],
                        "closure_output_assertions": [
                            {"type": "exact_line", "value": "BOUNDARY_OK"}
                        ],
                    }
                ]
            }
        )

        errors = phase_obligation_closure_errors(
            phase_number=0,
            contract={"closes_obligations": ["obl.acceptance"]},
            phase_result={
                "commands_run": [
                    {
                        "id": "unit-tests",
                        "role": "acceptance",
                        "exit_code": 0,
                        "output_truncated": True,
                        "output_tail": "BOUNDARY_OK",
                    },
                ]
            },
            obligations=obligations,
        )

        self.assertTrue(any("output is truncated" in error for error in errors), errors)

    def test_stored_assertion_outcome_closes_without_tail_recalculation(self) -> None:
        design_contract = {
            "obligations": [
                {
                    "id": "obl.acceptance",
                    "class": "acceptance_validity",
                    "required_command_roles": ["acceptance"],
                    "closure_command_refs": ["unit-tests"],
                    "closure_output_assertions": [
                        {"type": "exact_line", "value": "BOUNDARY_OK"}
                    ],
                }
            ]
        }
        obligations = design_obligations_by_id(design_contract)
        phase_result = {
            "schema_version": 1,
            "commands_run": [
                {
                    "id": "unit-tests",
                    "role": "acceptance",
                    "exit_code": 0,
                    "output": "setup\nBOUNDARY_OK\nteardown",
                },
            ]
        }
        phase_result["obligation_closure_assertions"] = build_phase_obligation_assertion_outcomes(
            contract={"closes_obligations": ["obl.acceptance"]},
            phase_result=phase_result,
            obligations=obligations,
        )
        phase_result["commands_run"][0].pop("output")
        phase_result["commands_run"][0]["output_truncated"] = True
        phase_result["commands_run"][0]["output_tail"] = "[truncated]\nteardown"

        errors = phase_obligation_closure_errors(
            phase_number=0,
            contract={"closes_obligations": ["obl.acceptance"]},
            phase_result=phase_result,
            obligations=obligations,
        )

        self.assertEqual(errors, [])

    def test_latest_schema_requires_runner_owned_assertion_outcomes(self) -> None:
        obligations = design_obligations_by_id(
            {
                "obligations": [
                    {
                        "id": "obl.acceptance",
                        "class": "acceptance_validity",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["unit-tests"],
                        "closure_output_assertions": [
                            {"type": "exact_line", "value": "BOUNDARY_OK"}
                        ],
                    }
                ]
            }
        )

        errors = phase_obligation_closure_errors(
            phase_number=0,
            contract={"closes_obligations": ["obl.acceptance"]},
            phase_result={
                "schema_version": 1,
                "commands_run": [
                    {
                        "id": "unit-tests",
                        "role": "acceptance",
                        "exit_code": 0,
                        "output_tail": "BOUNDARY_OK",
                    },
                ],
            },
            obligations=obligations,
        )

        self.assertTrue(any("missing runner-owned obligation_closure_assertions" in error for error in errors), errors)

    def test_legacy_result_without_schema_can_use_output_fallback(self) -> None:
        obligations = design_obligations_by_id(
            {
                "obligations": [
                    {
                        "id": "obl.acceptance",
                        "class": "acceptance_validity",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["unit-tests"],
                        "closure_output_assertions": [
                            {"type": "exact_line", "value": "BOUNDARY_OK"}
                        ],
                    }
                ]
            }
        )

        errors = phase_obligation_closure_errors(
            phase_number=0,
            contract={"closes_obligations": ["obl.acceptance"]},
            phase_result={
                "commands_run": [
                    {
                        "id": "unit-tests",
                        "role": "acceptance",
                        "exit_code": 0,
                        "output_tail": "BOUNDARY_OK",
                    },
                ],
            },
            obligations=obligations,
        )

        self.assertEqual(errors, [])

    def test_command_ref_assertion_does_not_pass_from_other_referenced_command_output(self) -> None:
        obligations = design_obligations_by_id(
            {
                "obligations": [
                    {
                        "id": "obl.acceptance",
                        "class": "acceptance_validity",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["unit-tests", "validator"],
                        "closure_output_assertions": [
                            {
                                "type": "exact_line",
                                "value": "BOUNDARY_OK",
                                "command_ref": "validator",
                            }
                        ],
                    }
                ]
            }
        )

        errors = phase_obligation_closure_errors(
            phase_number=0,
            contract={"closes_obligations": ["obl.acceptance"]},
            phase_result={
                "commands_run": [
                    {
                        "id": "unit-tests",
                        "role": "acceptance",
                        "exit_code": 0,
                        "output_tail": "BOUNDARY_OK",
                    },
                    {
                        "id": "validator",
                        "role": "acceptance",
                        "exit_code": 0,
                        "output_tail": "validator ran without marker",
                    },
                ]
            },
            obligations=obligations,
        )

        self.assertTrue(any("exact_line:" in error for error in errors), errors)

    def test_runner_outcome_records_declared_command_ref(self) -> None:
        design_contract = {
            "obligations": [
                {
                    "id": "obl.acceptance",
                    "class": "acceptance_validity",
                    "required_command_roles": ["acceptance"],
                    "closure_command_refs": ["unit-tests", "validator"],
                    "closure_output_assertions": [
                        {
                            "type": "exact_line",
                            "value": "BOUNDARY_OK",
                            "command_ref": "validator",
                        }
                    ],
                }
            ]
        }

        outcomes = build_phase_obligation_assertion_outcomes(
            contract={"closes_obligations": ["obl.acceptance"]},
            phase_result={
                "commands_run": [
                    {
                        "id": "unit-tests",
                        "role": "acceptance",
                        "exit_code": 0,
                        "output": "BOUNDARY_OK",
                    },
                    {
                        "id": "validator",
                        "role": "acceptance",
                        "exit_code": 0,
                        "output": "BOUNDARY_OK",
                    },
                ]
            },
            obligations=design_obligations_by_id(design_contract),
        )

        self.assertEqual(outcomes[0]["command_ref"], "validator")
        self.assertEqual(outcomes[0]["declared_command_ref"], "validator")
        self.assertEqual(outcomes[0]["candidate_command_refs"], ["validator"])

    def test_closure_command_ref_role_must_match_same_command(self) -> None:
        obligations = design_obligations_by_id(
            {
                "obligations": [
                    {
                        "id": "obl.acceptance",
                        "class": "acceptance_validity",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["security-scan"],
                    }
                ]
            }
        )

        errors = phase_obligation_closure_errors(
            phase_number=0,
            contract={"closes_obligations": ["obl.acceptance"]},
            phase_result={
                "commands_run": [
                    {"id": "unit-tests", "role": "acceptance", "exit_code": 0},
                    {"id": "security-scan", "role": "meta", "exit_code": 0},
                ]
            },
            obligations=obligations,
        )

        self.assertTrue(any("missing required roles" in error for error in errors), errors)

    def test_passed_command_roles_ignore_failed_commands(self) -> None:
        self.assertEqual(
            passed_command_roles(
                {
                    "commands_run": [
                        {"role": "acceptance", "exit_code": 1},
                        {"role": "fixture", "exit_code": 0},
                    ]
                }
            ),
            {"fixture"},
        )

    def test_passed_command_refs_include_id_and_command_only_for_passed_commands(self) -> None:
        self.assertEqual(
            passed_command_refs(
                {
                    "commands_run": [
                        {"id": "unit-tests", "command": "python3 -m unittest", "exit_code": 0},
                        {"id": "failed-tests", "command": "false", "exit_code": 1},
                    ]
                }
            ),
            {"unit-tests", "python3 -m unittest"},
        )

    def test_passed_commands_by_ref_maps_id_and_command(self) -> None:
        command = {"id": "unit-tests", "command": "python3 -m unittest", "role": "acceptance", "exit_code": 0}

        self.assertEqual(
            passed_commands_by_ref({"commands_run": [command]}),
            {"unit-tests": command, "python3 -m unittest": command},
        )

    def test_closure_command_refs_ignores_non_string_values(self) -> None:
        self.assertEqual(
            closure_command_refs({"closure_command_refs": ["unit-tests", "", 123]}),
            {"unit-tests"},
        )

    def test_closure_output_contains_ignores_non_string_values(self) -> None:
        self.assertEqual(
            closure_output_contains({"closure_output_contains": ["BOUNDARY_OK", "", 123]}),
            {"BOUNDARY_OK"},
        )

    def test_closure_output_assertions_include_legacy_contains_alias(self) -> None:
        self.assertEqual(
            closure_output_assertions(
                {
                    "closure_output_contains": ["BOUNDARY_OK"],
                    "closure_output_assertions": [
                        {"type": "exact_line", "value": "DONE"}
                    ],
                }
            ),
            [
                {"type": "contains", "value": "BOUNDARY_OK"},
                {"type": "exact_line", "value": "DONE"},
            ],
        )

    def test_closure_output_assertions_preserve_command_ref(self) -> None:
        self.assertEqual(
            closure_output_assertions(
                {
                    "closure_output_assertions": [
                        {"type": "exact_line", "value": "DONE", "command_ref": "validator"}
                    ],
                }
            ),
            [{"type": "exact_line", "value": "DONE", "command_ref": "validator"}],
        )

    def test_assertion_command_refs_narrows_to_declared_ref(self) -> None:
        self.assertEqual(
            assertion_command_refs(
                {"type": "exact_line", "value": "DONE", "command_ref": "validator"},
                {"validator", "unit-tests"},
            ),
            {"validator"},
        )
        self.assertEqual(
            assertion_command_refs(
                {"type": "exact_line", "value": "DONE"},
                {"validator", "unit-tests"},
            ),
            {"validator", "unit-tests"},
        )

    def test_command_output_prefers_output_over_output_tail(self) -> None:
        self.assertEqual(command_output({"output": "full", "output_tail": "tail"}), "full")

    def test_command_output_truncated_detects_marker_or_flag(self) -> None:
        self.assertTrue(command_output_truncated({"output_tail": "[truncated]\nBOUNDARY_OK"}))
        self.assertTrue(command_output_truncated({"output_truncated": True, "output_tail": "BOUNDARY_OK"}))
        self.assertFalse(command_output_truncated({"output_tail": "BOUNDARY_OK"}))

    def test_output_satisfies_assertion_distinguishes_contains_and_exact_line(self) -> None:
        self.assertTrue(
            output_satisfies_assertion(
                "BOUNDARY_OK missing",
                {"type": "contains", "value": "BOUNDARY_OK"},
            )
        )
        self.assertFalse(
            output_satisfies_assertion(
                "BOUNDARY_OK missing",
                {"type": "exact_line", "value": "BOUNDARY_OK"},
            )
        )

    def test_error_display_redacts_sensitive_values(self) -> None:
        self.assertEqual(display_value("token-abc"), "[redacted]")

    def test_missing_output_error_redacts_sensitive_matchers(self) -> None:
        obligations = design_obligations_by_id(
            {
                "obligations": [
                    {
                        "id": "obl.acceptance",
                        "class": "acceptance_validity",
                        "required_command_roles": ["acceptance"],
                        "closure_command_refs": ["unit-tests"],
                        "closure_output_contains": ["token-abc"],
                    }
                ]
            }
        )

        errors = phase_obligation_closure_errors(
            phase_number=0,
            contract={"closes_obligations": ["obl.acceptance"]},
            phase_result={
                "commands_run": [
                    {"id": "unit-tests", "role": "acceptance", "exit_code": 0, "output_tail": "no match"},
                ]
            },
            obligations=obligations,
        )

        self.assertFalse(any("token-abc" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
