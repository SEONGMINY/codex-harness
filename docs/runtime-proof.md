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
phase<N>-prompt-attempt<M>.md
phase<N>-contract-attempt<M>.json
phase<N>-checklist-attempt<M>.md
phase<N>-output-attempt<M>.jsonl
phase<N>-stderr-attempt<M>.txt
phase<N>-ac-attempt<M>.json
phase<N>-evidence-attempt<M>.json
phase<N>-reconciliation-attempt<M>.json
phase<N>-reconciliation-attempt<M>.md
phase<N>-gate-attempt<M>.json
phase<N>-quality-attempt<M>.json
phase<N>-handoff-attempt<M>.md
phase<N>-result-attempt<M>.json
phase<N>-evidence.json
phase<N>-reconciliation.json
phase<N>-reconciliation.md
phase<N>-gate.json
phase<N>-quality.json
phase<N>-obligation-closure-attempt<M>.json
phase<N>-baseline.json
phase<N>-result.json
phase<N>-attempt<M>-commit.json
```

호환성과 사람이 보기 쉬운 latest view를 위해 다음 phase-scoped alias도 유지됩니다.

```text
phase<N>-prompt.md
phase<N>-contract.json
phase<N>-checklist.md
phase<N>-evidence.json
phase<N>-reconciliation.json
phase<N>-reconciliation.md
phase<N>-gate.json
phase<N>-quality.json
phase<N>-attempt-manifest.jsonl
phase<N>-result.json
```

무결성 기준은 attempt-scoped 파일입니다. `phase<N>-attempt<M>-commit.json`은
해당 attempt의 prompt, contract, checklist, handoff, evidence, gate, quality, reconciliation, result와 실행 산출물 hash를 고정합니다.
phase-scoped alias는 최신 attempt를 보기 위한 편의 파일이며 commit proof의 기준으로 쓰지 않습니다.
`phase<N>-attempt-manifest.jsonl`은 attempt lifecycle ledger입니다. attempt start, failed terminal state, interrupted terminal state, committed terminal state를 구조화해 남기지만, 완료 판정은 여전히 `phase<N>-result-attempt<M>.json`과 `phase<N>-attempt<M>-commit.json`의 hash 검증을 기준으로 합니다.

실패하거나 다시 시도하면 다음 파일도 생깁니다.

```text
phase<N>-last-error.md
phase<N>-repair-packet-attempt<M>.json
phase<N>-repair-packet-attempt<M>.md
phase<N>-repair-packet.json
phase<N>-repair-packet.md
```

repair packet의 attempt-scoped 파일은 실패 attempt의 canonical snapshot입니다.
phase-scoped repair packet은 최신 실패를 다음 prompt에 넣기 위한 alias입니다.

긴 실행 중에는 진행 기록도 남깁니다.

```text
progress.md
```

이 파일은 현재 phase, attempt, gate 실패, 완료 같은 runner 이벤트를 사람이 확인하기 위한 로그입니다.
기계가 재현 가능한 attempt lifecycle은 `phase<N>-attempt-manifest.jsonl`을 기준으로 봅니다.

planned 또는 generated 상태에서는 task artifact 관계를 확인하는 파생 출력도 생성됩니다.

```text
relationship-graph.json
relationship-graph.mmd
relationship-graph-warning.json  # 생성 실패 시
```

relationship graph는 읽기 전용 보조 출력입니다.
생성 실패는 초기에는 non-blocking warning이며, 완료 판정은 계속 phase result, gate, evidence, verify 결과를 기준으로 합니다.

## 프롬프트

`phase<N>-prompt-attempt<M>.md`는 해당 attempt에서 Codex에게 실제로 전달된 프롬프트입니다.
`phase<N>-prompt.md`는 최신 attempt 프롬프트의 alias입니다.

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

`phase<N>-contract-attempt<M>.json`은 해당 attempt 실행 직전에 확정된 phase contract입니다.
`phase<N>-contract.json`은 최신 attempt contract의 alias입니다.

Codex가 phase 파일 안의 contract를 바꾸면 runner는 변조로 보고 실패시킵니다.

## 확인 명령 결과

`phase<N>-ac-attempt<M>.json`은 확인 명령 실행 결과입니다.

runner는 이 결과를 gate 판정에 씁니다.

## evidence

`phase<N>-evidence-attempt<M>.json`은 관찰된 실행 증거입니다.
`phase<N>-evidence.json`은 최신 attempt evidence의 alias입니다.

주요 내용:

- 변경된 파일
- 명령 실행 결과
- 필수 산출물 존재 여부
- 구현 산출물(`required_repo_outputs`) 존재 여부

## gate

`phase<N>-gate-attempt<M>.json`은 통과/실패 판정입니다.
`phase<N>-gate.json`은 최신 attempt gate의 alias입니다.

기본 gate:

- 확인 명령
- 필수 산출물
- 구현 산출물
- handoff blocked/partial 상태
- handoff 변경 추적(`## Change Trace`)
- 수정 범위
- quality check

