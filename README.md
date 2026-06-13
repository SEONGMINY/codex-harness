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
→ docs review status
→ 구현 설계 리뷰
→ phase contract
→ runner proof
```

`context-pack`은 phase가 읽을 문서와 전달 메모를 모은 폴더입니다.
`repair packet`은 실패 이유와 다음 시도에서 고칠 내용을 담은 요약입니다.
`docs-review-status.json`은 task 문서와 정적 컨텍스트가 fresh review를 통과했는지 기록합니다.

각 phase는 새 Codex 세션에서 실행됩니다.

다음 phase는 긴 대화를 읽지 않습니다.
필요한 문서, 컨텍스트, 전달 메모, 실패 요약만 읽습니다.

완료 판정은 runner가 합니다.

`phase<N>-attempt<M>-commit.json`과 `phase<N>-result-attempt<M>.json`이 없으면 완료가 아닙니다.
`phase<N>-result.json`, `phase<N>-gate.json`, `phase<N>-quality.json`은 최신 상태를 보기 위한 runner-owned alias입니다.

자세한 실행 모델은 [docs/model.md](./docs/model.md)를 읽으세요.

## 하는 일

codex-harness는 구현 요청을 다음 구조로 바꿉니다.

- 요구사항과 범위를 정리한 task 문서
- design approval 전에 문서 모순과 승인 누락을 확인하는 docs review gate
- 레이어, 객체 의존성, 공개 인터페이스, API/DB/상태 흐름을 담은 구현 설계 리뷰
- 승인된 설계 리뷰 문서, 정적 evidence bundle, policy pack lineage를 봉인한 design approval
- 승인된 기술 결정과 미결정 항목을 담은 decision registry
- 설계 항목, 리뷰 taxonomy, 리뷰 findings, traceability matrix를 담은 구조화된 design contract
- phase마다 필요한 컨텍스트 묶음
- 수정 범위와 확인 명령이 들어간 phase contract
- bugfix/validation phase의 재현 증거 또는 대체 검증 사유
- 변경 파일을 phase instruction id에 연결한 handoff trace
- task artifact 사이의 관계를 확인하는 read-only relationship graph
- runner가 실행한 확인 명령
- 실행 증거, 판정, 대조 기록, 최종 결과
- 실패 시 다음 시도에 넘기는 repair packet

## 오픈소스 유지관리 목적

이 프로젝트는 Codex를 쓰는 오픈소스 메인테이너가 긴 작업을 더 안전하게 나누어 실행하도록 돕습니다.

특히 다음 유지관리 작업을 목표로 합니다.

- 큰 기능 요청을 승인 가능한 문서와 phase contract로 나누기
- PR 리뷰, 릴리스 준비, 문서 정리처럼 기준이 흐려지기 쉬운 작업에 검증 기록 남기기
- Codex 실행 결과를 주장으로 보지 않고 runtime artifact와 acceptance command로 확인하기
- 실패 원인을 repair packet과 gate 결과로 남겨 다음 시도에서 같은 실수를 줄이기
- 보안, 의존성, scope 변경처럼 메인테이너가 직접 판단해야 하는 결정을 구조화하기

API credit을 받는다면 우선순위는 maintainer automation입니다.
구체적으로는 PR 리뷰 보조, release note 초안 작성, docs review loop 고도화, regression test triage, security-oriented phase 검증에 사용할 계획입니다.

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
cat .codex/harness/sessions/<run-id>/launcher-result.json
cat .codex/harness/sessions/<run-id>/last-message.md
```

`launcher-result.json`의 `documents`에는 메인 세션에서 바로 보여줄 문서 본문이 들어갑니다.
질문, 문서 생성 승인 요청, 구현 설계 리뷰처럼 사용자가 확인해야 하는 문서는 경로만 남기지 않고 본문도 함께 제공합니다.

`questions.md`가 있으면 답을 추가합니다.
`docs-approval-request.md`가 있으면 승인한 뒤 다시 실행합니다.
`implementation-design-review.md`가 있으면 설계를 검토하고 승인한 뒤 다시 실행합니다.

launcher 상태는 항상 하나입니다.

- `questions_needed`
- `docs_approval_needed`
- `docs_blocked`
- `design_approval_needed`
- `planned`
- `generated`
- `blocked`

