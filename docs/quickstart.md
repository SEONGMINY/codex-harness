# 빠른 시작

이 문서는 설치와 첫 실행만 다룹니다.

실행 모델은 [model.md](./model.md)를 먼저 읽으면 좋습니다.

## 설치

대상 프로젝트 루트에서 실행합니다.

```bash
python3 /path/to/codex-harness/scripts/install-codex-harness.py . --all --force
```

이 저장소를 `/Users/leesm/work/side/harness`에 두었다면:

```bash
python3 /Users/leesm/work/side/harness/scripts/install-codex-harness.py . --all --force
```

설치 후 생기는 것:

- `~/.codex/skills/codex-harness`
- `~/.codex/hooks/codex-harness`
- `.codex/harness/scripts`
- `.codex/harness/sessions`
- `codex-harness.json`

## hooks 포함 설치

프로젝트 안에도 hook 설정을 남기려면 `--with-hooks`를 붙입니다.

```bash
python3 /path/to/codex-harness/scripts/install-codex-harness.py . --all --force --with-hooks
```

선택 hook까지 설치하려면 `--optional-hooks`도 붙입니다.

```bash
python3 /path/to/codex-harness/scripts/install-codex-harness.py . --all --force --with-hooks --optional-hooks
```

hooks는 하네스 phase 실행 중에만 의미가 있습니다.
일반 Codex 작업에는 끼어들지 않도록 `CODEX_HARNESS_ACTIVE=1`일 때만 검사합니다.

## 첫 실행

Codex 대화에서 호출합니다.

```text
$codex-harness

list-tasks.py를 만들어줘.

요구사항:
- tasks/index.json을 읽는다.
- task id, 이름, 상태를 출력한다.
- --status 옵션으로 상태를 필터링할 수 있다.

완료 조건:
- python3 list-tasks.py --status pending 이 동작한다.
- 테스트 또는 실행 예시가 남아 있어야 한다.
```

처음부터 구현하지 않습니다.

launcher가 요청을 파일로 저장하고, 별도 하네스 세션을 실행합니다.

```text
.codex/harness/sessions/<run-id>/
```

첫 실행에서는 다음 중 하나가 먼저 나올 수 있습니다.

- 확인 질문
- 문서 생성 승인 요청
- task 경로
- 다음 실행 명령

세션 상태는 다음 파일에서 확인합니다.

```bash
cat .codex/harness/sessions/<run-id>/launcher-result.json
cat .codex/harness/sessions/<run-id>/last-message.md
```

`launcher-result.json`의 `documents` 배열에는 다음에 사용자가 확인해야 하는 문서 본문이 들어갑니다.
메인 세션은 이 값을 그대로 보여주면 되고, 사용자가 파일을 직접 열어야만 내용을 알 수 있게 만들지 않습니다.

`questions.md`가 있으면 답을 추가합니다.
`docs-approval-request.md`가 있으면 승인한 뒤 다시 실행합니다.
`implementation-design-review.md`가 있으면 설계를 검토하고 승인한 뒤 다시 실행합니다.
task 경로도 위 파일에서 확인합니다.

## 명령으로 직접 시작

직접 실행할 수도 있습니다.

```bash
python3 .codex/harness/scripts/start.py --request-file - --full-auto <<'EOF'
list-tasks.py를 만들어줘.
EOF
```

문서 생성이 이미 승인된 상태로 시작하려면:

```bash
python3 .codex/harness/scripts/start.py --request-file - --docs-approved --full-auto <<'EOF'
list-tasks.py를 만들어줘.
EOF
```

이 단계는 구현 설계 리뷰를 만들고 `design_approval_needed`에서 멈춥니다.
구현 설계가 승인된 뒤에는 `--design-approved`를 함께 넘깁니다.
이때 하네스는 `tasks/<task-dir>/context-pack/static/design-approval.json`을 만들고, 승인된 설계 리뷰 문서의 SHA-256 해시를 기록해야 합니다.

```bash
python3 .codex/harness/scripts/start.py --request-file - --docs-approved --design-approved --full-auto <<'EOF'
list-tasks.py를 만들어줘.
EOF
```

phase 실행까지 요청하려면:

```bash
python3 .codex/harness/scripts/start.py --request-file - --docs-approved --design-approved --run-phases --full-auto <<'EOF'
list-tasks.py를 만들어줘.
EOF
```

이 경우 Codex orchestration 세션은 `planned` 상태까지만 만듭니다.
`start.py`가 `planned` 결과를 받은 뒤 `.codex/harness/scripts/run-phases.py`를 직접 실행합니다.

## task 검증

task가 만들어진 뒤에는 먼저 검증합니다.

```bash
python3 .codex/harness/scripts/verify-task.py <task-dir> --require-design-approval
python3 .codex/harness/scripts/run-phases.py <task-dir> --dry-run
python3 .codex/harness/scripts/review-phase-plan.py <task-dir>
```

## phase 실행

대기 중인 phase를 실행합니다.

```bash
python3 .codex/harness/scripts/run-phases.py <task-dir> --full-auto
```

모든 phase가 끝난 뒤 평가까지 실행하려면:

```bash
python3 .codex/harness/scripts/run-phases.py <task-dir> --full-auto --evaluate
```

특정 phase부터 다시 실행하려면:

```bash
python3 .codex/harness/scripts/run-phases.py <task-dir> --from 1 --full-auto
```

가장 이른 repair packet 또는 실패 phase부터 재개하려면:

```bash
python3 .codex/harness/scripts/run-phases.py <task-dir> --resume-repair --full-auto
```

## 평가

새 컨텍스트에서 평가합니다.

```bash
python3 .codex/harness/scripts/evaluate-task.py <task-dir> \
  --command "npm test" \
  --full-auto
```

평가 실행 기록까지 확인합니다.

```bash
python3 .codex/harness/scripts/verify-task.py <task-dir> --require-evaluation
```

`run-phases.py --evaluate`는 평가가 `rejected`를 반환하면 개선 세션을 실행하고 다시 평가합니다.
이 과정은 평가가 `approved`가 되거나 `--review-iterations` 한도에 도달할 때까지 반복됩니다.
