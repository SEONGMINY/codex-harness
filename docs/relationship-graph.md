# relationship graph

relationship graph는 task artifact 사이의 관계를 읽기 전용으로 보여주는 출력입니다.

이 그래프는 새로운 source of truth가 아닙니다.
하네스의 기준은 여전히 task 문서, decision registry, phase contract, runner proof입니다.
relationship graph는 그 파일들에서 관계를 추출해 사람이 검토하기 쉽게 보여줍니다.

## 배경

LinkedIn 글에서 확인한 핵심은 다음입니다.

- AI가 같은 파일과 맥락을 반복 탐색하는 이유는 대상 사이의 관계가 구조화되지 않았기 때문입니다.
- `codegraph`는 코드의 함수, 클래스, 호출, 상속, import 관계를 그래프로 만들어 탐색 비용을 줄입니다.
- `ActiveGraph`는 장시간 실행되는 에이전트의 task, claim, evidence와 `supports`, `contradicts`, `depends_on` 관계를 그래프로 기록합니다.
- 두 접근의 공통점은 암묵적인 관계를 명시적인 노드와 엣지로 바꾸는 것입니다.

codex-harness는 이미 대화를 상태로 쓰지 않고 승인된 파일과 실행 증거를 상태로 씁니다.
따라서 graph 고도화도 이 원칙을 유지해야 합니다.

```text
대화 기억이 아니라 artifact가 source of truth다.
그래프는 artifact를 대체하지 않고 artifact에서 파생된다.
```

## 자동 생성

relationship graph는 사용자가 별도 옵션을 주지 않아도 기본 흐름에서 생성됩니다.

- `planned` 상태가 유효하게 만들어지면 launcher가 생성합니다.
- `generated` 상태에서 모든 phase가 완료되면 runner가 다시 생성합니다.
- 생성 실패는 초기에는 task 실패가 아니라 non-blocking warning으로 기록합니다.

출력 위치:

```text
tasks/<task-dir>/context-pack/runtime/relationship-graph.json
tasks/<task-dir>/context-pack/runtime/relationship-graph.mmd
tasks/<task-dir>/context-pack/runtime/relationship-graph-warning.json  # 실패 시
```

`relationship-graph-warning.json`은 graph exporter 자체 실패만 의미합니다.
contract, decision registry, runtime proof의 실제 오류 판단은 계속 `verify-task.py`와 runner proof가 담당합니다.

## 수동 생성 명령

JSON:

```bash
python3 scripts/harness/gen-relationship-graph.py tasks/<task-dir> --format json
```

Mermaid:

```bash
python3 scripts/harness/gen-relationship-graph.py tasks/<task-dir> --format mermaid
```

파일로 저장:

```bash
python3 scripts/harness/gen-relationship-graph.py tasks/<task-dir> \
  --format mermaid \
  --output tasks/<task-dir>/context-pack/runtime/relationship-graph.mmd
```

## 포함되는 관계

- task가 읽는 common docs와 task docs
- task가 가진 static context
- design approval이 승인한 design review 문서
- approved decision과 open decision
- architecture node, architecture ref, allowed dependency edge
- phase가 요구하는 decision ref와 architecture ref
- phase가 수정할 수 있는 allowed path
- phase의 required output과 required repo output
- phase의 acceptance command
- phase가 가진 runtime proof와 handoff

## 의도적으로 하지 않는 것

- graph를 runner 상태로 사용하지 않습니다.
- graph 결과만으로 phase를 완료 처리하지 않습니다.
- `ActiveGraph`나 `codegraph`를 dependency로 추가하지 않습니다.
- graph에 없는 관계를 추측해서 만들지 않습니다.
- open decision을 자동으로 해결하지 않습니다.

## 다음 결정이 필요한 고도화

아래는 현재 구현하지 않았습니다.
구현하려면 별도 결정이 필요합니다.

- relationship graph를 `verify-task.py`의 필수 gate로 만들지 여부
- `supports`, `contradicts`, `depends_on` 같은 evidence relation을 decision registry에 추가할지 여부
- `codegraph` MCP 설치를 하네스 설치 흐름에 포함할지 여부
- `ActiveGraph`를 runtime backend로 채택할지 여부

현재 권장 방향은 읽기 전용 graph export까지만 유지하는 것입니다.
이 단계는 기존 패러다임을 바꾸지 않으면서 관계를 명시화하는 효과가 있습니다.

필수 gate 승격은 실제 task 5개 이상에서 false positive 없이 통과한 뒤 다시 결정합니다.
승격하더라도 gate는 graph 생성 가능 여부와 artifact 참조 무결성만 봐야 하며, graph 해석 품질을 source of truth로 삼지 않습니다.
