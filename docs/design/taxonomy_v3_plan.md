# v3 구현 계획

설계는 [taxonomy_v3.md](taxonomy_v3.md). 이 문서는 **순서와 완료 조건**만 적는다.
기준선: 2026-10-24, 테스트 890 통과.

## 원칙

- 한 단계가 끝날 때마다 테스트가 돈다. 깨진 채로 다음 단계를 쌓지 않는다.
- 데이터 계약(`Case` · `TurnResult` · `Candidate` · kev 문항)을 먼저 굳히고, 기능은 그 계약
  위에 독립적으로 만든다. 기능끼리는 `TurnResult` 의 필드로만 만난다.
- 옛 이름(`case20` 등)은 코드에서 지운다. 결과 파일을 읽는 쪽은 `taxonomy.from_v2()` 로 옮긴다.

## 단계

| # | 할 일 | 파일 | 완료 조건 |
|---|---|---|---|
| 1 | 라벨 표 v3 | `taxonomy.py` | `LABELS` · `GROUPS` · `ORDER` · `TAGS` · `from_v2()` · `describe()` 가 묶음 값을 낸다. `tests/test_taxonomy_v3.py` |
| 2 | 데이터 계약 | `schema.py` · `results.py` | `Case` 신규 필드 · `ObservationText` · `Claims` · `Candidate` · `TurnResult` 의 단계 결과 필드 |
| 3 | 결정 백엔드 | `decide.py` (신규) · `judge.py` | `Judge.decide(stage, state, questions)` 가 kev HTTP · LLM 에뮬레이션 · 스텁 셋 중 하나로 돌고 캐시된다. `tests/test_decide.py` |
| 4 | 파싱 | `conv.py` · `settings.py` · `config.py` · `env.example.yaml` | assistant · tool_calls · chunk_sources · prior_turn_nos · 훅. `tests/test_history_input.py` 확장 |
| 5 | 기능 — 코드 | `features/integrity` · `short_circuit`(S2 · S3) · `tool_numbers` | 각 기능 단위 테스트 |
| 6 | 기능 — 판정 | `legibility` · `observe` · `sufficiency` · `claims` · `memory_check` · `consistency` · `quotes` | 스텁 백엔드로 단위 테스트 |
| 7 | 중재 | `features/arbitrate` · `features/__init__.py` | `tests/test_arbitrate.py` 가 후보 조합 전 경로. 옛 `route` · `citation` · `grounding` · `complaint_quote` 삭제 |
| 8 | 출력 | `output.py` · `summary` · `classification` · `__main__.py` | 결과 JSON 에 tags · grade · flags · events · candidates · probabilities. 요약에 무결성 · 이벤트 · kev 호출 |
| 9 | 전달본 · 대시보드 | `features/handover` · `dashboard.py` | 묶음 → 라벨 → 태그. `case9/30/0` 하드코딩 → `I1/I2/N0`. 기존 테스트 갱신 |
| 10 | 테스트셋 | `fixtures/v3_cases.py` · `tests/test_v3_pipeline.py` · `tests/snapshots` | 라벨 · 플래그 · 이벤트 · 태그마다 2건 이상, 전 파이프라인 통과. 스냅숏 재생성 |
| 11 | 문서 | `process_flow.md` · `taxonomy.md` · README | v3 로 |

## 병렬 가능한 묶음

1~4 는 순서대로(계약). 5 · 6 · 7 은 계약이 굳은 뒤 **동시에**. 8 은 7 뒤, 9 는 8 뒤, 10 은
5~9 와 함께 자라되 마지막에 전체를 돌린다.

## 하지 않는 것

- 골든셋(`fixtures/observations.py` 등)의 **내용**은 안 바꾼다. 채점 코드만 v3 필드에 맞춘다.
- 대시보드의 화면 구성은 안 바꾼다. 라벨 값과 축만 바꾼다.
- 실제 kev 서버 성능 측정은 사내에서. 여기서는 계약과 배관만.
