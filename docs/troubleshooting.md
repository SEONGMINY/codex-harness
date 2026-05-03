# 문제 해결

막히면 먼저 runner proof를 봅니다.
runner proof는 runner가 남긴 실행 증거입니다.

Codex의 마지막 응답보다 runtime 실행 기록이 중요합니다.

## 구현 전에 검증이 실패합니다

명령:

```bash
python3 scripts/harness/verify-task.py <task-dir>
```

주요 원인:

- 필수 문서가 없음
- 고정 컨텍스트가 비어 있음
- phase 파일에 `TODO`가 남아 있음
- `## Contract` JSON 블록이 없음
- `read_first` 경로가 틀림
- `scope.allowed_paths`가 비어 있음
- 확인 명령이 없음
- 필수 산출물이 없음

해결:

- 출력에 나온 파일을 채웁니다.
- phase contract를 고칩니다.
- `run-phases.py <task-dir> --dry-run`을 다시 실행합니다.

## Codex는 완료라고 했지만 task가 완료가 아닙니다

Codex의 완료 선언은 완료 증거가 아닙니다.

확인:

```bash
python3 scripts/harness/verify-task.py <task-dir>
find tasks/<task-dir>/context-pack/runtime -maxdepth 1 -type f | sort
find tasks/<task-dir>/context-pack/handoffs -maxdepth 1 -type f | sort
```

봐야 할 파일:

- `phase<N>-result.json`
- `phase<N>-gate.json`
- `phase<N>-reconciliation.md`
- `phase<N>-ac-attempt<M>.json`
- `context-pack/handoffs/phase<N>.md`

`phase<N>-result.json`이 없으면 완료가 아닙니다.

## gate가 실패합니다

확인:

```bash
cat tasks/<task-dir>/context-pack/runtime/phase<N>-gate.json
cat tasks/<task-dir>/context-pack/runtime/phase<N>-repair-packet.md
```

주요 원인:

- 확인 명령 실패
- 필수 산출물 누락
- 허용 범위 밖 파일 변경

runner는 다시 시도할 수 있는 실패를 repair packet으로 정리합니다.
다음 시도는 같은 phase에서 실패 항목만 고칩니다.

## repair packet을 어떻게 읽나

먼저 Markdown 요약을 봅니다.

```bash
cat tasks/<task-dir>/context-pack/runtime/phase<N>-repair-packet.md
```

자세한 구조가 필요하면 JSON을 봅니다.

```bash
cat tasks/<task-dir>/context-pack/runtime/phase<N>-repair-packet.json
```

중요한 필드:

- `failure.type`
- `failure.message`
- `failure.retryable`
- `failed_commands`
- `missing_outputs`
- `failed_gate_checks`
- `instruction_results_to_repair`

## phase가 error입니다

먼저 last error를 봅니다.

```bash
cat tasks/<task-dir>/context-pack/runtime/phase<N>-last-error.md
```

phase를 고친 뒤 다시 실행하려면:

```bash
python3 scripts/harness/run-phases.py <task-dir> --from <N> --full-auto
```

`--from`은 해당 phase부터 끝난 상태를 `pending`으로 되돌립니다.

## 시도 예산이 소진됐습니다

메시지:

```text
Phase attempt budget exhausted: attempts=1, max_attempts=1.
```

의미:

- contract의 `validation_budget.max_attempts`만큼 이미 실행했습니다.
- runner가 더 이상 자동으로 다시 시도하지 않습니다.
- phase는 `error`가 됩니다.

해결:

1. `phase<N>-last-error.md`를 읽습니다.
2. `phase<N>-repair-packet.md`를 읽습니다.
3. phase contract나 구현 범위를 고칩니다.
4. 다시 실행합니다.

```bash
python3 scripts/harness/run-phases.py <task-dir> --from <N> --full-auto
```

필요하면 `validation_budget.max_attempts`를 조정합니다.

## 필수 산출물이 없습니다

대표적인 필수 산출물은 phase 전달 메모입니다.

```text
context-pack/handoffs/phase<N>.md
```

Stop hook이 켜져 있으면 Codex가 멈추기 전에 이 누락을 잡을 수 있습니다.

그래도 최종 확인은 runner가 합니다.

## 설치를 업데이트하고 싶습니다

대상 프로젝트 루트에서 다시 설치합니다.

```bash
python3 /path/to/codex-harness/scripts/install-codex-harness.py . --all --force
```

프로젝트 hook까지 갱신하려면:

```bash
python3 /path/to/codex-harness/scripts/install-codex-harness.py . --all --force --with-hooks
```
