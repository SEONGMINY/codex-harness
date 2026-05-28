# task 형식

task는 실행 가능한 작업 단위입니다.

하나의 task는 문서, 컨텍스트 묶음, phase, index 파일로 구성됩니다.

## 전체 task index

`tasks/index.json`은 전체 task 목록입니다.

`status`, `completed_at`, `failed_at`은 runner가 갱신합니다.

```json
{
  "tasks": [
    {
      "id": 0,
      "name": "list-tasks",
      "dir": "0-list-tasks",
      "status": "pending",
      "created_at": "2026-05-04T10:00:00+09:00"
    }
  ]
}
```

## task index

`tasks/<task-dir>/index.json`은 한 task의 실행 계획입니다.

```json
{
  "project": "Project",
  "task": "list-tasks",
  "prompt": "원래 요청",
  "baseline": "git-sha",
  "created_at": "2026-05-04T10:00:00+09:00",
  "totalPhases": 2,
  "common_docs": [
    "docs/harness/runner-contract.md",
    "docs/harness/testing.md",
    "docs/harness/document-scope.md",
    "docs/harness/implementation-quality.md"
  ],
  "docs": [
    "tasks/0-list-tasks/docs/prd.md",
    "tasks/0-list-tasks/docs/flow.md",
    "tasks/0-list-tasks/docs/data-schema.md",
    "tasks/0-list-tasks/docs/code-architecture.md",
    "tasks/0-list-tasks/docs/adr.md",
    "tasks/0-list-tasks/docs/implementation-design-review.md"
  ],
  "evaluation_commands": [
    "python3 -m unittest discover -s tests"
  ],
  "phases": [
    {
      "phase": 0,
      "name": "implementation",
      "status": "pending",
      "ac_commands": [],
      "required_outputs": [
        "context-pack/handoffs/phase0.md"
      ]
    }
  ]
}
```

phase 상태는 runner만 바꿉니다.

모든 task는 `tasks/<task-dir>/docs/implementation-design-review.md`를 포함해야 합니다.
작고 구현 설계가 필요 없는 비구현 작업만 `tasks/<task-dir>/docs/design-review-waiver.md`로 대체할 수 있습니다.
구현 설계 리뷰는 범위 요약, 레이어 계획, 객체/모듈 의존 방향, 공개 인터페이스, API 계약, DB/스토리지 스키마, 상태와 라이프사이클, 트랜잭션 경계, 추가/변경 파일, Mermaid 다이어그램, 미결정 사항, 승인 체크리스트를 포함해야 합니다.
구현이 phase, 새 파일, 공개 인터페이스, 레이어 경계, 상태 흐름을 만들면 Mermaid 다이어그램은 `flowchart`, `sequenceDiagram`, `stateDiagram-v2` 중 하나로 작성합니다.
`Files To Add/Change`에는 승인된 저장소 경로나 path pattern을 적습니다.
구현 phase의 `scope.allowed_paths`와 `required_repo_outputs`는 이 승인 경로 안에 있어야 합니다.
glob pattern은 승인된 pattern과 완전히 같거나, `scripts/harness/` 같은 승인된 디렉터리 prefix 아래에 있을 때만 허용합니다.

구현 설계 리뷰와 함께 다음 구조화 artifact도 필요합니다.

- `context-pack/static/design-contract.json`: 승인 경로, 설계 obligation, 트랜잭션 경계, lifecycle/retry trigger, 외부 환경 mapping, decision/architecture 참조, persistent artifact를 기록합니다.
- `context-pack/static/review-taxonomy.json`: 리뷰 단계가 반드시 확인할 실패 분류를 기록합니다.
- `context-pack/static/review-findings.json`: 각 taxonomy 항목에 대한 `pass`, `fail`, `na`와 근거를 기록합니다. `pass`는 반드시 `evidence_refs`로 정적 설계 근거를 참조해야 하며, `fail`이 남아 있으면 Plan으로 갈 수 없습니다.
- `context-pack/static/review-coverage.json`: taxonomy와 design obligation 중 무엇을 리뷰했는지 기록하는 coverage ledger입니다. `blocked` 또는 `missing` coverage가 남아 있으면 Plan으로 갈 수 없습니다.
- `context-pack/static/traceability-matrix.json`: `design_ref`를 phase, 파일, evidence에 연결합니다.

