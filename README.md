# codex-harness

codex-harness는 긴 Codex 작업을 여러 단계로 나누고, 각 단계의 기준과 검증 결과를 파일로 남기는 도구입니다.

대화를 더 길게 이어가는 대신, 작업 기준을 실행 가능한 파일로 고정합니다.

핵심은 세 가지입니다.

```text
대화는 요청을 설명하는 입력이다.
실행 상태는 작업 파일과 실행 기록이다.
완료 여부는 runner가 만든 증거로 판단한다.
```

여기서 **phase contract**는 한 단계가 읽고 고칠 범위와 확인 명령입니다.
**runner proof**는 실제 실행 결과를 담은 기록입니다.
**phase**는 나눠 실행하는 한 작업 단위입니다.
**runner**는 phase를 실행하고 검증하는 하네스 스크립트입니다.

## 문제

Codex와 긴 작업을 하다 보면 기준이 흐려집니다.

처음 정한 조건, 중간에 버린 선택지, 나중에 바뀐 결정이 한 대화 안에 같이 남습니다.
작업이 길어질수록 Codex가 무엇을 기준으로 고쳐야 하는지 흐려집니다.

일반적인 “요청 → 긴 대화 → 바로 구현 → 완료 선언” 흐름은 짧은 수정에는 빠릅니다.

하지만 긴 작업에서는 다음 문제가 생깁니다.

- 버린 선택지가 다시 살아납니다.
- 이전 오해가 다음 단계로 넘어갑니다.
- 검증 명령이 실제로 실행됐는지 불분명합니다.
- 어느 기준으로 완료를 판단했는지 추적하기 어렵습니다.

이 문제는 결과를 바꿉니다.

- 이미 제외한 범위를 다시 고칩니다.
- 테스트 없이 완료했다고 판단합니다.
- 실패 이유가 다음 실행에 전달되지 않습니다.
- 나중에 왜 그 변경을 했는지 설명하기 어렵습니다.

## 모델

codex-harness는 대화를 실행 상태로 쓰지 않습니다.

요청에서 확정된 기준만 파일로 남깁니다.

```text
요청
→ task 문서
→ context-pack
→ phase contract
→ runner proof
```

`context-pack`은 phase가 읽을 문서와 전달 메모를 모은 폴더입니다.
`repair packet`은 실패 이유와 다음 시도에서 고칠 내용을 담은 요약입니다.

각 phase는 새 Codex 세션에서 실행됩니다.

다음 phase는 긴 대화를 읽지 않습니다.
필요한 문서, 컨텍스트, 전달 메모, 실패 요약만 읽습니다.

완료 판정은 runner가 합니다.

`phase<N>-result.json`과 `phase<N>-gate.json`이 없으면 완료가 아닙니다.

자세한 실행 모델은 [docs/model.md](./docs/model.md)를 읽으세요.

## 하는 일

codex-harness는 구현 요청을 다음 구조로 바꿉니다.

- 요구사항과 범위를 정리한 task 문서
- phase마다 필요한 컨텍스트 묶음
- 수정 범위와 확인 명령이 들어간 phase contract
- runner가 실행한 확인 명령
- 실행 증거, 판정, 대조 기록, 최종 결과
- 실패 시 다음 시도에 넘기는 repair packet

## 빠른 시작

대상 프로젝트 루트에서 설치합니다.

```bash
python3 /path/to/codex-harness/scripts/install-codex-harness.py . --all --force
```

이 저장소를 `/Users/leesm/work/side/harness`에 두었다면:

```bash
python3 /Users/leesm/work/side/harness/scripts/install-codex-harness.py . --all --force
```

설치 후 Codex 대화에서 시작합니다.

```text
$codex-harness

list-tasks.py를 만들어줘.
```

첫 실행에서 바로 phase가 생기지 않을 수 있습니다.
하네스는 먼저 확인 질문을 남기거나, 문서 생성 승인을 요청할 수 있습니다.

다음 상태는 세션 출력에서 확인합니다.

```bash
cat .codex-harness/sessions/<run-id>/launcher-result.json
cat .codex-harness/sessions/<run-id>/last-message.md
```

`questions.md`가 있으면 답을 추가합니다.
`docs-approval-request.md`가 있으면 승인한 뒤 다시 실행합니다.

task 경로도 위 두 파일에서 확인합니다.
경로를 확인한 뒤 검증합니다.

