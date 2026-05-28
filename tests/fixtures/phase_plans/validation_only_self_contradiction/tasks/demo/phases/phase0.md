# Phase 0: validator hardening

## Contract

```json
{
  "phase": 0,
  "name": "validator hardening",
  "phase_kind": "validation",
  "scope": {
    "layer": "tests",
    "allowed_paths": [
      "tests/validate_home_live_loader.py"
    ]
  },
  "instructions": [
    {
      "id": "P0-001",
      "task": "Create a repo scanner validator.",
      "expected_evidence": [
        "tests/validate_home_live_loader.py"
      ]
    }
  ],
  "success_criteria": [
    "Validator exists and catches the known repo gap."
  ],
  "verification_evidence": {
    "reproduction": [
      "python3 tests/validate_home_live_loader.py --repo-scan"
    ]
  },
  "acceptance_commands": [
    "python3 tests/validate_home_live_loader.py"
  ],
  "required_outputs": [
    "context-pack/handoffs/phase0.md"
  ],
  "required_repo_outputs": [
    "tests/validate_home_live_loader.py"
  ]
}
```