Markdown 설계 문서는 사람이 읽는 설명이고, 위 JSON artifact는 runner가 검증하는 계약입니다.
`Files To Add/Change`의 경로와 `design-contract.json.approved_paths`는 같아야 합니다.
승인 필요, TBD, 트랜잭션, retry/lifecycle trigger를 Markdown에 적었다면 대응하는 구조 필드도 채워야 합니다.
persistent artifact 경로는 gitignore로 제외되면 안 됩니다.
`review-findings.json.findings[*].evidence_refs`는 실행 후 runtime proof가 아니라 Plan 전 정적 설계 근거입니다.
허용되는 형식은 `section:<Implementation Design Review heading>`, `path:<approved repo path>`, `design:<design-contract item id>`, `obligation:<design-contract obligation id>`, `decision:<approved decision id>`, `architecture:<architecture id>`입니다.
미결정 `open_decision_refs`는 pass evidence로 사용할 수 없습니다.
기본 taxonomy의 `pass`는 taxonomy별 최소 ref kind도 만족해야 합니다.
`concurrency_atomicity`, `lifecycle_trigger_completeness`, `rollback_idempotency`는 `design:` 또는 `obligation:` 근거가 필요하고, `acceptance_validity`는 `obligation:` 근거가 필요합니다.
`decision_approval_leakage`는 `decision:`, `dependency_direction`은 `architecture:` 또는 `design:`, `artifact_persistence`는 `design:` 또는 `path:`, `implementation_traceability`는 `design:`, `obligation:`, `path:` 중 하나가 필요합니다.
해당 항목이 이번 task에 적용되지 않으면 generic section ref로 `pass` 처리하지 말고 `na`와 rationale을 기록해야 합니다.
기존 task 호환을 위해 승인 경로의 bare path도 허용하지만 새 task는 `path:` prefix를 사용해야 합니다.
외부 URL, 절대 경로, `..`, secret/token/password 같은 민감 참조는 허용하지 않습니다.

구현 설계 승인 뒤에는 다음 파일이 필요합니다.

```json
{
  "schema_version": 3,
  "approved": true,
  "approved_doc": "tasks/0-list-tasks/docs/implementation-design-review.md",
  "approved_doc_sha256": "<sha256>",
  "approved_bundle": [
    {"path": "tasks/0-list-tasks/docs/implementation-design-review.md", "sha256": "<sha256>"},
    {"path": "tasks/0-list-tasks/context-pack/static/design-contract.json", "sha256": "<sha256>"},
    {"path": "tasks/0-list-tasks/context-pack/static/review-taxonomy.json", "sha256": "<sha256>"},
    {"path": "tasks/0-list-tasks/context-pack/static/review-findings.json", "sha256": "<sha256>"},
    {"path": "tasks/0-list-tasks/context-pack/static/review-coverage.json", "sha256": "<sha256>"},
    {"path": "tasks/0-list-tasks/context-pack/static/traceability-matrix.json", "sha256": "<sha256>"},
    {"path": "tasks/0-list-tasks/context-pack/static/decisions.json", "sha256": "<sha256>"},
    {"path": "tasks/0-list-tasks/context-pack/static/open-decisions.json", "sha256": "<sha256>"},
    {"path": "tasks/0-list-tasks/context-pack/static/architecture.json", "sha256": "<sha256>"},
    {"path": "tasks/0-list-tasks/context-pack/static/dependency-policy.json", "sha256": "<sha256>"}
  ],
  "approved_bundle_sha256": "<sha256>",
  "active_policy_pack": {"id": "default-security", "schema_version": "1", "sha256": "<sha256>"},
  "approved_policy_packs": [
    {"id": "default-security", "schema_version": "1", "sha256": "<sha256>", "status": "active"}
  ],
  "approved_policy_packs_sha256": "<sha256>",
  "design_approval_scope_sha256": "<sha256>",
  "approved_at": "2026-05-22T10:00:00+09:00",
  "approval_source": "--design-approved"
}
```