```bash
python3 scripts/harness/verify-task.py <task-dir>
python3 scripts/harness/run-phases.py <task-dir> --dry-run
```

phase를 실행합니다.

```bash
python3 scripts/harness/run-phases.py <task-dir> --full-auto
```

더 자세한 설치와 실행 명령은 [docs/quickstart.md](./docs/quickstart.md)에 있습니다.

## 실행 루프

전체 흐름은 다음과 같습니다.

```text
요구사항 확인
→ 요구사항 검토
→ 문서 생성 승인
→ 컨텍스트 수집
→ phase 계획
→ phase 실행
→ 검증
→ 수리 또는 평가
```

요구사항 확인과 검토는 무엇을 만들지 정합니다.
phase 계획은 phase contract를 만듭니다.
phase 실행은 새 Codex 세션에서 진행합니다.
검증과 평가는 runner proof를 봅니다.

## 생성되는 파일

작업을 실행하면 대표적으로 이런 구조가 생깁니다.

```text
tasks/<task-dir>/
  docs/
  phases/
  context-pack/
    static/
    runtime/
      phase<N>-contract.json
      phase<N>-ac-attempt<M>.json
      phase<N>-evidence.json
      phase<N>-gate.json
      phase<N>-reconciliation.json
      phase<N>-repair-packet.md
      phase<N>-result.json
    handoffs/
      phase<N>.md
  index.json
```

세부 구조는 [docs/task-format.md](./docs/task-format.md)와 [docs/runtime-proof.md](./docs/runtime-proof.md)를 보세요.

## 검증하고 기록하는 것

runner가 검증하는 것:

- phase가 독립 실행됐는가
- 상태를 runner만 바꿨는가
- 변경 파일이 `scope.allowed_paths` 안에 있는가
- 확인 명령이 성공했는가
- 필수 산출물이 있는가
- 실행 증거와 gate가 완료를 뒷받침하는가

runner가 기록하는 것:

- Codex에 넘긴 프롬프트
- 실행 직전에 확정한 phase contract
- 확인 명령 실행 결과
- 변경된 파일
- evidence, gate, reconciliation, result
- 실패 시 다음 시도에 넘길 repair packet

마지막 응답도 정해진 형식을 따릅니다.
하지만 마지막 응답은 요약입니다.
완료 기준은 runner proof입니다.

보장하지 않는 것:

- 모든 버그 자동 탐지
- 모든 도구 사용 차단
- 작은 작업의 속도 향상
- Codex의 판단 품질 개선

hooks는 보조 장치입니다.
최종 판정은 runner proof를 기준으로 합니다.

hooks 세부 내용은 [docs/hooks.md](./docs/hooks.md)에 있습니다.

## 언제 쓰나

- 요구사항이 아직 흐릿한 구현 작업
- 한 번에 끝내기 어려운 작업
- 여러 phase로 나눠야 하는 작업
- 완료 판정이 중요한 작업
- 나중에 왜 그렇게 했는지 추적해야 하는 작업
- 실패를 repair packet으로 이어가야 하는 작업

## 언제 안 쓰나

- 한 파일만 가볍게 고치는 작업
- 검증이 필요 없는 임시 수정
- 사람이 직접 고치는 편이 빠른 작업
- 이미 요구사항과 테스트가 매우 명확한 작업
- phase와 proof 파일 관리가 과한 작업

작고 명확한 수정은 일반 Codex가 더 빠를 수 있습니다.

## 문서

- [실행 모델](./docs/model.md)
- [빠른 시작](./docs/quickstart.md)
- [task 형식](./docs/task-format.md)
- [runtime proof](./docs/runtime-proof.md)
- [hooks](./docs/hooks.md)
- [문제 해결](./docs/troubleshooting.md)

## 상태

현재 버전은 `0.1.0`입니다.

이 프로젝트는 Codex 작업을 더 신뢰성 있게 만들기 위한 하네스입니다.
프로젝트 관리 도구도, 여러 에이전트를 조율하는 프레임워크도 아닙니다.

설계 원칙:

- 먼저 명확히 한다.
- 컨텍스트는 파일에 남긴다.
- phase는 새 Codex 세션에서 실행한다.
- 상태는 runner만 바꾼다.
- 주장이 아니라 실행 기록을 검증한다.
- 평가는 새 컨텍스트에서 한다.