하나라도 실패하면 gate는 failed입니다.

## quality

`phase<N>-quality-attempt<M>.json`은 phase 종료 직전 실행한 quality check 결과입니다.
`phase<N>-quality.json`은 최신 attempt quality 결과의 alias입니다.
실행 가능한 기존 프로젝트 lint나 formatter가 있으면 먼저 사용하며, 기본 level은 warning입니다.
실행 가능한 프로젝트 lint가 없으면 하네스 baseline 검사를 phase changed files 기준으로 block합니다.
`CODEX_HARNESS_PROJECT_LINT_LEVEL=block`을 설정하면 프로젝트 lint 실패도 gate 실패가 됩니다.
이 파일은 runner가 만들며, block level 실패가 있으면 gate의 `quality` check가 실패합니다.
child process env는 문서화된 하네스 컨텍스트 키만 전달합니다.
임의 `CODEX_HARNESS_*` 변수와 self-service env allowlist는 기본적으로 전달하지 않습니다.

## reconciliation

`phase<N>-reconciliation-attempt<M>.json`은 contract 지시사항과 실행 증거를 대조한 결과입니다.
`phase<N>-reconciliation-attempt<M>.md`는 같은 내용을 사람이 읽기 쉽게 요약한 파일입니다.
`phase<N>-reconciliation.json`과 `phase<N>-reconciliation.md`는 최신 attempt reconciliation의 alias입니다.

상태:

- `satisfied`
- `blocked`

완료된 phase의 instruction result는 모두 `satisfied`여야 합니다.
`instructions[*].expected_evidence`가 관찰된 command, required output, required repo output, changed file 중 어디에도 매칭되지 않으면 gate의 `expected_evidence` check가 실패하고 phase는 완료되지 않습니다.
이 검사는 LLM handoff 설명이 아니라 runner가 수집한 구조화 evidence만 사용합니다.

## result

`phase<N>-result-attempt<M>.json`은 완료된 attempt의 최종 기록입니다.
`phase<N>-result.json`은 최신 completed attempt result의 alias입니다.
crash recovery와 verifier는 task index의 completed attempt가 가리키는 attempt-scoped result를 우선합니다.

이 파일은 runner가 씁니다.
phase를 실행하는 Codex가 직접 쓰면 안 됩니다.

필수 정보:

- phase
- schema version
- runner version
- status
- 시도 번호
- Codex 종료 코드
- 변경된 파일
- 실행한 명령
- 필수 산출물
- 구현 산출물
- 산출물 경로

`commands_run[*]`에는 command/id/role/exit code와 함께 디버깅용 `output_tail`이 기록될 수 있습니다.
출력이 잘리면 `output_truncated: true`가 기록되며, 이 경우 obligation closure의 `closure_output_assertions` 증거로 인정하지 않습니다.
로그는 진단 자료이고, 잘린 로그는 완료 proof가 아닙니다.

