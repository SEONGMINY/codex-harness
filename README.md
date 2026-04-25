# codex-harness

Codex 작업을 phase(단계)로 나누고, 컨텍스트와 검증 결과를 파일로 남기는 하네스입니다.

Codex에게 바로 구현을 맡기면 대화가 길어질수록 기준이 흐려질 수 있습니다. codex-harness는 먼저 요구사항과 판단 기준을 고정합니다. 그 다음 필요한 문서만 조합해 새 Codex 세션에 넘기고, 완료 여부는 runner(실행 스크립트) 산출물로 확인합니다.

흐름은 단순합니다.

```text
정리 → 결정 저장 → 컨텍스트 조합 → phase 실행 → 검증
```

## 왜 이 방식인가

긴 대화를 다음 작업에 계속 넘기면 컨텍스트가 탁해집니다.

대화 안에는 필요한 결정만 있는 것이 아닙니다.

- 중간에 나온 틀린 가정
- 폐기된 선택지
- 말하다가 바뀐 기준
- 모델이 이미 가진 자기확신
- 길어진 대화 자체의 잡음

codex-harness는 그래서 체이닝을 쓰지 않습니다.

체이닝 방식:

```text
AGENT.md
  → Plan Agent
    → Verify Agent
      → Execute Agent
```

codex-harness 방식:

```text
대화에서 확정된 결정만 뽑는다
→ docs, context-pack, phase 파일로 저장한다
→ runner가 필요한 파일만 고른다
→ 새 Codex 세션에 넘긴다
→ runner가 완료 여부를 판단한다
```

핵심은 "이전 대화를 이어붙이는 것"이 아닙니다.

"필요한 문서와 증거만 조합하는 것"입니다.

phase 프롬프트는 보통 이렇게 만들어집니다.

```text
현재 phase 프롬프트
= 공통 하네스 규칙
+ task 문서
+ 고정 컨텍스트
+ 이전 phase 요약
+ 현재 phase 지시서
```

`context-pack`은 한 번 쓰고 버리는 프롬프트가 아닙니다. task 폴더에 남는 컨텍스트 저장소입니다. phase마다 필요한 파일만 조합해서 씁니다.

메인 세션도 완료 판정을 맡지 않습니다. 재시도, 실패, 다음 phase 진행은 runner가 결정합니다. Codex가 "완료했다"고 말해도 runner 산출물이 없으면 완료가 아닙니다.

## 용어

이 네 가지만 알면 됩니다.

- `task`: 하나의 작업 단위입니다.
- `phase`: task를 나눈 실행 단위입니다.
- `context-pack`: phase 프롬프트를 만들 때 쓰는 컨텍스트 묶음입니다.
- `runner`: Codex CLI를 실행하고 결과를 검증하는 Python 스크립트입니다.

## 빠른 설치

사용할 프로젝트 폴더에서 실행합니다.

```bash
curl -fsSL https://raw.githubusercontent.com/SEONGMINY/codex-harness/master/scripts/bootstrap-install.py | python3
```

이미 설치된 파일을 덮어쓰려면:

```bash
curl -fsSL https://raw.githubusercontent.com/SEONGMINY/codex-harness/master/scripts/bootstrap-install.py | python3 - --force
```

설치 후 프로젝트에 다음 경로가 생깁니다.

```text
.agents/skills/codex-harness
scripts/harness
```

Codex에서 호출합니다.

```text
$codex-harness
```

## 무엇이 달라지나

일반적인 Codex 사용:

```text
요청 → 바로 구현 → Codex가 완료라고 말함
```

codex-harness 사용:

```text
요청
→ 요구사항 정리
→ 만들 가치 검토
→ 문서와 컨텍스트 저장
→ phase 계획
→ runner가 컨텍스트 조합
→ Codex가 새 세션에서 phase 구현
→ runner가 명령과 산출물로 완료 판단
→ 새 컨텍스트에서 평가
```

