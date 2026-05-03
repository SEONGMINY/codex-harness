# runtime proof

runtime proof는 runner가 남기는 실행 증거입니다.

Codex의 마지막 응답보다 중요합니다.

## 위치

```text
tasks/<task-dir>/context-pack/runtime/
```

## phase 실행 증거

phase가 실행되면 runner는 다음 파일을 만듭니다.

```text
phase<N>-prompt.md
phase<N>-contract.json
phase<N>-checklist.md
phase<N>-output-attempt<M>.jsonl
phase<N>-stderr-attempt<M>.txt
phase<N>-ac-attempt<M>.json
phase<N>-evidence.json
phase<N>-reconciliation.json
phase<N>-reconciliation.md
phase<N>-gate.json
phase<N>-result.json
```

실패하거나 다시 시도하면 다음 파일도 생깁니다.

```text
phase<N>-last-error.md
phase<N>-repair-packet.json
phase<N>-repair-packet.md
```

## 프롬프트

`phase<N>-prompt.md`는 Codex에게 실제로 전달된 프롬프트입니다.

여기에는 다음이 조합됩니다.

- 공통 문서
- task 문서
- 고정 컨텍스트
- 이전 전달 메모
- runtime 실행 기록
- 저장소 스냅샷
- 현재 phase 체크리스트
- 현재 phase 파일

## contract

`phase<N>-contract.json`은 실행 직전에 확정된 phase contract입니다.

Codex가 phase 파일 안의 contract를 바꾸면 runner는 변조로 보고 실패시킵니다.

## 확인 명령 결과

`phase<N>-ac-attempt<M>.json`은 확인 명령 실행 결과입니다.

runner는 이 결과를 gate 판정에 씁니다.

## evidence

`phase<N>-evidence.json`은 관찰된 실행 증거입니다.

주요 내용:

- 변경된 파일
- 명령 실행 결과
- 필수 산출물 존재 여부

## gate

`phase<N>-gate.json`은 통과/실패 판정입니다.

기본 gate:

- 확인 명령
- 필수 산출물
- 수정 범위

하나라도 실패하면 gate는 failed입니다.

## reconciliation

`phase<N>-reconciliation.json`은 contract 지시사항과 실행 증거를 대조한 결과입니다.

상태:

- `satisfied`
- `unverified`
- `blocked`

`unverified`는 자동 매칭 한계일 수 있습니다.
gate가 통과했다면 이것만으로 다시 시도하지는 않습니다.

## result

`phase<N>-result.json`은 완료된 phase의 최종 기록입니다.

이 파일은 runner가 씁니다.
phase를 실행하는 Codex가 직접 쓰면 안 됩니다.

필수 정보:

- phase
- status
- 시도 번호
- Codex 종료 코드
- 변경된 파일
- 실행한 명령
- 필수 산출물
- 산출물 경로

## repair packet

gate나 명령이 실패하면 runner는 repair packet을 씁니다.

```text
phase<N>-repair-packet.json
phase<N>-repair-packet.md
```

다음 시도는 이 packet을 읽고 실패한 항목만 고칩니다.

repair packet에는 다음이 들어갑니다.

- 실패 유형
- 실패 메시지
- 재시도 가능 여부
- 실패한 명령
- 빠진 산출물
- 범위 위반
- 다시 확인할 지시사항
- contract 요약

## evaluation 실행 기록

evaluation은 새 컨텍스트에서 실행됩니다.

필수 실행 기록:

```text
evaluation-command-results.json
evaluation-prompt.md
evaluation-output.jsonl
evaluation-stderr.txt
```

평가까지 요구하려면 다음을 실행합니다.

```bash
python3 scripts/harness/verify-task.py <task-dir> --require-evaluation
```

## 확인 명령

phase 실행 증거를 확인합니다.

```bash
python3 scripts/harness/verify-task.py <task-dir>
find tasks/<task-dir>/context-pack/runtime -maxdepth 1 -type f | sort
find tasks/<task-dir>/context-pack/handoffs -maxdepth 1 -type f | sort
```