`phase<N>-obligation-closure-attempt<M>.json`이 있으면 runner가 command 실행 직후 full output을 메모리에서 평가한 결과입니다.
이 artifact는 raw matcher value나 full output을 저장하지 않고 obligation id, assertion hash, command ref, pass/fail, attempt, runner version, contract hash, command output hash만 남깁니다.
`phase<N>-result-attempt<M>.json`은 이 artifact를 `artifacts.obligation_closure`로 참조하고, attempt commit marker는 해당 artifact의 sha256을 봉인합니다.
검증자는 이 구조화 ledger를 우선 사용하고, 오래된 result에 이 artifact가 없을 때만 `output_tail` compatibility path를 사용합니다.

## attempt commit

`phase<N>-attempt<M>-commit.json`은 완료된 attempt bundle의 commit marker입니다.

완료 판정의 commit point는 이 marker입니다.
`index.json`의 phase status는 scheduling과 UI를 위한 projection이며, 완료 증거의 source of truth는 marker와 marker가 가리키는 result/artifact hash입니다.

`phase<N>-baseline.json`은 phase 첫 attempt 전의 worktree snapshot과 `required_repo_outputs` 상태를 저장합니다.
재시도 attempt가 실패한 attempt의 변경 위에서 실행되더라도 최종 `changed_files`와 repo content attestation은 이 phase-level baseline 대비로 계산합니다.
attempt별 현재 worktree를 baseline으로 쓰지 않습니다.

marker는 다음을 기록합니다.

- schema version
- runner version
- phase와 attempt
- reset generation
- committed status와 committed_at
- 적용된 policy pack metadata
- design approval scope SHA-256
- runtime proof profile의 harness attestation digest
- `phase<N>-result-attempt<M>.json` 경로와 sha256
- result가 참조하는 runtime proof artifact들의 경로, 존재 여부, sha256. runner는 `context-pack/handoffs/phase<N>.md`를 `phase<N>-handoff-attempt<M>.md`로 snapshot한 뒤 commit marker에 봉인합니다.
- phase result의 `changed_files`에 대한 before/after digest와 canonical digest
- `required_repo_outputs`의 before/after 존재 상태와 file sha256

repo content attestation은 completed marker가 단순히 runtime JSON 묶음만 가리키지 않고, phase 성공 시점의 핵심 repository output bytes도 함께 봉인하도록 하기 위한 것입니다.
다만 이 값은 historical proof입니다.
이후 phase가 같은 파일을 합법적으로 다시 수정할 수 있으므로, verify는 marker와 result의 내부 정합성과 digest를 검증하고 현재 worktree가 과거 after sha와 항상 같은지는 전역 불변식으로 강제하지 않습니다.

harness attestation도 historical proof입니다.
runner는 시작 시점에 runtime-proof profile의 하네스 파일 fingerprint를 한 번 측정하고, phase result, AC results, attempt commit에 같은 값을 기록합니다.
verify는 attestation 자체의 digest 정합성과 같은 attempt artifact 간 일관성을 검증합니다.
일반 verify는 하네스 업그레이드 후 과거 proof를 무조건 실패시키지 않기 위해 현재 runner version 또는 현재 파일 fingerprint와 과거 proof의 exact match를 전역 불변식으로 강제하지 않습니다.
CI나 fresh-run 검증에서 현재 설치된 하네스와 exact match가 필요하면 `verify-task.py --strict-current-harness`를 사용합니다.
Generate 경로까지 같은 기준을 적용하려면 `run-phases.py --strict-current-harness`를 사용합니다.

