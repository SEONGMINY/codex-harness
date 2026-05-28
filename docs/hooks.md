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

Stop hook은 phase 시작 시점의 worktree baseline을 알 수 없으므로 quality check를 hard block하지 않습니다.
quality check는 runner gate에서 phase changed files 기준으로 실행합니다.

## quality check

runner는 phase 종료 전에 `phase<N>-quality.json`을 만듭니다.

quality check는 실행 가능한 기존 프로젝트 lint를 먼저 사용합니다.
실행 가능한 프로젝트 lint가 없으면 하네스의 보수적인 changed-file baseline 검사를 block으로 실행합니다.
기존 프로젝트 lint의 기본 level은 warning입니다.
프로젝트 lint를 block으로 승격하려면 `CODEX_HARNESS_PROJECT_LINT_LEVEL=block`을 설정합니다.

기존 프로젝트 lint는 다음을 감지합니다.

- `package.json`의 `format:check` 또는 `lint` script
- `pyproject.toml` 또는 `ruff.toml`이 있는 Python 프로젝트의 `ruff`

fallback baseline은 다음을 막습니다.

- trailing whitespace
- merge conflict marker
- final newline 누락
- 변경된 Python 파일의 syntax error

폴더 구조 스타일은 hook에서 block하지 않습니다.

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

하네스 child process env는 `CODEX_HARNESS_*` prefix 전체를 신뢰하지 않습니다.
문서화된 하네스 컨텍스트 키만 전달하고, 임의 같은-prefix 변수는 버립니다.
정책 pack override 키는 runner가 명시적으로 허용한 경우에만 전달됩니다.

## hooks가 하지 않는 것

hooks는 모든 문제를 막지 않습니다.

- 모든 도구를 가로채지는 못합니다.
- 모든 의미상 버그를 알 수 없습니다.
- 테스트 성공 여부를 대신 판단하지 않습니다.
- 프로젝트에 없는 lint 도구를 설치하지 않습니다.
- 폴더 구조 스타일을 강제하지 않습니다.
- Stop hook은 dirty worktree 전체를 quality 기준으로 막지 않습니다.
- phase 완료 상태를 직접 결정하지 않습니다.

hooks는 빠른 차단 장치입니다.

최종 판정은 다음 파일을 봅니다.

```text
phase<N>-gate.json
phase<N>-result-attempt<M>.json
phase<N>-attempt<M>-commit.json
```
