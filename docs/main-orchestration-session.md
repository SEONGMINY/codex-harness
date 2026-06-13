# Main Orchestration Session 재설계

## 목적

이 문서는 다음 하네스 재설계의 목표 구조를 고정한다.

목표는 SDK runner, exec runner, 또는 다른 실행 엔진을 만드는 것이 아니다.
목표는 현재 Codex 대화를 메인 오케스트레이션 세션으로 삼는 것이다.

```text
Main Orchestration Session
-> 필요할 때만 bounded inquiry thread를 생성/읽기/조향
-> thread output 수집
-> harness artifact 작성 또는 갱신
-> verifier/preflight script 실행
-> 필요한 경우 사용자 승인 요청
```

## 전제

- 이 재설계가 문서화되고 작은 단계로 구현되는 동안 현재 runner 기반 흐름은
  남아 있을 수 있다.
- runner를 실행 엔진에서 제거해도 verifier, preflight, approval hash, artifact
  schema, completion proof는 제거하지 않는다.
- thread output은 주장이다. 증거가 아니다.
- 파일 기반 artifact와 deterministic verification이 source of truth다.
- sub thread 기본값은 0개다.

## Orchestration Invariants

Thread는 architecture primitive가 아니다.
Thread는 role이 아니라 bounded inquiry다.
상태는 thread가 아니라 Main decision과 artifact에 남긴다.

```text
Main owns orchestration.

Artifacts are authoritative.
Thread output is advisory.

Only Main may adopt thread output into artifacts.
Unadopted thread output has no project-state effect.

Sub threads are bounded inquiries, not roles.
The thread answers; it does not steer.

Default sub thread is none.
For non-trivial design/risk review, Main may create at most one disposable skeptical inquiry.

No persistent role threads.
No thread-owned state.
No thread-to-thread delegation.

A sub thread cannot create obligations for future work.
Only Main can create, close, or change obligations.

Verifier failure does not itself authorize repair.
Only Main decision authorizes the next action.

No verifier-to-auto-repair loop.
No open-ended improver/refactorer role.

Fix/application work, if delegated at all, must be tied to an approved finding, fixed scope, explicit allowed files, and Main review.
```

Do not add:

- persistent role threads
- role registry
- thread lifecycle database
- thread graph
- thread-owned state
- thread-to-thread delegation
- verifier-to-auto-repair loop
- default improver/refactorer role
- orchestration runtime disguised as main

## Thread-Backed Phase Execution Policy

Codex thread가 phase execution surface로 쓰이더라도 source of truth는 바뀌지
않는다.

```text
Thread completion is not phase completion.
Thread output is not automatically truth.
Thread state is not project state.

Artifacts, gates, verifier/preflight, approval/hash checks remain authoritative.
```

Thread-backed phase에는 두 종류의 실패가 있다.

### Thread Invocation Failure

Thread invocation 자체가 실패한 경우는 execution surface failure다.

예:

- SDK unavailable
- auth/session failure
- thread start failure
- thread run failure
- timeout
- interrupted
- empty final response
- invalid final response
- partial output
- artifact write failure

정책:

```text
failure.type = codex_thread
retryable = false
phase complete 없음
phase result 없음
automatic fallback 없음
automatic retry 없음
automatic repair 없음
Main/user decision required
```

### Post-Thread Harness Gate/AC Failure

Thread invocation은 성공했지만 Harness gate 또는 acceptance command가 실패한
경우는 thread transport failure가 아니다. 작업 결과가 Harness validation을
통과하지 못한 것이다.

예:

- required output missing
- required repo output missing
- handoff failure
- acceptance command failure
- scope validation failure
- verifier/preflight failure

정책:

```text
existing Harness retry policy applies
```

단, 다음 경우에는 terminal failure가 될 수 있다.

- attempt budget exhausted
- scope contamination
- policy상 non-retryable failure
- Main/user decision required

이 정책은 `codex exec`와 thread-backed execution의 phase retry semantics를
동일하게 유지한다. 목표는 execution mechanism swap이지 phase retry semantics
change가 아니다.

Revised invariant wording:

```text
No automatic fallback/retry/repair for thread invocation failures.

Post-thread Harness gate/AC failures follow the existing Harness retry policy.

Verifier-triggered repair loops remain forbidden.

Thread-owned retry/repair remains forbidden.
```

## Disposable Skeptical Inquiry

