# 실행 모델

codex-harness의 핵심은 단순합니다.

대화는 입력입니다.
실행 상태는 파일과 실행 기록입니다.

Codex가 긴 대화를 계속 이어받으면 기준이 흐려집니다.
처음 정한 조건, 중간에 버린 선택지, 나중에 바뀐 결정이 한 흐름에 섞입니다.

codex-harness는 이 문제를 대화가 아니라 파일 구조로 풉니다.

launcher는 매번 하나의 상태만 만듭니다.

- `questions_needed`
- `docs_approval_needed`
- `docs_blocked`
- `design_approval_needed`
- `planned`
- `generated`
- `blocked`

상태는 마지막 응답이 아니라 파일로 증명합니다.

## 기본 원칙

- 사용자의 요청은 작업을 시작하는 입력입니다.
- 확정된 기준은 task 문서에 남깁니다.
- 구현 방향을 바꾸는 결정은 승인된 JSON에 남깁니다.
- phase는 launcher가 runner를 호출한 뒤 독립된 Codex 세션에서 실행합니다.
- 완료 여부는 runner가 만든 실행 증거로 판단합니다.
- 실패 이유는 repair packet으로 다음 시도에 넘깁니다.

## 대화 체이닝을 피하는 이유

체이닝은 보통 이런 흐름입니다.

```text
긴 대화
→ 계획 에이전트
→ 검토 에이전트
→ 실행 에이전트
```

이 흐름은 짧은 작업에서는 충분할 수 있습니다.

하지만 긴 작업에서는 문제가 생깁니다.

- 앞 단계의 오해가 다음 단계로 넘어갑니다.
- 버린 선택지가 다시 살아납니다.
- 검토 에이전트의 승인과 실제 확인 명령이 분리됩니다.
- 나중에 어떤 기준으로 작업했는지 추적하기 어렵습니다.

codex-harness는 에이전트 사이의 대화를 넘기지 않습니다.

넘기는 것은 정리된 파일입니다.

```text
요청
→ task 문서
→ context-pack
→ docs review status
→ 구현 설계 리뷰
→ phase contract
→ runner proof
```

`docs_blocked`는 문서 초안 review가 clean verdict에 도달하지 못해 design approval 전에 멈추는 상태입니다.
새 사용자 결정이 필요한 blocker가 있거나 최대 review/cleanup 반복 뒤에도 blocker가 남으면 launcher는 승인 요청을 만들지 않고 `required_decisions`를 보여줘야 합니다.
이 상태는 일반 구현 실패나 완료 상태가 아니라, 문서를 다시 clean review로 만들기 위한 사용자 결정을 기다리는 stop state입니다.

문서 작성 완료는 `tasks/<task-dir>/context-pack/runtime/docs-review-status.json`의 `verdict`가 `clean`이고, status에 기록된 reviewed file hash가 현재 task docs와 일치할 때만 성립합니다.
해시가 달라지면 문서가 review 뒤 바뀐 것이므로 docs complete, design approval, phase contract generation, dry-run, phase execution은 다시 review clean 상태가 될 때까지 통과하지 않습니다.

`design_approval_needed`는 문서 생성 승인 뒤, phase 계획 전에 멈추는 상태입니다.
이 상태에서는 `tasks/<task-dir>/docs/implementation-design-review.md`를 만들고 레이어 구조, 객체/모듈 의존 방향, 공개 인터페이스, API 계약, DB/스토리지 스키마, 상태와 라이프사이클, 트랜잭션 경계를 승인받습니다.
작고 구현 설계가 필요 없는 비구현 작업만 `tasks/<task-dir>/docs/design-review-waiver.md`로 대체할 수 있습니다.

구현 설계가 승인되면 `tasks/<task-dir>/context-pack/static/design-approval.json`에 승인 대상 문서, 정적 evidence bundle, 각 SHA-256 해시를 남깁니다.
승인 뒤 설계 리뷰 문서가 바뀌면 해시가 달라지므로 Plan은 다시 승인받기 전까지 통과하지 않습니다.