`docs_blocked`는 design approval 전에 문서 리뷰가 막힌 상태입니다.
새 사용자 결정이 필요하거나 최대 review/cleanup 반복 뒤에도 blocker가 남으면 launcher는 design approval 요청을 만들지 않습니다.
이때 `launcher-result.json`과 `docs-blocked.md`에서 필요한 결정을 확인합니다.

task 경로도 위 두 파일에서 확인합니다.
경로를 확인한 뒤 검증합니다.

```bash
python3 .codex/harness/scripts/verify-task.py <task-dir> --require-design-approval
python3 .codex/harness/scripts/run-phases.py <task-dir> --dry-run
python3 .codex/harness/scripts/review-phase-plan.py <task-dir>
```

phase를 실행합니다.

```bash
python3 .codex/harness/scripts/run-phases.py <task-dir> --full-auto
```

기본 실행 경로는 `codex exec`입니다. Codex app-server thread phase execution은
아직 experimental입니다. 현재 검증된 범위는 one-shot read-only path와
`workspace-write` + `approvalPolicy=never` smoke path의 작은 fixture phase입니다.
Thread completion이나 thread output은 완료 증거가 아니며, phase completion은 계속
runtime artifact, changed-file evidence, handoff, acceptance command, gate,
verifier/preflight 결과가 결정합니다. 더 넓은 migration은 별도 design review가 필요합니다.

Thread-backed phase 실패는 두 종류로 나눕니다. Thread invocation 자체가 실패하면
`failure.type = codex_thread`, `retryable = false`로 fail-closed 처리하며 자동
fallback/retry/repair를 하지 않습니다. Thread invocation은 성공했지만 gate 또는
acceptance command가 실패하면 thread transport failure가 아니므로 기존 Harness
retry policy가 적용됩니다. verifier-triggered repair loop와 thread-owned
retry/repair는 계속 금지됩니다.

현재 설치된 하네스와 runtime proof가 정확히 일치해야 하는 CI/fresh-run 검증에서는 `--strict-current-harness`를 붙입니다.

평가를 실행하려면 `--evaluate`를 붙입니다.
평가가 `rejected`이면 runner는 rejection을 기록하고 멈춥니다.
다음 action은 명시적인 Main/user decision이 있을 때만 진행할 수 있습니다.

```bash
python3 .codex/harness/scripts/run-phases.py <task-dir> --full-auto --evaluate
```

더 자세한 설치와 실행 명령은 [docs/quickstart.md](./docs/quickstart.md)에 있습니다.

task artifact의 관계를 확인하는 relationship graph는 `planned` 또는 `generated` 흐름에서 자동 생성됩니다.
이 그래프는 source of truth가 아니라 기존 artifact에서 파생되는 읽기 전용 출력입니다.

```bash
python3 .codex/harness/scripts/gen-relationship-graph.py <task-dir> --format mermaid
```

## 실행 루프

전체 흐름은 다음과 같습니다.

```text
요구사항 확인
→ 요구사항 검토
→ 문서 생성 승인
→ 컨텍스트 수집
→ docs review / cleanup gate
→ 구현 설계 리뷰 승인
→ phase 계획
→ phase 실행
→ 검증
→ 평가
```

요구사항 확인과 검토는 무엇을 만들지 정합니다.
docs review gate는 문서가 design approval로 넘어가기 전에 blocker와 미승인 결정을 확인합니다.
구현 설계 리뷰는 어떻게 나눠 만들지 정합니다.
design approval은 어떤 설계 문서를 승인했는지 고정합니다.
phase 계획은 phase contract를 만듭니다.
phase 실행은 launcher가 runner를 호출한 뒤 새 Codex 세션에서 진행합니다.
검증과 평가는 runner proof를 봅니다.
평가가 rejected이면 자동 수리를 시작하지 않습니다.
명시적인 Main/user decision이 있을 때만 bounded follow-up을 실행합니다.

## 생성되는 파일

작업을 실행하면 대표적으로 이런 구조가 생깁니다.

