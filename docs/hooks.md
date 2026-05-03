# hooks

hooks는 하네스 실행 중 명백한 범위 위반을 줄이기 위한 보조 장치입니다.

최종 판정은 hooks가 아니라 runner proof를 기준으로 합니다.

## 설치

프로젝트에도 hook 설정을 남기려면 다음처럼 설치합니다.

```bash
python3 /path/to/codex-harness/scripts/install-codex-harness.py . --all --force --with-hooks
```

선택 hook도 같이 설치하려면 `--optional-hooks`를 붙입니다.

```bash
python3 /path/to/codex-harness/scripts/install-codex-harness.py . --all --force --with-hooks --optional-hooks
```

## 기본 hook

기본으로 쓰는 hook은 두 개입니다.

### PreToolUse

도구를 쓰기 전에 phase 범위를 확인합니다.

주로 막는 것:

- `scope.allowed_paths` 밖 파일 수정
- runner가 관리하는 실행 기록 파일 직접 수정
- task index 직접 수정

### Stop

Codex가 멈추려 할 때 필수 산출물이 있는지 확인합니다.

예를 들어 phase 전달 메모가 없으면 계속 작업하게 합니다.

## 선택 hook

선택 hook은 기본으로 켜지지 않습니다.

### PostToolUse

도구 실행 뒤에 범위 위반을 다시 확인합니다.

PreToolUse가 놓친 변경을 잡는 데 씁니다.

### UserPromptSubmit

사용자가 `$codex-harness`를 호출할 때 하네스 컨텍스트를 붙입니다.

## 동작 조건

사용자 전역 hooks는 일반 Codex 작업에 끼어들면 안 됩니다.

그래서 하네스 phase 실행 중에만 동작합니다.

```text
CODEX_HARNESS_ACTIVE=1
```

`run-phases.py`는 phase 실행 때 다음 정보를 환경 변수로 넘깁니다.

```text
CODEX_HARNESS_ROOT
CODEX_HARNESS_TASK
CODEX_HARNESS_TASK_PATH
CODEX_HARNESS_PHASE
CODEX_HARNESS_CONTRACT_PATH
```

## hooks가 하지 않는 것

hooks는 모든 문제를 막지 않습니다.

- 모든 도구를 가로채지는 못합니다.
- 모든 의미상 버그를 알 수 없습니다.
- 테스트 성공 여부를 대신 판단하지 않습니다.
- phase 완료 상태를 직접 결정하지 않습니다.

hooks는 빠른 차단 장치입니다.

최종 판정은 다음 파일을 봅니다.

```text
phase<N>-gate.json
phase<N>-result.json
```