Disposable skeptical inquiry는 API가 아니다.
Client abstraction, transport layer, runner, role이 아니다.
Main session이 필요할 때 한 번만 외부 Codex context에 던지는 one-shot
advisory prompt contract다.

### Input

- `bounded_question`: 답해야 하는 제한된 질문
- `scope_summary`: 읽을 수 있는 artifact와 판단하지 말아야 할 범위
- `input_artifacts`: Main이 제공한 approved artifact
- `main_decision_ref`: 이 inquiry를 연 Main decision reference
- `forbidden_actions`: 금지된 행동

### Execution

- Main creates one external Codex context.
- Context receives only the approved artifacts supplied by Main.
- Context answers once.
- Context cannot write files.
- Context cannot delegate.
- Context cannot create obligations.

### Output

- `advisory_answer`
- `findings`
- `uncertainty_or_limits`

### Adoption

- Main reads the answer.
- Main may ignore it.
- Main may adopt selected content into artifacts through a separate Main decision.
- Unadopted output has no project-state effect.

### First Use Case

Main asks:

```text
Given these approved design artifacts, what risks or contradictions should I consider before proceeding?
```

Sub inquiry returns:

- findings
- evidence from supplied artifacts
- uncertainties

Main decides:

- adopt finding into docs
- ask user
- ignore
- revise plan

Success criteria:

- The design remains a prompt contract, not an interface.
- There is no new runtime abstraction.
- There is no new transport abstraction.
- There is no new state model.
- There is no new role model.
- The inquiry answers; it does not steer.
- Main remains the only owner of adoption and obligations.

## 비목표

- SDK runner를 만들지 않는다.
- 새 exec runner abstraction을 만들지 않는다.
- `run-phases.py`를 새 이름의 runner-like orchestration engine으로 대체하지
  않는다.
- persistent role registry, thread graph, automatic router, retry/improve loop를
  추가하지 않는다.
- thread id, final message text, model status를 completion source of truth로
  만들지 않는다.
- sub thread가 decision 승인, scope 확장, completion proof 확정을 하지 못하게
  한다.

## Source of Truth

다음 항목이 권위를 가진다.

- task documents
- approved static context
- approval hash
- verifier/preflight output
- changed-file evidence
- completion proof
- blocked/failed/interrupted artifacts

thread transcript와 bounded inquiry output은 trace metadata 또는 review material일 뿐이다.
artifact가 왜 바뀌었는지 설명할 수는 있지만, 변경이 유효하다는 증거는 아니다.

## 책임 분리

### Main Session

Main session이 소유한다.

- 구현 전 가정 명시
- 결정이 불분명할 때 중단
- sub thread 필요 여부 판단
- disposable sub thread 생성, 읽기, 조향
- sub thread output 수집
- sub thread finding 채택 또는 기각
- harness artifact 작성 또는 갱신
- verifier와 preflight script 실행
- approval request 작성
- verifier-backed artifact를 기준으로 task status 판단

### Disposable Sub Threads

Sub thread는 다음을 할 수 있다.

- bounded question 조사
- fresh context에서 문서 또는 설계 리뷰
- skeptical finding 작성
- verifier failure 원인 분석
- 승인된 finding에 대한 repair 제안

Sub thread는 다음을 해서는 안 된다.

- harness artifact 작성
- 사용자 decision 승인
- approval hash 갱신
- allowed paths 확대
- product, API, schema, storage, dependency, UX decision 추가
- task 또는 phase completion 선언
- 다른 sub thread 생성

## Thread Budget

Sub thread는 선택 사항이다.

다음 budget을 사용한다.

- 기본값: sub thread `0`개
- non-trivial design/risk review: disposable skeptical inquiry `1`개까지
- task 전체 한도: Main이 각각 명시적으로 승인한 bounded inquiry 최대 `3`개

더 많은 thread가 필요해 보이면 task가 너무 크거나 불명확한 것이다.
Main session은 중단하고, 모호한 부분을 요약한 뒤 더 좁은 결정을 요청해야 한다.

## Approved Finding Application

Open-ended improver 또는 refactor thread는 금지한다.
수정 적용을 위임하더라도 approved finding application으로 제한한다.

다음 조건을 모두 만족할 때만 허용한다.

- 구체적인 finding이 이미 있다.
- 사용자 또는 Main session이 해당 finding을 scope 안으로 채택했다.
- allowed paths가 명시되어 있다.
- forbidden changes가 명시되어 있다.
- 새 product/API/schema/storage/dependency/UX decision이 필요하지 않다.
- verifier command와 stop condition이 알려져 있다.