```text
tasks/<task-dir>/
  docs/
  phases/
  context-pack/
    static/
    runtime/
      phase<N>-prompt-attempt<M>.md
      phase<N>-contract-attempt<M>.json
      phase<N>-checklist-attempt<M>.md
      phase<N>-evidence-attempt<M>.json
      phase<N>-gate-attempt<M>.json
      phase<N>-quality-attempt<M>.json
      phase<N>-reconciliation-attempt<M>.json
      phase<N>-reconciliation-attempt<M>.md
      phase<N>-handoff-attempt<M>.md
      phase<N>-result-attempt<M>.json
      phase<N>-repair-packet-attempt<M>.json
      phase<N>-repair-packet-attempt<M>.md
      phase<N>-prompt.md
      phase<N>-contract.json
      phase<N>-checklist.md
      phase<N>-ac-attempt<M>.json
      phase<N>-evidence.json
      phase<N>-gate.json
      phase<N>-quality.json
      phase<N>-reconciliation.json
      phase<N>-repair-packet.md
      phase<N>-result.json
      phase<N>-attempt<M>-commit.json
    handoffs/
      phase<N>.md
  index.json
```

세부 구조는 [docs/task-format.md](./docs/task-format.md)와 [docs/runtime-proof.md](./docs/runtime-proof.md)를 보세요.

## 검증하고 기록하는 것

runner가 검증하는 것:

- blocking open decision이 남아 있지 않은가
- phase contract가 승인된 decision과 architecture를 참조하는가
- phase contract의 `design_refs`가 `design-contract.json` 항목을 참조하고 `traceability-matrix.json`에 연결되는가
- `design-contract.json.obligations`가 phase `closes_obligations`로 닫히는가
- implementation phase의 `risk_ledger.required_evidence`가 같은 phase의 acceptance command나 `command_expectations` id로 닫히는가
- acceptance/evaluation command가 shell 제어 토큰 없이 argv로 파싱되고 기본 command policy를 통과하는가
- command output, Codex stdout/stderr, evaluation prompt에 민감 값이 저장되기 전에 redaction 되는가
- acceptance runtime artifact에 적용된 policy pack id/schema/sha256이 남는가
- runner/evaluator/launcher의 주요 runtime artifact가 atomic write로 기록되어 중간 JSON을 읽지 않도록 하는가
- child Codex와 acceptance/evaluation command에 민감 env가 기본 전달되지 않는가
- 리뷰 taxonomy의 필수 관점을 `review-findings.json`이 모두 pass 또는 na 근거로 다뤘는가
- 승인 필요, 트랜잭션, lifecycle/retry claim이 구조화된 design contract와 모순되지 않는가
- persistent artifact가 gitignore로 빠지지 않는가
- 새 dependency가 승인된 정책을 따르는가
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

## 개발과 테스트

주요 회귀 테스트는 Python unittest로 실행합니다.

```bash
python3 -m unittest \
  tests.test_verify_task \
  tests.test_run_phases_runtime \
  tests.test_start \
  tests.test_phase_plan_review \
  tests.test_metrics \
  tests.test_orchestration_protocol
```

하네스 전체 변경 전에는 적어도 다음 검증을 권장합니다.

```bash
python3 -m unittest discover tests
```

## 기여

이슈와 PR은 다음 정보를 포함하면 검토하기 쉽습니다.

- 어떤 Codex 작업 흐름에서 문제가 났는지
- 관련 task 경로와 phase 번호
- 실패한 command와 exit code
- `context-pack/runtime`의 result, gate, repair packet 경로
- 기대한 동작과 실제 동작

보안이나 민감 정보가 포함된 runtime artifact는 공개 이슈에 그대로 붙이지 마세요.
토큰, API key, 개인 정보는 제거한 뒤 최소 재현 예시를 남겨 주세요.

## 문서

- [실행 모델](./docs/model.md)
- [빠른 시작](./docs/quickstart.md)
- [task 형식](./docs/task-format.md)
- [runtime proof](./docs/runtime-proof.md)
- [relationship graph](./docs/relationship-graph.md)
- [hooks](./docs/hooks.md)
- [문제 해결](./docs/troubleshooting.md)

## 상태

현재 버전은 `0.1.5`입니다.

이 프로젝트는 Codex 작업을 더 신뢰성 있게 만들기 위한 하네스입니다.
프로젝트 관리 도구도, 여러 에이전트를 조율하는 프레임워크도 아닙니다.

설계 원칙:

- 먼저 명확히 한다.
- 컨텍스트는 파일에 남긴다.
- phase는 새 Codex 세션에서 실행한다.
- 상태는 runner만 바꾼다.
- 주장이 아니라 실행 기록을 검증한다.
- 평가는 새 컨텍스트에서 한다.

## 라이선스

MIT License입니다.
자세한 내용은 [LICENSE](./LICENSE)를 보세요.