`approved_bundle`은 승인된 설계 문서뿐 아니라 Plan의 정적 truth source를 함께 봉인합니다. 승인 뒤 위 파일 중 하나라도 바뀌면 `verify-task.py --require-design-approval`은 실패해야 합니다.
`approved_policy_packs`는 runtime proof가 사용할 수 있는 policy pack fingerprint lineage입니다. 절대 경로나 로컬 설치 경로는 저장하지 않고 `id`, `schema_version`, `sha256`, 선택적 `status`만 저장합니다.
`status`는 `active`, `historical`, `revoked` 중 하나입니다. 생략하면 `active_policy_pack`과 같은 fingerprint는 `active`, 그 외는 `historical`로 해석합니다. `revoked` 항목은 `revocation_reason`이 필요하고, 선택적으로 `replacement_policy_pack` fingerprint를 기록할 수 있습니다. `revoked` 항목은 일반 verify의 historical proof에서도 제외되며, 전부 revoked이면 명시적 empty lineage로 처리되어 runtime proof를 통과시키지 않습니다.
`active_policy_pack`은 새 phase attempt에 사용할 수 있는 단일 effective policy pack입니다.
일반 verify는 completed runtime artifact의 policy pack이 이 lineage 안에 있는지 확인합니다. `run-phases.py`는 새 phase attempt를 시작하기 전에 현재 policy pack이 `active_policy_pack`과 같은지 확인합니다. `--strict-current-harness`는 여기에 더해 현재 설치본과 runtime proof의 exact match를 요구합니다.
policy lineage의 정렬, revocation 해석, 허용 fingerprint 계산, `design_approval_scope_sha256` 계산은 `scripts/harness/policy_lineage.py`만 소유합니다.
launcher, runner, evaluator, verifier가 서로 다른 parser나 hash 계산식을 두면 approval authority가 분기되므로 금지합니다.
`schema_version: 2` approval은 legacy로 읽을 수 있지만 policy lineage가 없으므로 strict current 검증에서는 재승인 또는 migration이 필요합니다.

파일 위치:

```text
tasks/<task-dir>/context-pack/static/design-approval.json
```

허용되는 상태:

- `pending`
- `running`
- `completed`
- `error`

## phase 파일

phase 파일은 다음 위치를 씁니다.

```text
tasks/<task-dir>/phases/phase<N>.md
```

각 phase는 독립 실행될 수 있어야 합니다.

이전 대화에 의존하면 안 됩니다.

## contract

`## Contract` JSON 블록이 기준입니다.

