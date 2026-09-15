# 판정을 기능 등록부로 — 설계

지금은 판정 순서가 `classify.classify_turn()` 안에 코드로 박혀 있고, 코드 검증기
12종은 `checks.py` 한 파일(771줄)에 있다. `features/` 는 판정이 끝난 뒤 지표만 내는
자리였다.

이것을 **모든 기능을 `features/` 에 두고 `FEATURES` 순서대로 실행하는** 구조로 바꾼다.
판정 단계도, 검증기도, 진리표도, 집계도 전부 기능이다.

구현 계획: [features_pipeline_plan.md](features_pipeline_plan.md)

## 결정

1. **계약은 하나다** — `process_data(ctx) -> (metrics, notes)`. 지금 계약 그대로다.
   모양이 둘이면 새 기능을 만드는 사람이 먼저 어느 쪽인지 정해야 한다.
2. **`FEATURES` 순서가 곧 실행 순서다.** 판정 순서가 적힌 곳은 거기뿐이다.
3. **`ctx` 는 실행 전체가 공유한다.** 판정 기능은 `ctx.turns` 의 턴마다 결과를 쓰고,
   뒤 기능이 그걸 읽는다 (observe 의 관측을 sufficiency 가 읽는 식).
4. **기능 하나가 전체 턴을 처리하고 다음 기능으로 넘어간다.** LLM 기능은 안에서
   `workers` 만큼 병렬로 돈다.
5. **case 가 정해졌거나 실패한 턴은 뒤 기능이 건너뛴다** (`ctx.open_turns()`).
6. **진리표는 `route` 한 기능에 둔다.** 증거 강도 순서가 이 설계의 핵심이고, 흩으면
   예전의 순서 결함(약한 증거가 강한 증거를 가로챈 것)이 다시 생긴다.
7. **LLM 전에 case 를 확정하는 규칙은 `short_circuit` 안의 규칙들이다.** 규칙 하나가
   파일 하나고, 규칙끼리의 순서는 `short_circuit.RULES` 다.
8. **인용 강등 규칙은 한 곳에 둔다** (`verify.final_verdict`). 근거 활용을 물을지
   정하는 쪽(grounding)과 case 를 정하는 쪽(route)이 같은 규칙을 봐야 한다.

## FEATURES

| # | 기능 | 종류 | 도는 턴 | 쓰는 것 |
|---|---|---|---|---|
| 1 | `short_circuit` | 코드 | 열린 턴 | `checks[규칙]`, 걸리면 `classification` (턴이 닫힌다) |
| 2 | `observe` | LLM · Step 1 | 열린 턴 | `observation` |
| 3 | `complaint_quote` | 코드 | `complaint_target == "none"` | `complaint` |
| 4–14 | `pii` `truncated` `quoted_spans` `python_syntax` `sql_shape` `arithmetic` `dates` `injection` `language` `format` `length` | 코드 | 열린 턴 | `checks[이름]` |
| 15 | `sufficiency` | LLM · Step 2 | 도메인 + 내용 불만 | `judgment` (청크 0개면 LLM 없이 insufficient) |
| 16 | `citation` | 코드 | `judgment` 가 있는 턴 | `citation` |
| 17 | `grounding` | LLM · Step 3 | `final_verdict == "sufficient"` | `grounding` |
| 18 | `route` | 코드 | 열린 턴 | `classification` |
| 19–22 | `classification` `llm_fallback` `filter_fp` `failures` | 집계 | — | 지표 · 노트 |

4–14 는 `features.CHECKS` 로 묶어 두고 `FEATURES` 에 풀어 넣는다. 검증기를 한눈에
보려는 테스트와 문서가 그 목록을 쓴다.

## 공유 상태

```python
@dataclass
class RunContext:
    selection: Any = None        # 고른 턴들. 턴 목록만 받았으면 None
    turns: list = ...            # 턴마다 TurnResult 하나. 판정 기능이 채운다
    judge: Any = None            # LLM 호출 + 캐시
    workers: int = 1
    backend: Any = None

    def open_turns(self): ...    # classification 도 error 도 없는 턴
```

