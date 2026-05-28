# Phase 0: runtime bridge

## Contract

```json
{
  "phase": 0,
  "name": "runtime bridge",
  "phase_kind": "implementation",
  "scope": {
    "layer": "SupApp.Runtime",
    "allowed_paths": [
      "SupApp/Sources/SupApp/AppEnvironment.swift"
    ]
  },
  "interfaces": [
    {
      "path": "SupApp/Sources/SupApp/AppEnvironment.swift",
      "symbol": "AppEnvironment.activityTokenPendingSyncer",
      "signature": "let activityTokenPendingSyncer: any ActivityTokenPendingSyncing",
      "visibility": "public",
      "kind": "property",
      "exposes": [
        "ActivityTokenPendingSyncing"
      ],
      "business_rules": [
        "Expose syncer intentionally."
      ]
    },
    {
      "path": "SupApp/Sources/SupApp/ActivityTokenPendingSync.swift",
      "symbol": "ActivityTokenPendingSyncing",
      "signature": "protocol ActivityTokenPendingSyncing { func sync() async }",
      "visibility": "internal",
      "kind": "protocol",
      "business_rules": [
        "Local protocol."
      ]
    }
  ],
  "decision_refs": [
    "D-001"
  ],
  "design_refs": [
    "design.runtime-bridge"
  ],
  "architecture_refs": [
    "A-001"
  ],
  "dependency_policy": {
    "new_dependencies": "forbidden",
    "approved_new_dependencies": [],
    "approved_dependency_manifest_changes": []
  },
  "instructions": [
    {
      "id": "P0-001",
      "task": "Add the runtime bridge while keeping public API visibility coherent.",
      "expected_evidence": [
        "SupApp/Sources/SupApp/AppEnvironment.swift"
      ]
    }
  ],
  "success_criteria": [
    "The bridge compiles."
  ],
  "acceptance_commands": [
    "xcodebuild -project App.xcodeproj -scheme App build"
  ],
  "required_outputs": [
    "context-pack/handoffs/phase0.md"
  ],
  "required_repo_outputs": [
    "SupApp/Sources/SupApp/AppEnvironment.swift"
  ]
}
```