```json
{
  "phase": 0,
  "name": "implementation",
  "phase_kind": "implementation",
  "read_first": {
    "docs": [
      "docs/harness/runner-contract.md",
      "docs/harness/implementation-quality.md",
      "tasks/0-list-tasks/docs/implementation-design-review.md",
      "tasks/0-list-tasks/docs/code-architecture.md",
      "context-pack/static/context-gathering.md"
    ],
    "previous_outputs": []
  },
  "scope": {
    "layer": "runner",
    "allowed_paths": [
      ".codex/harness/scripts/run-phases.py"
    ]
  },
  "interfaces": [
    {
      "path": ".codex/harness/scripts/run-phases.py",
      "symbol": "execute_phase",
      "signature": "def execute_phase(...) -> bool",
      "visibility": "internal",
      "kind": "function",
      "exposes": [],
      "business_rules": [
        "phase 상태는 runner만 바꾼다."
      ]
    }
  ],
  "decision_refs": [
    "D-001"
  ],
  "design_refs": [
    "txn.pending-token-removal"
  ],
  "closes_obligations": [
    "obl.acceptance-validity"
  ],
  "architecture_refs": [
    "A-001"
  ],
  "risk_ledger": [
    {
      "id": "R0-001",
      "class": "acceptance_validity",
      "action": "verifies",
      "required_evidence": [
        "unit-test-suite"
      ],
      "rationale": "이 phase의 변경은 같은 phase의 acceptance command로 닫혀야 한다."
    }
  ],
  "dependency_policy": {
    "new_dependencies": "forbidden",
    "approved_new_dependencies": [],
    "approved_dependency_manifest_changes": []
  },
  "instructions": [
    {
      "id": "P0-001",
      "task": "정해진 범위 안에서 변경을 구현한다.",
      "expected_evidence": [
        ".codex/harness/scripts/run-phases.py"
      ]
    }
  ],
  "success_criteria": [
    "정해진 범위의 동작이 구현됐고 확인 명령으로 검증된다."
  ],
  "stop_rules": [
    "필수 컨텍스트가 없으면 멈추고 blocked로 보고한다.",
    "scope.allowed_paths 밖 파일이 필요하면 멈추고 blocked로 보고한다."
  ],
  "fallback_behavior": {
    "if_blocked": "막힌 이유와 필요한 결정을 phase handoff에 쓴다.",
    "if_tests_fail": "보고하기 전에 현재 phase 범위 안에서 실패를 고친다."
  },
  "validation_budget": {
    "max_attempts": 2,
    "command_timeout_seconds": 600
  },
  "missing_evidence_behavior": "명령 출력이나 필수 파일로 증명되기 전까지 빠진 증거는 unresolved로 본다.",
  "verification_evidence": {
    "reproduction": [
      "python3 -m unittest tests.test_regression"
    ],
    "fallback_reason": "",
    "alternative_evidence": []
  },
  "command_expectations": [
    {
      "id": "unit-test-suite",
      "command": "python3 -m unittest discover -s tests",
      "role": "acceptance",
      "target": "tests",
      "repo_scan": false
    }
  ],
  "acceptance_commands": [
    "python3 -m unittest discover -s tests"
  ],
  "required_outputs": [
    "context-pack/handoffs/phase0.md"
  ],
  "required_repo_outputs": [
    ".codex/harness/scripts/run-phases.py"
  ],
  "forbidden": [
    {
      "rule": "`tasks/*/index.json`을 직접 수정하지 않는다.",
      "reason": "task와 phase 상태는 runner가 관리한다."
    }
  ]
}
```

## contract 규칙

- `read_first.docs`는 구체적인 문서나 컨텍스트 경로를 나열합니다.
- `phase_kind`는 명시할 수 있으며 `implementation`, `validation`, `bugfix`, `docs`, `qa`, `other` 중 하나입니다. 명시하면 runner/reviewer/verifier의 canonical phase 분류가 됩니다.
- `phase_kind`가 `validation`, `qa`, `docs`이면 product implementation path를 포함하면 안 됩니다.
- 구현 phase의 `read_first.docs`는 `docs/harness/implementation-quality.md`를 포함해야 합니다.
- 구현 phase의 `read_first.docs`는 승인된 `implementation-design-review.md` 또는 `design-review-waiver.md`를 포함해야 합니다.
- 구현 phase의 `scope.allowed_paths`와 `required_repo_outputs`는 설계 리뷰 `Files To Add/Change`의 승인 경로 안에 있어야 합니다.
- phase N > 0이면 `read_first.previous_outputs`가 있어야 합니다.
- `scope.allowed_paths`는 저장소 루트 기준의 수정 가능 경로입니다.
- 문서 작업이 아닌 phase는 `interfaces`를 채웁니다.
- `interfaces[*].visibility`는 선택 필드이며 `open`, `public`, `package`, `internal`, `fileprivate`, `private` 중 하나입니다.
- `interfaces[*].kind`는 선택 필드이며 `type`, `protocol`, `function`, `property`, `method`, `module`, `doc`, `other` 중 하나입니다.
- public/open 인터페이스가 다른 symbol을 타입, 프로토콜, wrapper, callback 등으로 노출하면 `interfaces[*].exposes`에 해당 symbol을 적습니다. Plan review는 public/open 인터페이스가 같은 phase의 non-public 인터페이스 symbol을 노출하는 경우를 차단합니다.
- `visibility`, `kind`, `exposes` 중 하나라도 있으면 이 구조화된 메타데이터가 public API visibility 검증의 기준입니다. `signature` regex는 기존 contract 호환용 fallback입니다.
- 한 phase contract에서 구조화된 interface metadata를 쓰기 시작하면 모든 `interfaces[*]`는 `visibility`와 `kind`를 명시해야 합니다. 일부 항목만 구조화하면 fallback 검증이 조용히 꺼질 수 있으므로 허용하지 않습니다.
- `decision_refs`는 `decisions.json`의 승인된 결정만 참조합니다.
- 구현 phase의 `design_refs`는 `design-contract.json`의 설계 항목 id를 참조해야 합니다.
- `closes_obligations`는 이 phase가 닫는 `design-contract.json.obligations[*].id`를 나열합니다.
- Plan review는 `closes_obligations`가 가리키는 obligation이 존재하고, 같은 phase의 acceptance evidence로 닫히는지 먼저 검증합니다.
- completed phase가 `closes_obligations`를 나열하면 해당 obligation의 `required_command_roles`가 같은 phase의 통과한 `command_expectations[*].role`로 닫혀야 합니다.
- `design-contract.json.obligations[*].closure_command_refs`를 쓰면 해당 obligation은 같은 phase의 통과한 `command_expectations[*].id` 또는 command 문자열로도 닫혀야 하며, `required_command_roles`는 그 closure refs가 가리키는 command들의 role로 충족해야 합니다.
- Swift phase가 SDK/secret/boundary 위험을 도입하거나 수정하면 특정 validator 파일명을 하드코딩하지 않고, 같은 phase에서 `secret_sdk_boundary` obligation을 닫아야 합니다.
- append-preserving read-modify-write나 load/mutate/write 저장소 흐름을 주장하면 같은 phase에서 `transaction_boundary` 또는 `concurrency_atomicity` obligation을 닫아야 합니다.
- `design-contract.json.obligations[*].closure_output_assertions`를 쓰면 `closure_command_refs`가 가리키는 통과 command output이 assertion을 만족해야 합니다.
  지원 형식은 `{ "type": "contains", "value": "BOUNDARY_OK" }`와 `{ "type": "exact_line", "value": "BOUNDARY_OK" }`입니다.
  assertion 객체에 `command_ref`를 넣으면 해당 assertion은 같은 obligation의 `closure_command_refs` 중 그 command 하나에만 귀속됩니다.
  새 phase에서는 substring 위양성을 줄이기 위해 `exact_line`을 우선 사용합니다.
  `secret_sdk_boundary` 같은 보안 경계 obligation은 `contains`와 `closure_output_contains`를 사용할 수 없습니다.
  runner는 command 실행 직후 full output을 메모리에서 평가하고, `phase<N>-obligation-closure-attempt<M>.json`에는 assertion hash와 pass/fail만 저장합니다.
  `phase<N>-result-attempt<M>.json`은 이 ledger artifact를 참조하고 attempt commit marker가 ledger hash를 봉인합니다.
  runner는 latest handoff alias도 `phase<N>-handoff-attempt<M>.md`로 snapshot해 attempt commit marker에 봉인합니다.
  오래된 runtime result처럼 구조화 결과가 없고 command output이 잘린 경우에는 closure proof로 인정하지 않습니다.
- `design-contract.json.obligations[*].closure_output_contains`는 기존 contract 호환용 alias입니다.
  쓰면 `{ "type": "contains", "value": "<entry>" }`와 같은 의미로 처리되며, `closure_command_refs`가 필요합니다.
- `traceability-matrix.json`은 모든 phase `design_refs`를 phase 번호, 파일, evidence에 연결해야 합니다.
- `architecture_refs`는 `architecture.json`의 승인된 구조 참조만 나열합니다.
- 구현 phase는 `risk_ledger`를 포함해야 합니다.
- `risk_ledger[*].required_evidence`는 같은 phase의 `acceptance_commands` 문자열 또는 `command_expectations[*].id`를 정확히 참조해야 합니다.
- `dependency_policy.new_dependencies`는 `forbidden`, `approved_only`, `allowed` 중 하나입니다.
- phase contract의 `dependency_policy`는 `dependency-policy.json`보다 더 넓게 허용할 수 없습니다.
- `approved_only`일 때는 허용된 패키지와 변경 가능한 manifest 경로를 함께 적습니다.
- 이름 검증을 지원하는 manifest는 `package.json`, `pyproject.toml`, `requirements*.txt`입니다.
- lockfile은 대응되는 source manifest가 함께 변경되고 검증될 때만 허용됩니다.
- `instructions[*].id`는 phase 안에서 고유해야 합니다.
- `instructions[*].expected_evidence`는 runner가 관찰할 수 있는 증거여야 합니다.
  같은 phase의 통과한 command 문자열, `required_outputs`, `required_repo_outputs`, 또는 실제 changed file과 매칭되지 않으면 gate가 실패합니다.
  `command_expectations[*].id`를 쓰면 긴 command 문자열 대신 안정적인 command evidence 이름으로 매칭할 수 있습니다.
  호환성을 위해 문자열을 계속 허용하지만, 새 phase에서는 `{ "type": "command", "ref": "unit-test-suite" }`, `{ "type": "required_repo_output", "ref": "src/app.py" }`, `{ "type": "required_output", "ref": "context-pack/handoffs/phase0.md" }`, `{ "type": "changed_file", "ref": "src/app.py" }`처럼 evidence source를 명시하는 object 형식을 선호합니다.
  object 형식은 문자열 compatibility mode보다 엄격합니다. `command.ref`는 같은 contract의 acceptance command 또는 `command_expectations[*].id`여야 하고, output ref는 해당 required output 목록에 있어야 하며, `changed_file.ref`는 `scope.allowed_paths` 안의 repo-relative exact path로 매칭됩니다.
- `success_criteria`는 결과 기준입니다.
- `stop_rules`는 중단해야 하는 조건입니다.
- `fallback_behavior`는 막히거나 테스트가 실패했을 때의 안전한 행동입니다.
- `validation_budget.max_attempts`는 실제 재시도 횟수입니다.
- `validation_budget.command_timeout_seconds`는 확인 명령 제한 시간입니다.
- bugfix 또는 validation 성격의 phase는 `verification_evidence`를 포함해야 합니다.
- 재현 테스트나 재현 명령이 있으면 `verification_evidence.reproduction`에 적습니다.
- 재현이 불가능하면 `verification_evidence.fallback_reason`과 `verification_evidence.alternative_evidence`를 함께 적습니다.
- `command_expectations[*].id`는 필수이며, risk evidence가 참조할 수 있는 안정적인 command id입니다.
- `command_expectations[*].role`이 `reproduction`이면 같은 명령이 `verification_evidence.reproduction`에 있어야 합니다.
- `command_expectations[*].role`이 `acceptance`, `build`, `fixture`, `meta`이면 같은 명령이 `acceptance_commands`에 있어야 합니다.
- `acceptance_commands`는 shell 제어 토큰 없이 argv로 파싱 가능한 명령만 둡니다. `curl`, `ssh`, `rm`, `.env`, `.ssh`처럼 네트워크/파괴적/민감 경로 접근은 기본 command policy에서 막습니다.
- 기본 command/env/redaction 정책은 `.codex/harness/scripts/policy-packs/default-security.json`에서 로드합니다.
- `CODEX_HARNESS_POLICY_PACK` 환경변수는 기본적으로 차단됩니다. 정책 pack을 런타임에서 바꿔야 하면 target root의 `codex-harness.json`에 `policy_pack_env_override.allow_env_override: true`를 명시하고 `CODEX_HARNESS_ALLOW_POLICY_PACK_OVERRIDE=1`을 함께 설정해야 하며, override 경로는 설치된 harness `policy-packs/` 디렉터리 아래로 resolve되어야 합니다.
  외부 임시 파일이나 repository 임의 경로의 정책 pack을 환경변수로 주입하는 방식은 runner/evaluator의 command/env/redaction guard를 약화시킬 수 있으므로 허용하지 않습니다.
- CLI entrypoint는 `--root`를 확정한 뒤 policy를 freeze해야 하며, module import 또는 `--help` 처리 중 policy file을 읽으면 안 됩니다.
- custom policy pack은 default security pack을 대체하지 않고 overlay로 합성됩니다. shell/control token 차단, forbidden executable, sensitive path marker, sensitive env pattern, secret redaction pattern은 기본 pack과 union 처리되어 custom pack이 기본 보안 baseline을 제거할 수 없습니다.
- acceptance runtime artifact에는 effective policy pack id, schema version, sha256 fingerprint가 기록되어야 합니다. custom overlay의 `sha256`은 합성된 effective policy 기준이며, metadata에는 원본 pack `source_sha256`과 baseline `baseline_sha256`도 함께 기록됩니다.
- phase result, AC results, attempt commit, evaluation command results는 runner/evaluator 시작 시점에 측정한 runtime-proof harness attestation과 policy pack fingerprint를 기록해야 합니다.
  verifier는 runner version, attestation 내부 digest, artifact 간 일관성을 확인하지만, 과거 proof 호환성을 위해 일반 verify에서 현재 runner version이나 현재 하네스 파일 hash와의 exact match를 전역 강제하지 않습니다.
  CI처럼 현재 설치된 하네스와 동일한 proof만 허용하려면 `verify-task.py --strict-current-harness`를 사용합니다.
  Phase 실행 중 preflight/final verify에도 같은 기준을 적용하려면 `run-phases.py --strict-current-harness`를 사용합니다.
- command output, Codex stdout/stderr, evaluation prompt는 runtime artifact에 쓰기 전에 policy pack의 secret redaction을 거칩니다.
- child Codex와 acceptance/evaluation command는 policy pack의 env allowlist를 사용하며 token/secret/password/API key 계열 env는 전달하지 않습니다.
- `CODEX_HARNESS_*`는 prefix 전체가 신뢰 경계가 아닙니다. child process에는 하네스가 문서화한 context key만 전달하고, 임의 same-prefix 변수와 `CODEX_HARNESS_ENV_ALLOW` self-service 확장은 기본적으로 전달하지 않습니다.
- runner/evaluator/launcher가 쓰는 주요 runtime proof JSON/Markdown artifact는 같은 디렉터리의 임시 파일에 쓴 뒤 atomic replace로 커밋합니다.
- `required_outputs`는 task 경로 기준입니다.
- `required_repo_outputs`는 저장소 루트 기준의 구현 산출물입니다. 문서/계획 phase에서는 생략할 수 있지만, 구현 phase에서는 구체적인 파일을 나열해야 하며 `scope.allowed_paths` 안에 있어야 합니다.
- `forbidden[*]`는 `rule`과 `reason`을 모두 포함합니다.

## validation_budget

`validation_budget`은 참고값이 아닙니다.

runner가 실제로 사용합니다.

```json
{
  "validation_budget": {
    "max_attempts": 1,
    "command_timeout_seconds": 300
  }
}
```

이 경우:

- phase 시도는 최대 1번입니다.
- 확인 명령 제한 시간은 300초입니다.
- 이미 `attempts >= max_attempts`이면 phase는 `error`가 됩니다.

## handoff

phase는 다음 phase를 위한 전달 메모를 남깁니다.

```text
tasks/<task-dir>/context-pack/handoffs/phase<N>.md
```

handoff가 `blocked`, `partial`, `skipped`, `workaround`, `우회`, `막힘`, `차단`, `부분 구현`처럼 미완료 상태를 말하면 runner gate가 실패합니다. 파일 존재와 확인 명령이 통과해도 완료로 보지 않습니다.
handoff는 `## Change Trace` 섹션에서 필수 task output을 제외한 변경 저장소 파일을 phase instruction id에 연결해야 합니다.

권장 구조:

```markdown
# Phase <N> 전달 메모

## 변경 파일

- <path>: <요약>

## Change Trace

- `<path>`: `<instruction-id>`

## 동작

- <바뀐 동작>

## 확인

- `<command>`: <결과>

## 남은 위험

- <남은 위험 또는 없음>
```