코드는 그대로 Codex가 고칩니다. 다만 하네스가 먼저 작업을 잘게 나누고, 각 단계에서 읽을 문서와 확인할 명령을 정해 둡니다. 다음 단계는 긴 대화 전체가 아니라 그 문서들만 보고 시작합니다.

## 잘 맞는 작업

- 요구사항이 아직 모호한 구현 작업
- 한 번에 끝내기엔 큰 작업
- 여러 단계로 나눠야 하는 기능 작업
- Codex의 완료 선언만으로는 불안한 작업
- 여러 저장소에서 같은 Codex 작업 방식을 쓰고 싶은 경우

잘 맞지 않는 작업도 있습니다.

- 한 파일만 가볍게 고치는 작업
- 검증이 필요 없는 임시 수정
- 사람이 직접 고치는 편이 더 빠른 작업

## 기본 흐름

codex-harness는 다음 순서로 진행합니다.

1. 요구사항 정리
2. 요구사항 검토
3. 문서 생성 승인
4. 문서와 컨텍스트 저장
5. 관련 코드와 문서 탐색
6. phase 계획
7. phase 실행
8. 평가

## 1. 요구사항 정리

먼저 무엇을 만들지 정합니다.

확인하는 것:

- 어떤 문제를 푸는가
- 누가 쓰는가
- 어떤 흐름으로 쓰는가
- 어떤 데이터나 파일이 필요한가
- 무엇은 만들지 않을 것인가
- 완료 기준은 무엇인가
- 더 싸게 해결할 방법은 없는가

이 단계에서는 파일을 만들지 않습니다.

## 2. 요구사항 검토

기본값은 "만들지 않는다"입니다.

다음 기준을 통과해야 구현으로 갑니다.

- 구체적인 증거가 있는가
- 이 기능이 없으면 실제 손실이 생기는가
- 수동 운영, 기존 기능, 문서화 같은 더 싼 대안은 없는가
- CLI와 AI 에이전트만으로 실행, 운영, 장애 대응이 가능한가
- 지금 급한 일인가
- 1명이 1~3일 안에 끝낼 MVP인가

통과하지 못하면 구현으로 가지 않습니다.

## 3. 문서 생성 승인

요구사항이 통과해도 바로 파일을 만들지 않습니다.

사용자가 승인해야 다음 문서를 만듭니다.

```text
docs/harness/*
tasks/<task>/docs/*
tasks/<task>/context-pack/*
tasks/<task>/phases/*
```

## 4. 문서와 컨텍스트 저장

승인 후 task 폴더를 만듭니다.

예시:

```text
tasks/0-add-list-tasks/
  docs/
    prd.md
    flow.md
    data-schema.md
    code-architecture.md
    adr.md
  context-pack/
    static/
    runtime/
    handoffs/
  phases/
    phase0.md
    phase1.md
  index.json
```

각 폴더의 역할:

- `docs`: 작업 의도와 설계
- `context-pack/static`: phase가 공통으로 읽을 고정 컨텍스트
- `context-pack/runtime`: runner가 실행 중 만든 증거 파일
- `context-pack/handoffs`: phase가 다음 phase에 남기는 요약

## 5. 관련 코드와 문서 탐색

구현에 필요한 저장소 컨텍스트만 찾습니다.

기록하는 것:

- 관련 파일
- 참고할 기존 패턴
- 실행한 탐색 명령
- 테스트 명령
- 구현 리스크
- 보지 않은 영역과 그 이유

목표는 많이 모으는 것이 아닙니다. 다음 phase가 헷갈리지 않을 만큼만 남깁니다.

## 6. phase 계획

작업을 작은 phase로 나눕니다.

각 phase에는 다음이 있어야 합니다.

- 하나의 목적
- 구체적인 작업 지시
- 실행 가능한 확인 명령
- 필요한 산출물

실행 전에는 task 상태를 확인합니다.

```bash
python3 scripts/harness/verify-task.py <task-dir>
python3 scripts/harness/run-phases.py <task-dir> --dry-run
```

