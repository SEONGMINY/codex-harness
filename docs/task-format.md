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
    "docs/harness/document-scope.md"
  ],
  "docs": [
    "tasks/0-list-tasks/docs/prd.md",
    "tasks/0-list-tasks/docs/flow.md",
    "tasks/0-list-tasks/docs/data-schema.md",
    "tasks/0-list-tasks/docs/code-architecture.md",
    "tasks/0-list-tasks/docs/adr.md"
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
  "read_first": {
    "docs": [
      "docs/harness/runner-contract.md",
      "tasks/0-list-tasks/docs/code-architecture.md",
      "context-pack/static/context-gathering.md"
    ],
    "previous_outputs": []
  },
  "scope": {
    "layer": "runner",
    "allowed_paths": [
      "scripts/harness/run-phases.py"
    ]
  },
  "interfaces": [
    {
      "path": "scripts/harness/run-phases.py",
      "symbol": "execute_phase",
      "signature": "def execute_phase(...) -> bool",
      "business_rules": [
        "phase 상태는 runner만 바꾼다."
      ]
    }
  ],
  "instructions": [
    {
      "id": "P0-001",
      "task": "정해진 범위 안에서 변경을 구현한다.",
      "expected_evidence": [
        "scripts/harness/run-phases.py"
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
  "acceptance_commands": [
    "python3 -m unittest discover -s tests"
  ],
  "required_outputs": [
    "context-pack/handoffs/phase0.md"
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
- phase N > 0이면 `read_first.previous_outputs`가 있어야 합니다.
- `scope.allowed_paths`는 저장소 루트 기준의 수정 가능 경로입니다.
- 문서 작업이 아닌 phase는 `interfaces`를 채웁니다.
- `instructions[*].id`는 phase 안에서 고유해야 합니다.
- `instructions[*].expected_evidence`는 관찰 가능한 증거여야 합니다.
- `success_criteria`는 결과 기준입니다.
- `stop_rules`는 중단해야 하는 조건입니다.
- `fallback_behavior`는 막히거나 테스트가 실패했을 때의 안전한 행동입니다.
- `validation_budget.max_attempts`는 실제 재시도 횟수입니다.
- `validation_budget.command_timeout_seconds`는 확인 명령 제한 시간입니다.
- `acceptance_commands`는 실행 가능한 명령만 둡니다.
- `required_outputs`는 task 경로 기준입니다.
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

권장 구조:

```markdown
# Phase <N> 전달 메모

## 변경 파일

- <path>: <요약>

## 동작

- <바뀐 동작>

## 확인

- `<command>`: <결과>

## 남은 위험

- <남은 위험 또는 없음>
```
