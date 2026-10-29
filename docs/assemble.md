# eval.jsonl 경로 — 가벼운 파일로 먼저 고르고, 본문은 고른 턴만 꺼낸다

conv-eval.json 은 대화 전부를 담아 너무 크다. 그 앞 단계 파일 eval.jsonl 은 턴마다 점수 ·
라벨 · 조직 · 시각만 있어 가볍다. 그래서 순서를 바꾼다.

```
 eval.jsonl + filter.json ──① select (저장소)──▶ selected.jsonl
 selected.jsonl + csv     ──② lookup (사내)  ──▶ records.jsonl
 records.jsonl + selected ──③ run.py (저장소)──▶ parsed.json
```

```bash
python <저장소>/src/assemble.py select --eval-jsonl eval.jsonl --filter-data filter.json --out selected.jsonl
#  (② 사내 스크립트: selected.jsonl + csv → records.jsonl)
python <저장소>/src/assemble.py check selected.jsonl records.jsonl
python <저장소>/src/run.py --conv-data records.jsonl --turns selected.jsonl --output-dir outputs
```

**② 는 이 저장소 밖에 있다.** CSV 의 열 이름을 아는 코드는 CSV 가 있는 곳에 있어야 하고,
여기서는 실 CSV 가 없어 테스트할 수 없다. 저장소가 ② 에게 주는 것은 아래 **파일 계약 둘**과
`check` 다. 함수 import · 훅 같은 코드 경계는 없다 — ② 는 어떤 언어 · 도구로 짜도 된다.

## ① select 가 하는 것

eval.jsonl 의 행을 본문 없는 대화로 세워 **conv-eval 과 같은 `apply_filter`** 를 건다. 필터를
jsonl 용으로 다시 짜지 않는다 — 두 구현이 어긋나면 티가 안 난다. 단계별 탈락 건수 보고도
그대로 나온다.

| 단계 | 규칙 |
|---|---|
| 후보 | `turn ≥ 2` 이고 같은 `chat_id` 에 `turn − 1` 행이 있다. **eval.jsonl 에는 대화의 모든 턴이 있어야 한다** |
| 조직 · 턴 구간 · 기간 | `job_grade` · `db_dept_name` · `db_job_name` · `turn` · `event_time` 로 지금 필터 그대로 |
| emotion 점수 · 라벨 | `llm_emotion_score` · `llm_emotion_result` (alternatives 재점수 포함) |
| eval 점수 · 라벨 | filter.json 에 `eval_range` · `eval_labels` 가 있으면 **예외로 멈춘다** — eval.jsonl 에는 `llm_eval_*` 가 비어 온다 |

경고로 찍는 것: 같은 chat 안에서 `event_time` 이 겹치는 행 (② 가 행을 못 가른다), `event_time`
이 빈 턴.

## selected.jsonl — ① 이 내고 ② · ③ 이 읽는다

한 줄에 불만 턴 하나. **좌표만 있고 본문은 없다.**

```json
{"chat_id": "C-0002", "event_time": "2026-10-21 14:07:45", "target_event_time": "2026-10-21 14:03:10", "n_prior": 1,
 "llm_emotion_result": "불만", "llm_emotion_score": 88.0, "llm_emotion_score_top1": 88.0, "llm_emotion_alternatives": [...]}
```

| 필드 | 뜻 | 누가 쓰나 |
|---|---|---|
| `chat_id` | 대화 | ② 조회 키 · ③ 묶기 |
| `event_time` | 불만 턴 N+1 의 시각. eval.jsonl 값 **그대로** | ② 가 이 행을 찾는다 · ③ 이 턴 번호를 붙인다 |
| `target_event_time` | 판정 대상 답변 턴 N 의 시각 | ② 가 이 행을 찾는다 |
| `n_prior` | N 앞에 있는 턴 수 | ③ 이 턴 번호를 되살린다 (N = n_prior+1, N+1 = n_prior+2). C1 이 앞 턴 수를 센다 |
| `llm_emotion_*` | 불만 턴의 감정 판정 | ③ 이 결과 파일에 싣는다. **② 는 복사하지 않는다** |

## records.jsonl — ② 가 내고 ③ 이 읽는다

selected.jsonl 한 줄당 **두 줄**. 답변 턴(`target_event_time` 행)은 본문 전부, 불만 턴(`event_time`
행)은 질문만. 값은 CSV 셀을 **그대로** 싣는다 — `history_input` 이 JSON 문자열이면 문자열 그대로.
파싱은 ③ 이 한다.

```json
{"chat_id": "C-0002", "event_time": "2026-10-21 14:03:10",
 "user_question": "…", "llm_response": "…", "retrieved_data": …, "tool_output": …, "tool_calls": …,
 "history_input": {…}, "memory": "…", "prev_question": …, "carried_turn_nos": …,
 "job_grade": "책임", "db_dept_name": "공정기술팀", "db_job_name": "공정 엔지니어"}
{"chat_id": "C-0002", "event_time": "2026-10-21 14:07:45",
 "user_question": "우리 라인 규격을 물었는데요",
 "job_grade": "책임", "db_dept_name": "공정기술팀", "db_job_name": "공정 엔지니어"}
```

