# 실행 모델

codex-harness의 핵심은 단순합니다.

대화는 입력입니다.
실행 상태는 파일과 실행 기록입니다.

Codex가 긴 대화를 계속 이어받으면 기준이 흐려집니다.
처음 정한 조건, 중간에 버린 선택지, 나중에 바뀐 결정이 한 흐름에 섞입니다.

codex-harness는 이 문제를 대화가 아니라 파일 구조로 풉니다.

## 기본 원칙

- 사용자의 요청은 작업을 시작하는 입력입니다.
- 확정된 기준은 task 문서에 남깁니다.
- phase는 독립된 Codex 세션에서 실행합니다.
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
→ phase contract
→ runner proof
```

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
- 구체적인 작업 지시
- 성공 기준
- 중단 조건
- 검증 예산
- 확인 명령
- 필요한 산출물
- 금지 규칙

runner는 이 계약을 기준으로 프롬프트, 체크리스트, 실행 증거, gate, 결과 파일을 만듭니다.

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
- `phase<N>-result.json`

이 파일들이 없으면 Codex가 완료했다고 말해도 완료가 아닙니다.

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