## context-pack

`context-pack`은 다음 phase가 읽을 문서와 전달 메모를 모은 폴더입니다.

한 번 쓰고 버리는 프롬프트가 아닙니다.

```text
context-pack/
  static/    # 승인된 결정과 안정적인 자료
  runtime/   # runner가 만든 실행 기록
  handoffs/  # phase가 다음 phase에 남긴 전달 메모
```

`static/`은 작업 기준입니다.
`runtime/`은 실행 증거입니다.
`handoffs/`는 다음 phase가 읽는 짧은 전달 메모입니다.

## phase contract

phase contract는 한 phase의 실행 계약입니다.

계약에는 다음이 들어갑니다.

- 먼저 읽을 문서
- 수정 가능한 파일 범위
- 인터페이스와 비즈니스 규칙
- 승인된 결정 참조
- 승인된 아키텍처 참조
- 의존성 정책
- 구체적인 작업 지시
- 성공 기준
- 중단 조건
- 검증 예산
- 확인 명령
- 필요한 산출물
- 금지 규칙

runner는 이 계약을 기준으로 프롬프트, 체크리스트, 실행 증거, gate, 결과 파일을 만듭니다.

## decision registry

Markdown 문서는 사람이 읽기 위한 설명입니다.
JSON 파일은 runner가 검증하기 위한 기준입니다.

필수 decision 파일:

- `decisions.json`
- `open-decisions.json`
- `architecture.json`
- `dependency-policy.json`
- `context-gathering-budget.json`

blocking open decision이 남아 있으면 Plan과 Generate는 진행할 수 없습니다.
phase contract는 승인된 `decision_refs`와 `architecture_refs`만 참조해야 합니다.
구현 phase의 phase contract는 승인된 구현 설계 리뷰 또는 waiver를 `read_first.docs`에 포함해야 합니다.
구현 phase의 `scope.allowed_paths`와 `required_repo_outputs`는 설계 리뷰의 `Files To Add/Change`에 승인된 경로 안에 있어야 합니다.
구현 방향을 바꾸는 가정은 별도 추측으로 남기지 않습니다. 승인된 기본값은 `decisions.json`에, 미확정이면 `open-decisions.json`에 남깁니다.
bugfix 또는 validation phase는 재현 증거를 `verification_evidence`에 남기거나, 재현이 불가능한 이유와 대체 검증을 함께 남깁니다.

## runner proof

Codex의 마지막 응답은 참고 자료입니다.

완료 기준은 runner proof입니다.

runner가 남기는 핵심 실행 증거는 다음입니다.

- `phase<N>-contract.json`
- `phase<N>-checklist.md`
- `phase<N>-ac-attempt<M>.json`
- `phase<N>-evidence.json`
- `phase<N>-gate.json`
- `phase<N>-reconciliation.json`
- `phase<N>-result-attempt<M>.json`
- `phase<N>-attempt<M>-commit.json`

이 파일들이 없으면 Codex가 완료했다고 말해도 완료가 아닙니다.
`phase<N>-result.json`은 latest alias이므로 사람이 상태를 볼 때는 유용하지만, 완료 proof의 source of truth는 attempt commit과 attempt-scoped result입니다.

## 실패 처리

실패는 대화 기억에 맡기지 않습니다.

runner는 실패 이유를 repair packet으로 남깁니다.

```text
phase<N>-repair-packet.json
phase<N>-repair-packet.md
```

다음 시도는 이 packet을 먼저 읽고, 같은 phase 안에서 실패만 고칩니다.

수정 범위를 넓히거나 다음 phase를 결정하지 않습니다.

## 마지막 응답의 역할

launcher, phase, evaluation 세션의 마지막 응답은 정해진 형식을 따릅니다.

하지만 마지막 응답은 요약입니다.

상태 전이와 완료 판정은 runner가 만든 파일을 봅니다.
