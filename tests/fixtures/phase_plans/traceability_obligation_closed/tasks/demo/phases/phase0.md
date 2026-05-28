# Phase 0: boundary validator

## Contract

```json
{
  "phase": 0,
  "name": "boundary validator",
  "phase_kind": "implementation",
  "scope": {
    "layer": "SupApp.Bridge",
    "allowed_paths": [
      "SupApp/Sources/SupApp/Bridge.swift"
    ]
  },
  "design_refs": [
    "obl.boundary"
  ],
  "closes_obligations": [
    "obl.boundary"
  ],
  "instructions": [
    {
      "id": "P0-001",
      "task": "Implement the bridge boundary.",
      "expected_evidence": [
        "SupApp/Sources/SupApp/Bridge.swift"
      ]
    }
  ],
  "success_criteria": [
    "Boundary validator is part of same-phase acceptance."
  ],
  "acceptance_commands": [
    "python3 tests/validate_ios_boundaries.py",
    "xcodebuild -project SupApp.xcodeproj -scheme SupApp build"
  ],
  "command_expectations": [
    {
      "id": "ios-boundary-validator",
      "command": "python3 tests/validate_ios_boundaries.py",
      "role": "acceptance",
      "target": "tests/validate_ios_boundaries.py"
    }
  ],
  "required_outputs": [
    "context-pack/handoffs/phase0.md"
  ],
  "required_repo_outputs": [
    "SupApp/Sources/SupApp/Bridge.swift"
  ]
}
```