policy pack도 historical proof와 current execution gate를 분리합니다.
`design-approval.json` schema v3는 승인된 policy pack fingerprint lineage와 `design_approval_scope_sha256`을 봉인합니다.
일반 verify는 completed phase의 result, AC results, attempt commit에 기록된 policy pack이 승인 lineage 안에 있는지 확인합니다.
lineage entry는 `active`, `historical`, `revoked` 상태를 가질 수 있습니다.
`revoked` entry는 `revocation_reason`이 필요하고 historical proof에서도 허용되지 않으며, status와 revocation metadata는 `design_approval_scope_sha256`에 포함됩니다.
lineage parsing, allowed fingerprint 계산, current active policy gate, approval scope hash 계산은 `scripts/harness/policy_lineage.py`가 단일로 소유합니다.
launcher, runner, evaluator, verifier는 이 모듈을 import해서 같은 의미 모델을 사용해야 하며, 각 entrypoint가 별도 lineage parser나 scope hash 계산식을 가지면 안 됩니다.
`CODEX_HARNESS_POLICY_PACK` 환경변수는 그 자체로 policy 선택 권한이 아닙니다.
런타임 override는 target root의 `codex-harness.json`에 있는 `policy_pack_env_override.allow_env_override: true`, `CODEX_HARNESS_ALLOW_POLICY_PACK_OVERRIDE=1`, 설치된 harness `policy-packs/` 하위 경로 조건을 모두 만족해야 합니다.
policy selection은 CLI `--root`가 확정된 뒤 freeze되며, `--help` 같은 argparse-only 경로에서는 policy file을 읽지 않습니다.
custom policy pack은 default security pack 위에 overlay로 적용됩니다. 기본 command/env/redaction guard는 union으로 유지되므로 custom pack이 기본 금지 명령, 민감 경로, secret redaction pattern을 제거할 수 없습니다.
custom overlay의 policy fingerprint는 원본 파일 hash가 아니라 합성된 effective policy hash이며, metadata에는 원본 `source_sha256`과 baseline `baseline_sha256`도 보존됩니다.
`run-phases.py`는 새 attempt를 시작하기 전에 현재 runner가 사용할 policy pack이 `active_policy_pack`과 같은지 확인합니다.
`--strict-current-harness`는 이 조건에 더해 현재 설치된 policy pack과 runtime proof의 exact match를 요구합니다.

검증자는 marker가 없거나 hash가 맞지 않으면 해당 completed phase를 신뢰하지 않습니다.
`phase<N>-result.json`만 있고 commit marker가 없으면 partial commit으로 봅니다.
`index.json`이 completed인데 marker가 없으면 projection corruption으로 보고 verify가 실패해야 합니다.

reset은 timestamp만으로 구분하지 않습니다.
`phase<N>-reset-marker.json`은 `reset_generation`을 증가시키고, 이후 생성되는 phase result와 attempt commit은 같은 `reset_generation`을 기록합니다.
검증자는 현재 reset marker와 generation이 다른 commit을 이전 실행의 증거로 보고 무시합니다.
generation이 없는 오래된 marker/commit은 backward compatibility를 위해 `reset_at`을 사용하지만, 같은 초에 reset된 legacy commit도 무효로 처리합니다.
multi-phase reset은 marker를 index projection보다 먼저 씁니다.
reset 도중 runner가 중단되어 일부 phase marker만 남아도, `from_phase` 이후 phase는 그 marker를 reset boundary로 사용해 old commit을 current projection으로 복구하지 않습니다.

runner 시작 시에는 runtime proof와 `index.json` projection을 조정합니다.

- valid commit marker가 있고 `index.json`이 pending/running이면 completed projection으로 복구합니다.
- `index.json`이 completed인데 valid commit marker가 없으면 error projection으로 바꿉니다.
- `index.json`이 running인데 valid commit marker가 없으면 이전 runner가 attempt 중간에 멈춘 것으로 보고 error projection으로 바꿉니다.
- `index.json`이 pending이어도 current reset generation에 terminal record 없는 `attempt_started`가 있으면 같은 attempt를 재사용하지 않고 error projection으로 바꿉니다.