턴 상태는 지금의 `TurnResult` 를 그대로 쓴다 — case · observation · checks · judgment ·
citation · grounding · complaint · classification · error · usage · n_calls.

## short_circuit 의 규칙

```python
# features/short_circuit/<규칙>.py
NAME = "service_error"       # 결과가 checks[NAME] 으로 남는다
CASE = "case9"               # 걸리면 확정할 case
REASON = "서비스 자원 부족 안내 문구"
NOTES = ("…", "…")           # 분류에 함께 실을 주의 사항

def check(turn) -> Check:    # 코드만. observe 보다 앞이라 LLM 결과는 아직 없다
```

- 규칙을 더하려면 `_template.py` 를 복사하고 `RULES` 에 한 줄 더한다.
- 모든 규칙의 결과가 `checks` 에 남는다. 처음 걸린 규칙에서 멈춘다.
- 분류는 `short_circuit.decide(rule, check)` 가 `CASE` · `REASON` · `NOTES` 로 만든다.
  신뢰도는 taxonomy 의 값이다.
- `llm_eval` 라벨 같은 값으로 즉시 판단하려면 그 값을 `Case` 에 필드로 더해야 한다
  (지금은 없다). 그 규칙을 만들 때 같이 한다.

## 공유 코드와 경계

| 기능 밖에 남는 것 | 없어지는 것 |
|---|---|
| `judge.py` · `backends.py` · `prompts.py` · `taxonomy.py` · `settings.py` · `schema.py` | `classify.py` → 판정 기능들 |
| `verify.py` (+ `final_verdict`) | `route.py` → `features/route/` |
| `results.py` (신규: `Check` · `Classification` · `TurnResult`) | `checks.py` → 검증기 폴더 11개 + `features/_text.py` |
| `output.py` · `pipeline.py` | |

`features/` 는 실행 환경으로 가져가는 코어가 된다. `tests/test_boundary.py` 의 CORE 와
README 복사 목록을 함께 바꾼다.

## 달라지는 것

- RUN SUMMARY 의 `truncated` 줄이 `llm_fallback` 으로 바뀐다. 검증기 `truncated`
  (챗봇 답변 잘림 · case8)와 이름이 겹쳐서다. 검증기 이름은 출력 JSON 의 `checks` 에
  실리는 데이터 계약이라 그쪽을 두고 집계 기능 쪽을 바꾼다.
- 실패 표시의 단계 이름이 정확해진다. 지금은 검증기에서 난 예외도 `[observe]` 로
  찍힌다 (`classify.py:117`). 바뀐 뒤에는 그 기능 이름으로 찍힌다.
- 출력의 `evidence.checks` 목록에서 `service_error` 가 맨 앞으로 온다. 가장 먼저 도는
  기능(`short_circuit`)이 남기기 때문이다. 예전에는 `pii` 가 먼저였다 — `run_checks`
  딕셔너리에 적힌 순서였을 뿐 의미는 없었다. 내용은 같다.
- 그 밖에 출력 JSON 과 RUN SUMMARY 는 바뀌지 않는다. `tests/test_snapshot.py` 가 재고
  (checks 는 이름 → verdict 로 접어 순서를 보지 않는다), 같은 입력을 main 과 이 브랜치로
  돌린 출력도 checks 순서를 빼면 같다.

## 이번에 하지 않는 것

- 관측이 필요 없는 검증기 9종을 `observe` 앞으로 옮기기. 순서만 바꾸면 되지만,
  실패한 턴의 출력에도 검증기 결과를 싣도록 출력을 바꿔야 의미가 있다 — 동작이
  바뀌는 변경이라 따로 한다.
- 기능별 지표 (검증기별 위반 수, 단계별 LLM 호출). 판정 기능은 당분간 빈 지표를 낸다.
- 등록부 위치를 `pipeline.py` 로 옮기기. 이 저장소는 `features/__init__.py` 를 등록부로
  쓰고 있고, 옮기는 것은 이번 목적과 무관하다.
