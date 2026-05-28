# 문제 해결

막히면 먼저 runner proof를 봅니다.
runner proof는 runner가 남긴 실행 증거입니다.

Codex의 마지막 응답보다 runtime 실행 기록이 중요합니다.

## 구현 전에 검증이 실패합니다

명령:

```bash
python3 .codex/harness/scripts/verify-task.py <task-dir>
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
- `run-phases.py <task-dir> --dry-run`과 `review-phase-plan.py <task-dir>`를 다시 실행합니다.

## Codex는 완료라고 했지만 task가 완료가 아닙니다

Codex의 완료 선언은 완료 증거가 아닙니다.

확인:

```bash
python3 .codex/harness/scripts/verify-task.py <task-dir>
find tasks/<task-dir>/context-pack/runtime -maxdepth 1 -type f | sort
find tasks/<task-dir>/context-pack/handoffs -maxdepth 1 -type f | sort
```

봐야 할 파일:

- `phase<N>-result-attempt<M>.json`
- `phase<N>-attempt<M>-commit.json`
- `phase<N>-gate.json`
- `phase<N>-reconciliation.md`
- `phase<N>-ac-attempt<M>.json`
- `context-pack/handoffs/phase<N>.md`

`phase<N>-result-attempt<M>.json` 또는 `phase<N>-attempt<M>-commit.json`이 없으면 완료가 아닙니다.
`phase<N>-result.json`은 latest alias입니다.

## gate가 실패합니다

확인:

```bash
cat tasks/<task-dir>/context-pack/runtime/phase<N>-gate.json
cat tasks/<task-dir>/context-pack/runtime/phase<N>-repair-packet.md
```

주요 원인:

- 확인 명령 실패
- 필수 산출물 누락
- 구현 산출물(`required_repo_outputs`) 누락
- handoff가 blocked/partial/skipped/workaround 상태를 보고함
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
- `missing_repo_outputs`
- `contaminating_changes`
- `failed_gate_checks`
- `instruction_results_to_repair`

## Cleanup Required가 표시됩니다

`phase<N>-repair-packet.md`의 `Cleanup Required` 섹션에 경로가 있으면 runner가 자동 재시도하지 않습니다.

의미:

- 해당 attempt에서 `scope.allowed_paths` 밖 변경이 관측됐습니다.
- 같은 phase를 바로 재시도하면 오염된 작업트리를 기준으로 판단할 수 있습니다.
- runner는 repair packet을 남기고 phase를 `error`로 멈춥니다.

해결:

1. `contaminating_changes` 경로가 phase scope에 포함돼야 하는지 확인합니다.
2. scope가 맞다면 phase contract의 `scope.allowed_paths`와 필요 시 `required_repo_outputs`를 고칩니다.
3. scope가 틀렸다면 해당 변경을 사람이 검토하거나 정리합니다.
4. 정리 후 `--resume-repair` 또는 `--from <N>`으로 다시 실행합니다.

## phase가 error입니다

먼저 last error를 봅니다.

```bash
cat tasks/<task-dir>/context-pack/runtime/phase<N>-last-error.md
```

phase를 고친 뒤 다시 실행하려면:

```bash
python3 .codex/harness/scripts/run-phases.py <task-dir> --from <N> --full-auto
```

`--from`은 해당 phase부터 끝난 상태를 `pending`으로 되돌립니다.

repair packet을 유지한 채 가장 이른 실패 지점부터 재개하려면:

```bash
python3 .codex/harness/scripts/run-phases.py <task-dir> --resume-repair --full-auto
```

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
python3 .codex/harness/scripts/run-phases.py <task-dir> --from <N> --full-auto
```

필요하면 `validation_budget.max_attempts`를 조정합니다.

## timeout 이후에도 프로세스가 의심됩니다

하네스가 직접 실행하는 장기 subprocess는 timeout 시 새 process group 전체에 종료 신호를 보냅니다.
일반적인 `pnpm install`, 확인 명령, verifier/evaluator, launcher subprocess는 이 경계 안에서 정리됩니다.
Codex 실행은 두 제한을 같이 사용합니다. `--codex-idle-timeout`은 활동이 멈춘 실행을 막고,
`--codex-max-runtime`은 stdout, stderr, 파일 변경이 계속 있어도 전체 실행 시간이 끝없이 늘어나는 것을 막습니다.
launcher가 Generate를 실행할 때 `run-phases.py` 전체를 감싸는 `--runner-timeout`은 기본적으로 꺼져 있습니다.
runner 내부의 phase/evaluation proof가 먼저 실패 이유를 기록하게 하기 위한 선택입니다.
`--subprocess-timeout` 기본값은 `--codex-max-runtime`보다 길어서 evaluator 같은 wrapper가 inner Codex timeout proof보다 먼저 죽지 않게 합니다.

한계:

- 이 cleanup은 POSIX process group 기준입니다.
- 자식이 의도적으로 `setsid`나 double-fork로 group을 탈출하면 완전한 process-tree containment가 아닙니다.
- timeout 로그에 `process cleanup ... could not be confirmed`가 있으면 lock은 풀렸더라도 작업트리 변경이 계속될 수 있으니 실행 중인 프로세스를 확인해야 합니다.

확인:

```bash
ps -ef | grep codex
ps -ef | grep pnpm
ps -ef | grep npm
```

해결:

1. 살아남은 프로세스가 해당 task의 하위 실행인지 확인합니다.
2. 필요하면 프로세스를 수동 종료합니다.
3. 작업트리 변경과 `tasks/<task-dir>/context-pack/runtime/*`를 확인합니다.
4. 오염된 변경이 있으면 정리한 뒤 `--resume-repair` 또는 `--from <N>`으로 재개합니다.

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