이 복구는 marker를 source of truth로 삼기 위한 최소 reconciliation입니다.
pending/running attempt가 terminal manifest record 없이 중단된 경우 runner는 같은 attempt를 실패로 관측했다고 주장하지 않습니다.
대신 `attempt_interrupted` terminal record와 repair packet을 쓰고 phase projection만 `error`로 바꿉니다.
이 상태에서는 자동으로 다음 attempt를 시작하지 않고, 사람이 repair packet을 확인한 뒤 `--resume-repair` 또는 `--from <N>`으로 재개해야 합니다.
장기적으로는 `index.json`을 runtime ledger에서 재생성 가능한 projection으로 낮추는 방향이 더 안전합니다.

## repair packet

gate나 명령이 실패하면 runner는 repair packet을 씁니다.

```text
phase<N>-repair-packet-attempt<M>.json
phase<N>-repair-packet-attempt<M>.md
phase<N>-repair-packet.json
phase<N>-repair-packet.md
```

다음 시도는 이 packet을 읽고 실패한 항목만 고칩니다.
phase-scoped repair packet은 최신 실패를 가리키는 alias입니다.
attempt-scoped repair packet은 retry가 진행되어도 실패 당시 context를 보존하는 canonical snapshot입니다.

repair packet에는 다음이 들어갑니다.

- 실패 유형
- 실패 메시지
- 재시도 가능 여부
- 실패한 명령
- 빠진 산출물
- 빠진 구현 산출물
- 자동 재시도를 막는 허용 범위 밖 변경(`contaminating_changes`)
- 실패 attempt artifact 경로, 존재 여부, sha256(`failed_attempt_artifacts`)
- 범위 위반
- 다시 확인할 지시사항
- contract 요약

`contaminating_changes`가 비어 있지 않으면 runner는 해당 phase를 자동 재시도하지 않습니다.
작업트리 오염 여부나 contract scope를 사람이 확인한 뒤 `--resume-repair` 또는 `--from <N>`으로 다시 실행해야 합니다.

## evaluation 실행 기록

evaluation은 새 컨텍스트에서 실행됩니다.

필수 실행 기록:

```text
evaluation-command-results.json
evaluation-prompt.md
evaluation-output.jsonl
evaluation-last-message.json
evaluation-stderr.txt
evaluation-commit.json
```

`run-phases.py --evaluate`에서 평가가 `rejected`이면 runner는 `evaluation-repair<N>-*` 실행 기록을 남기고 다시 평가합니다.
평가가 `approved`가 되기 전까지는 완료로 보지 않습니다.

`evaluation-commit.json`은 평가가 참조한 completed phase attempt commit과 evaluation artifact 묶음을 sha256으로 봉인합니다.
`verify-task.py --require-evaluation`은 이 파일을 기준으로 현재 phase proof와 evaluation artifact가 평가 시점의 봉인값과 일치하는지 확인합니다.

`evaluation-command-results.json`은 schema version 1 object입니다.
이 파일은 evaluation command 결과뿐 아니라 evaluation에 적용된 `policy_pack`, `harness_attestation`, `design_approval_scope_sha256`를 기록합니다.
verifier는 v3 design approval이 있는 task에서 evaluation policy pack이 승인 lineage 안에 있는지, approval scope가 일치하는지 확인합니다.
legacy list 형식은 historical default에서만 제한적으로 허용되며, v3 approval scope가 있거나 `--strict-current-harness`를 사용하면 실패합니다.
evaluation prompt에는 command 결과만 포함하고 policy lineage metadata는 verifier가 판단합니다.

평가까지 요구하려면 다음을 실행합니다.

```bash
python3 .codex/harness/scripts/verify-task.py <task-dir> --require-evaluation
```

## 확인 명령

phase 실행 증거를 확인합니다.

```bash
python3 .codex/harness/scripts/verify-task.py <task-dir>
find tasks/<task-dir>/context-pack/runtime -maxdepth 1 -type f | sort
find tasks/<task-dir>/context-pack/handoffs -maxdepth 1 -type f | sort
```