Main session이 제안된 변경을 적용하거나 기각한다.
approved finding application은 최종 patch나 proof를 소유하지 않는다.

## Approval Contract

approval request는 무엇을 승인하는지 정확히 말해야 한다.

반드시 포함한다.

- approval target: docs, design scope, phase plan, implementation permission,
  또는 다른 명시적 대상
- 승인 대상이 아닌 것
- artifact path와 hash
- allowed paths와 forbidden paths
- dependency, policy, sandbox, permission assumption
- open decision 또는 blocker
- verifier/preflight command와 result
- 사용자에게 요구하는 action: approve, request changes, block

approval이 decision을 고정하는 경우 Main session은 "문서를 작성할까요?" 또는
"진행할까요?"만 물어서는 안 된다.

## Failure State Contract

failure state는 artifact-backed여야 한다.

상태 의미는 다음과 같다.

- `blocked`: user decision, approval, policy, permission, design information이
  부족해 진행하면 안 되는 상태
- `failed`: verifier command, schema check, hash check, required output,
  evidence check가 실패한 상태
- `interrupted`: thread, tool, session, timeout, partial output 때문에 신뢰할 수
  있는 completion judgment를 할 수 없는 상태

각 state record는 다음을 포함해야 한다.

- 상태를 관찰한 session
- 관련 thread id가 있으면 해당 id
- input artifact path와 hash
- 가능한 경우 output artifact path와 hash
- reason
- affected task 또는 phase
- next required action

interruption 이후 partial output을 proof로 승격하면 안 된다.
Main session은 먼저 관련 verifier 또는 preflight check를 다시 실행해야 한다.

## Minimal Artifact Contract

재설계에는 작은 artifact surface만 필요하다.
아래 항목은 후보 계약이며, 이 문서만으로 구현을 승인하지 않는다.

- `orchestration-journal.jsonl`: Main session decision과 sub thread reference를
  append-only로 기록
- `bounded-inquiry-record.jsonl`: disposable inquiry scope, input, output, hash
- `verification-results.json`: verifier/preflight command와 result
- `approval-record.json`: approval target, artifact bundle, hash, user action
- `completion-proof.json`: final completion judgment에 사용한 evidence bundle

이 artifact들은 기존 task document와 runtime evidence를 복제하지 않고 참조해야 한다.
이 artifact들은 thread-owned state가 아니며, Main decision을 설명하는 기록이다.

## Guardrails

- 구체적인 이유가 없으면 sub thread를 열지 않는다.
- persistent role보다 one-off review를 선호한다.
- thread consensus보다 verifier-backed artifact를 선호한다.
- gap을 추론으로 메우기보다 decision을 요청하고 멈춘다.
- 더 많은 orchestration보다 더 작은 task를 선호한다.
- 설계에 role registry, router, retry loop, lifecycle database가 필요해지면
  runner를 다시 만든 것이다.

## Initial Implementation Scope

첫 구현은 runner 제거가 아니라 계약을 검증 가능한 형태로 고정하는 것이다.
이 섹션은 Orchestration Invariants를 통과한 뒤에만 실행할 수 있다.

1. `orchestration-journal.jsonl` schema를 정의한다.
2. approval request에 approval target, non-target, artifact path/hash, open
   decision, verifier result를 포함하도록 한다.
3. blocked/failed/interrupted state artifact schema를 정의한다.
4. sub thread output을 source of truth로 쓰지 않는 verifier check를 추가한다.
5. 기존 runner execution path를 제거하지 않고, 새 Main Session 계약과 충돌하는
   지점만 식별한다.

이 범위를 넘는 자동 thread router, retry loop, role lifecycle, runner replacement
구현은 후속 결정 없이는 시작하지 않는다.

## Open Decisions

- implementation thread가 repo file을 직접 수정할 수 있는지, 아니면 Main
  session만 patch를 적용해야 하는지
- `orchestration-journal.jsonl`을 task runtime artifact 아래에 둘지,
  session-level harness directory 아래에 둘지
- approval hash에 sub thread metadata를 포함할지, approved artifact bundle만
  포함할지
- runner execution을 retire하기 전에 기존 `run-phases.py` verification logic 중
  무엇을 standalone verifier utility로 분리할지