| 줄 | 필수 | 있으면 싣는 것 |
|---|---|---|
| 답변 턴 | `chat_id` · `event_time` · `user_question` · `llm_response` · 조직 셋 | `retrieved_data` · `tool_output` · `tool_calls` · `history_input` · `memory` · `prev_question` · `carried_turn_nos` — 턴 레코드 계약(`src/ragdiag/contracts.py` TURN_SCHEMA) 그대로 |
| 불만 턴 | `chat_id` · `event_time` · `user_question` · 조직 셋 | — |
| 앞 턴 (조건부) | `chat_id` · `event_time` · **`turn`** · `user_question` · `llm_response` | 답변 턴의 `history_input.history_chat` 이 **비어 있을 때만**, 답변 턴 바로 앞 최근 3턴 (turn = `n_prior-2 … n_prior`, 있는 만큼). 불만 판정이 앞 대화를 재구성하는 재료다 (`docs/design/decision_tree_v4.md` "history 규칙") |

**② 가 지킬 것**

- `event_time` 을 가공하지 않는다. ③ 은 `(chat_id, event_time)` 문자열 일치로 selected 와 맞춘다.
- `turn` 은 **앞 턴 행에만** 쓴다. 답변 턴 · 불만 턴은 CSV 에 없고 ③ 이 `n_prior` 로 붙인다. 앞 턴
  행의 `turn` 이 `n_prior` 를 넘거나 selected 의 턴과 겹치면 `check` 가 멈춘다.
- 한 좌표에 한 줄. 같은 `(chat_id, event_time)` 이 두 줄이면 `check` 가 멈춘다.
- 못 찾은 행은 빼지 말고 **멈춘다**. 빠진 채로 넘기면 `check` 가 "② 가 못 찾은 행" 으로 잡지만,
  조용히 비워 넘기면 그 턴이 T1(도구 안 부름)로 집계된다.

pandas 라면 이 정도다 — `"…열"` 자리에 실제 열 이름을 넣는 것이 ② 의 일 전부다.

```python
sel = [json.loads(l) for l in open("selected.jsonl")]
df = pd.read_csv("conv.csv", dtype=str).set_index(["chat_id", "event_time"])
with open("records.jsonl", "w") as out:
    for s in sel:
        ans = df.loc[(s["chat_id"], s["target_event_time"])]
        cmp = df.loc[(s["chat_id"], s["event_time"])]
        out.write(json.dumps({"chat_id": s["chat_id"], "event_time": s["target_event_time"],
                              "user_question": ans["질문열"], "llm_response": ans["답변열"],
                              "retrieved_data": ans["검색열"], "tool_output": ans["도구열"],
                              "history_input": ans["히스토리열"], "memory": ans["메모리열"],
                              "job_grade": ans["직급열"], "db_dept_name": ans["부서열"], "db_job_name": ans["직무열"]},
                             ensure_ascii=False) + "\n")
        out.write(json.dumps({"chat_id": s["chat_id"], "event_time": s["event_time"],
                              "user_question": cmp["질문열"],
                              "job_grade": cmp["직급열"], "db_dept_name": cmp["부서열"], "db_job_name": cmp["직무열"]},
                             ensure_ascii=False) + "\n")
```

## ③ check 와 run 이 하는 것

`assemble.py check` 는 두 파일을 conv-eval 모양으로 접어 보고(`records_to_payload`) 어긋난 줄을
문장으로 찍는다. 그 문장이 사내에서 사외로 돌아오는 포맷 정보다.

| 검사 | 멈추는 조건 |
|---|---|
| 좌표 일치 | selected 의 `(chat_id, event_time)` ∪ `(chat_id, target_event_time)` 과 records 의 좌표 집합이 다르다 — "② 가 못 찾은 행 n건" · "② 가 더 넣은 행 n건" |
| 번호 충돌 | 한 좌표에 selected 두 줄이 다른 턴 번호를 준다 (`n_prior` 불일치) |
| 계약 | 턴 레코드가 `contracts.TURN_SCHEMA` 와 다르다 — conv-eval 입력과 같은 문장 |

`run.py --conv-data records.jsonl --turns selected.jsonl` 은 같은 접기를 한 뒤 **지금 파이프라인
그대로** 돈다. 필터는 ① 에서 걸었으니 다시 안 걸고(`--filter-data` 는 못 준다), records 에 없는
앞 턴 `1..n_prior` 는 본문 없는 자리로 채워 C1 이 "앞 턴이 k 개" 를 맞게 센다 (계약 대조에서는
뺀다). 결과 파일 이름의 로그 자리에는 records.jsonl 의 stem 이 들어간다.

records.jsonl 은 **기본 보존**이다. parsed.json 을 다시 만들 수 있는 유일한 입력이고, 오류 턴만
다시 돌릴 때도 필요하다. 지우는 건 사내 절차가 정한다 — 프로그램이 자기 입력을 지우지 않는다.

예시 네 파일은 코드가 만든다 (가짜 데이터는 파일이 아니라 코드다):

```bash
python <저장소>/src/assemble.py example pseudo_data/eval_jsonl
```

`src/ragdiag/fixtures/eval_jsonl.py` 가 원본이고, 테스트가 select 의 출력이 거기 적힌
selected 와 같은지 잰다.
