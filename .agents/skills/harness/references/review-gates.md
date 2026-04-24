# Review Gates

## Product Feature Gate

Use this for customer-facing product features.

Output format:

```markdown
판정: 승인 | 거부
신뢰도: 0-100
핵심 근거: <한 문장>

상세:

* 증거: <판단 결과>
* 가치: <판단 결과>
* 대안: <판단 결과>
* 자동화: <판단 결과>
* 긴급성: <판단 결과>
* 스코프: <판단 결과>

(거부인 경우)
거부 사유 유형:

* insufficient_evidence
* value_unclear
* cheaper_alternative_exists
* requires_human_intervention
* not_urgent
* scope_too_large

개선 가이드: <보강 방법 또는 "재제안 불가">

(승인인 경우)
조건부 조건: <없으면 "없음">
```

Sequential checklist:

1. Evidence
   - Must include at least one concrete source:
     - direct customer quote
     - customer simulation report
     - real customer request log
   - Guesswork, intuition, and "in my experience" fail.
2. Value
   - Must support this sentence:
     - "이 기능이 없으면 [특정 고객]이 [구체 행동]을 하지 않아 [손실]이 발생한다."
3. Alternative cost
   - Must compare:
     - manual operation
     - existing feature
     - external service
     - exposed setting
     - documentation
   - Cheaper equivalent value fails the proposal.
4. Automation
   - CLI + one AI agent must be able to run, operate, and respond to failure.
   - Human intervention requires a non-replaceable reason.
5. Urgency
   - Must be active churn/revenue loss or high likelihood of losing the next customer now.
6. Scope
   - Must fit one MVP ticket and 1-3 days for one person.

## Internal Tooling Gate

Use this for harnesses, scripts, developer workflows, operations automation, and AI-agent tooling.

Output format:

```markdown
판정: 승인 | 거부
신뢰도: 0-100
핵심 근거: <한 문장>

상세:

* 반복성: <판단 결과>
* 실패 비용: <판단 결과>
* 대안: <판단 결과>
* 자동화: <판단 결과>
* 재현성: <판단 결과>
* 스코프: <판단 결과>

(거부인 경우)
거부 사유 유형:

* insufficient_repetition
* failure_cost_too_low
* cheaper_alternative_exists
* requires_human_intervention
* not_reproducible
* scope_too_large

개선 가이드: <보강 방법 또는 "재제안 불가">

(승인인 경우)
조건부 조건: <없으면 "없음">
```

Sequential checklist:

1. Repetition
   - Must address repeated work, repeated mistakes, or repeated context loss.
   - One-off convenience fails.
2. Failure cost
   - Must reduce meaningful time loss, review risk, implementation drift, or operational risk.
3. Alternative cost
   - Must compare:
     - manual checklist
     - existing Codex features
     - simple prompt template
     - existing script
     - documentation only
   - Cheaper equivalent value fails the proposal.
4. Automation
   - CLI + AI agent must run without the main session deciding status.
   - Human intervention requires a non-replaceable reason.
5. Reproducibility
   - Must produce file-based state and logs.
   - Hidden chat state as source of truth fails.
6. Scope
   - MVP must fit one clear tool iteration.