## 7. phase 실행

실제 구현은 runner를 통해 실행합니다.

```bash
python3 scripts/harness/run-phases.py <task-dir> --full-auto
```

역할은 나뉩니다.

- Codex: 코드를 수정하고 handoff를 작성합니다.
- runner: Codex를 실행하고, 확인 명령을 돌리고, 완료 여부를 판단합니다.

Codex가 쓰는 파일:

```text
tasks/<task-dir>/context-pack/handoffs/phase<N>.md
```

runner가 쓰는 파일:

```text
tasks/<task-dir>/context-pack/runtime/phase<N>-prompt.md
tasks/<task-dir>/context-pack/runtime/phase<N>-output-attempt<M>.jsonl
tasks/<task-dir>/context-pack/runtime/phase<N>-stderr-attempt<M>.txt
tasks/<task-dir>/context-pack/runtime/phase<N>-ac-attempt<M>.json
tasks/<task-dir>/context-pack/runtime/phase<N>-result.json
```

## 완료 판단

완료 판단은 Codex가 하지 않습니다.

runner가 합니다.

Codex가 "완료했습니다"라고 말해도 충분하지 않습니다. runner가 확인 명령을 실행하고, 필요한 파일을 확인하고, `phase-result.json`을 만들었을 때 완료로 봅니다.

`phase-result.json` 예시:

```json
{
  "phase": 0,
  "status": "completed",
  "attempt": 1,
  "codex_exit_code": 0,
  "changed_files": ["src/list-tasks.py"],
  "commands_run": [
    {
      "command": "python3 -m py_compile src/list-tasks.py",
      "exit_code": 0
    }
  ],
  "tests_passed": true,
  "required_outputs": [
    {
      "path": "context-pack/handoffs/phase0.md",
      "exists": true
    }
  ],
  "artifacts": {
    "prompt": "context-pack/runtime/phase0-prompt.md",
    "stdout": "context-pack/runtime/phase0-output-attempt1.jsonl",
    "stderr": "context-pack/runtime/phase0-stderr-attempt1.txt",
    "ac_results": "context-pack/runtime/phase0-ac-attempt1.json",
    "handoff": "context-pack/handoffs/phase0.md"
  }
}
```

이 파일은 Codex가 아니라 runner가 만듭니다.

## 8. 평가

구현이 끝나면 새 컨텍스트에서 평가합니다.

```bash
python3 scripts/harness/evaluate-task.py <task-dir> \
  --command "npm test" \
  --full-auto
```

평가 결과까지 확인합니다.

```bash
python3 scripts/harness/verify-task.py <task-dir> --require-evaluation
```

평가에서 보는 것:

- 테스트가 통과했는가
- 처음 정한 완료 기준을 만족했는가
- 범위가 커지지 않았는가
- 폐기했던 선택지가 다시 들어오지 않았는가
- 코드 변경이 목적과 맞는가

## 자주 쓰는 명령

task 생성:

```bash
python3 scripts/harness/init-task.py add-list-tasks \
  --project "Example Project" \
  --prompt-file /tmp/request.md \
  --phase docs \
  --phase implementation \
  --phase tests
```

task 검증:

```bash
python3 scripts/harness/verify-task.py 0-add-list-tasks
```

다음 phase 프롬프트만 생성:

```bash
python3 scripts/harness/run-phases.py 0-add-list-tasks --dry-run
```

phase 실행:

```bash
python3 scripts/harness/run-phases.py 0-add-list-tasks --full-auto
```

특정 phase부터 다시 실행:

```bash
python3 scripts/harness/run-phases.py 0-add-list-tasks --from 2 --full-auto
```

평가:

```bash
python3 scripts/harness/evaluate-task.py 0-add-list-tasks \
  --command "npm test" \
  --full-auto
```

## 폴더 구조

이 저장소:

```text
.
├── .agents/
│   └── skills/
│       └── codex-harness/
│           ├── SKILL.md
│           ├── agents/
│           │   └── openai.yaml
│           └── references/
│               ├── context-pack.md
│               ├── review-gates.md
│               ├── task-format.md
│               ├── testing.md
│               └── workflow.md
├── scripts/
│   ├── bootstrap-install.py
│   ├── install-codex-harness.py
│   └── harness/
│       ├── init-task.py
│       ├── run-phases.py
│       ├── verify-task.py
│       ├── evaluate-task.py
│       └── gen-docs-diff.py
└── tasks/
    └── .gitkeep
```

설치 후 대상 프로젝트:

```text
.
├── .agents/
│   └── skills/
│       └── codex-harness/
└── scripts/
    └── harness/
```

task 실행 중 생성되는 파일:

```text
.
├── docs/
│   └── harness/
│       ├── runner-contract.md
│       ├── testing.md
│       └── document-scope.md
└── tasks/
    └── <task-dir>/
        ├── docs/
        │   ├── prd.md
        │   ├── flow.md
        │   ├── data-schema.md
        │   ├── code-architecture.md
        │   └── adr.md
        ├── phases/
        │   ├── phase0.md
        │   └── phase1.md
        ├── context-pack/
        │   ├── static/
        │   ├── runtime/
        │   └── handoffs/
        └── index.json
```

## 문제 해결

1. Q. `verify-task.py`가 구현 전에 실패합니다

   A. task 문서나 phase 계약이 아직 완성되지 않은 상태입니다.

   확인할 것:

   - task 문서가 비어 있음
   - 컨텍스트 파일이 비어 있음
   - phase에 확인 명령이 없음
   - 필수 산출물이 없음
   - TODO가 남아 있음

   확인 명령:

   ```bash
   python3 scripts/harness/verify-task.py <task-dir>
   ```

   해결:

   - 출력에 나온 파일을 채웁니다.
   - phase에 확인 명령과 필수 산출물을 추가합니다.
   - TODO나 빈 섹션을 제거합니다.

2. Q. Codex는 완료됐다고 했는데 task는 완료가 아닙니다

   A. runner 산출물을 확인합니다.

   확인할 것:

   - `phase<N>-result.json`이 있는가
   - 확인 명령이 성공했는가
   - 필수 산출물이 생성됐는가
   - handoff가 남아 있는가

   확인 명령:

   ```bash
   python3 scripts/harness/verify-task.py <task-dir>
   find tasks/<task-dir>/context-pack/runtime -maxdepth 1 -type f | sort
   find tasks/<task-dir>/context-pack/handoffs -maxdepth 1 -type f | sort
   ```

   해결:

   - 실패한 phase를 고칩니다.
   - 필요한 경우 `--from`으로 해당 phase부터 다시 실행합니다.

3. Q. 설치된 하네스를 업데이트하고 싶습니다

   A. 대상 저장소에서 설치 명령을 다시 실행합니다.

   확인할 것:

   - 기존 하네스 파일을 덮어써도 되는가
   - 대상 저장소 루트에서 실행 중인가

   설치 명령:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/SEONGMINY/codex-harness/master/scripts/bootstrap-install.py | python3 - --force
   ```

   해결:

   - `--force`로 기존 하네스를 덮어씁니다.

## 목표가 아닌 것

codex-harness는 다음을 목표로 하지 않습니다.

- 여러 subagent를 병렬로 돌리는 오케스트레이터
- 프로젝트 관리 도구
- Codex 대체제
- 요구사항 정리를 건너뛰는 방법
- 에이전트의 성공 주장을 믿는 방법
- 모든 작은 작업의 기본 실행 방식

작고 명확한 수정은 일반 Codex가 더 빠를 수 있습니다.

## 설계 원칙

- 먼저 명확히 한다.
- 컨텍스트는 파일에 남긴다.
- phase는 새 Codex 세션에서 실행한다.
- 상태 전이는 runner가 소유한다.
- 주장이 아니라 산출물을 검증한다.
- 평가는 새 컨텍스트에서 한다.
