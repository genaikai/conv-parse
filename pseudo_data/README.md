# 입력 포맷 예시

`conv-data.json` 은 **파서가 읽는 그대로의 모양**이다. 계약(`src/ragdiag/contracts.py`)의
모든 필드가 한 번씩 등장하고, 한 필드가 여러 모양으로 오는 경우는 턴마다 다른 모양을
써 두었다.

```
$ PYTHONPATH=src python -m ragdiag --conv-data pseudo_data/conv-data.json --dry-run
input     : 2 users / 2 conversations / 5 turns
contract  : 31 ok
  · turn.llm_eval_score_top1     : 로그에 이 키가 하나도 없다 (안 쓰는 필드)
metrics   : selected 3 turns
            chunks 중앙 2개 / 174자 · 최대 4개 / 301자
```

마지막 두 줄이 **LLM 을 켜지 않고** 나온다. 청크 풀은 파싱 시점에 정해지므로, 풀이
얼마나 커졌는지는 판정을 돌리기 전에 알 수 있다.

`llm_eval_score_top1` 줄은 열어 둔 질문이다 — 2026-10 컬럼 목록에서 빠졌는데 짝인
`llm_emotion_score_top1` 은 남아 있다. 둘 다 읽는 곳이 없어서 실질 영향은 0이고,
그래서 위반이 아니라 노트로 내려간다.

## 중첩은 3단이다

```
{ "metadata": {...},
  "users": [ { 사용자 필드…,
               "conversations": [ { "conversation_id": "...",
                                    "turns": [ { 턴 필드… } ] } ] } ] }
```

`users[] → turns[]` 처럼 대화 층이 빠진 로그는 계약 검사가 따로 짚어 준다. 최상위
사용자 배열 키는 `users` · `analysis_results` · `data` 셋 다 받는다.

## 케이스 하나는 레코드 하나 + 질문 한 줄이다

```
┌─ turn N  (answered, 비판받은 답변) ────────────┐   ┌─ turn N+1 (불만) ─┐
│                                               │   │                 │
│  ■ 이 턴의 것                                  │   │  user_question  │
│      user_question · llm_response             │   │        │        │
│      retrieved_data · tool_output · memory    │   └────────┼────────┘
│                                               │            │
│  ■ history_input   ← ~N-1 이 **통째로** 여기    │            ↓
│      history_chat                             │      current_query
│      retrieved_data · tool_output · memory    │
└───────────────────────────────────────────────┘

       읽는 레코드는 이 둘뿐이다. 턴 N-1, N-2 … 의 레코드는 안 연다.
```

```
llm_ans_on_last_q  ← llm_response
pre_queries        ← history_input.history_chat 의 role=="user" + user_question
rag_chunks         ← retrieved_data · tool_output
                     history_input.retrieved_data · history_input.tool_output
memory             ← memory + history_input.memory        (코드 대조 전용)
current_query      ← turn N+1 의 user_question
```

이전 턴의 **레코드**를 여는 경우는 `pre_queries` 3단 폴백의 맨 아래 한 칸뿐이다
(아래 참고). `chunk_pool` 에도 같은 모양의 옛 가지가 남아 있지만 `history_input` 이
있으면 안 탄다 — 타면 같은 청크가 두 번 들어간다.

## history_input — 모델에 실제로 들어간 입력

이번 포맷에서 가장 큰 변화다. **직전 턴까지**의 입력을 통째로 들고 있다. 그래서
`turn N` 레코드 하나가 자족적이다 — 과거를 알려고 다른 레코드를 열 필요가 없다.

```json
"history_input": {
  "history_chat": [{"role": "user", "content": "..."},
                   {"role": "assistant", "content": "..."}],
  "memory": "",
  "retrieved_data": "...",
  "tool_output": [{"turn_no": 1,
                   "tool_calls": [{"name": "...", "arguments": "..."}],
                   "outputs": ["...", "..."]}]
}
```

같은 이름의 키가 턴 레벨에도 있고 여기에도 있다. **한 레코드 안의 두 자리**이고,
둘은 겹치지 않는다.

| turn N 안에서 | 문서 | 도구 결과 | 요약 |
|---|---|---|---|
| 이 턴 자신 | `retrieved_data` | `tool_output` *(통문자열)* | `memory` |
| `history_input` | `.retrieved_data` | `.tool_output` *(구조체)* | `.memory` |

겹치지 않으니 청크 풀은 네 칸을 그냥 더하면 된다. 순서는 왼쪽→오른쪽, 위→아래 —
**이 턴 것이 먼저다.** 잘리더라도 비판받은 답변의 문서가 남아야 한다.

파이프라인이 쓰는 방식:

| 안쪽 키 | 쓰임 |
|---|---|
| `history_chat` | `role == "user"` 만 순서대로 → `pre_queries` |
| `retrieved_data` | 청크 풀 |
| `tool_output` | `outputs[]` 만 청크 풀. **`tool_calls` 는 안 쓴다** |
| `memory` | 턴의 `memory` 와 합쳐 `history_quote` 코드 대조 대상 |

`tool_calls` 를 버리는 이유는 둘이다. 무엇을 물었는지는 충족도 대조의 대상이 아니고,
`outputs` 와 인덱스로 짝이 맞는지가 확인되지 않았다 — 짝을 가정해 붙이면 틀린 짝이
근거로 인용된다.

## pre_queries 는 3단 폴백이다

위에서부터 이긴다. 위로 갈수록 사실에 가깝다.

```
1. history_input.history_chat    모델에 실제로 들어간 질문들
2. prev_question                 서비스가 적어 준 앞 질문들
3. 턴 순서 재구성                 우리 추정 (옛 로그 · 골든셋)
```

1·2 는 직전 턴까지라 **비판받은 답변을 부른 질문이 들어 있지 않다.** 파서가 따로
붙인다 — 그게 없으면 무엇에 대한 답인지 자체를 알 수 없다. 그리고 1·2 에는
`run.history_turns` 상한을 걸지 않는다. 상한은 추정이 넓게 틀리는 것을 막으려고 둔
것인데, 이 둘은 챗봇이 실제로 본 것이라 자르면 못 본 턴 대신 본 턴을 지우게 된다.

## 한 필드가 여러 모양으로 온다

실제 로그에서 관측된 변종이고, 파서가 전부 흡수한다. 예시 파일이 이걸 한 번씩 쓴다.

| 필드 | 모양 | 예시 파일의 위치 |
|---|---|---|
| `retrieved_data` | 실제 리스트 | user1 turn 1 |
| | JSON 을 담은 문자열 | user1 turn 2 |
| | `"[]"` — 검색 0건. case21 후보다 | user1 turn 3 |
| | `\n\n` 로 이어 붙인 통문자열 | user2 turn 1 |
| `tool_output` (턴) | 통문자열 · `""` | user1 turn 2 · 나머지 |
| `history_input` | `null` (앞 턴이 없는 첫 턴) | user1·2 turn 1 |
| | dict | 그 외 전부 |
| `history_input.tool_output` | `[]` · 구조체 배열 | user1 turn 2 · turn 3 |
| `carried_turn_nos` | 리스트 · 문자열 `"[1, 2]"` | user1 turn 2 · turn 3 |
| `trace_matched` | `"true"` · `"y"` · `"1"` | user1 turn 1 · 2 · 3 |
| `prev_question` | `null` · str · list | turn 1 · user1 turn 2 · turn 3 |

## 턴 1 은 라벨이 비어 있다

`llm_eval_*` · `llm_emotion_*` 은 **직전 턴과의 관계**를 매긴 값이라 첫 턴에는 없다.
그래서 분석 대상은 2번 턴부터이고, 예시의 5턴 중 3턴이 후보로 잡힌다.

`*_score` 와 `*_alternatives` 의 관계는 이렇다 (`src/ragdiag/labels.py`):

```
*_score       = Σ(확률 × 라벨점수) / Σ확률      확률가중 기대점수
*_score_top1  = argmax 라벨의 점수
```

라벨 이름과 점수는 `query_taxonomy.md` · `emotion_taxonomy.md` 에 있다. 예시의 숫자는
그 표로 실제로 계산한 값이다 — 이름이 표에 없으면 필터가 **에러 없이 0건**을 돌려준다.

## 라우팅 계열 넷은 받아만 둔다

`ask_on` · `answered_by` · `route_intent` · `fallback` 은 파서가 읽지만 판정에 안 쓴다.
어느 플랫폼에서 묻고 어디가 답했는지는 실패의 **원인**이 아니라 실패가 일어난 **자리**다.
값의 모양을 한 사이클 회수한 뒤에 쓸지 정한다. 쓸 자리가 보이는 건 `answered_by` 하나다 —
집계 축이 될 수 있다. `fallback` 은 모델이 스스로 "다른 서비스가 더 잘 답하겠다"고 판단해
그쪽에서 시도했다가 돌아온 것이라, 서비스 자원 부족(case9)과는 무관하다.

## 필드 전체

`src/ragdiag/contracts.py` 에서 뽑았다. 계약이 바뀌면 이 표는 낡는다 — 원본이 그쪽이다.

### `users[]`

| 필드 | 타입 | 필수 | 판정에 쓰나 | 비고 |
|---|---|---|---|---|
| `db_dept_name` | str |  | 씀 | 조직 분류의 소분류와 매칭되는 값 |
| `db_job_name` | str |  | 씀 | 직무. job_grade(직급)와 다른 축이다 |
| `job_grade` | str |  | 씀 | 직급. db_position_name 이 빠진 뒤로 유일한 직급 축이다 |

### `conversations[]`

| 필드 | 타입 | 필수 | 판정에 쓰나 | 비고 |
|---|---|---|---|---|
| `conversation_id` | str | **필수** | 씀 |  |
| `turns` | list | **필수** | 씀 | 시간순. 2턴 이상이어야 분석 대상이다 |

### `turns[]`

| 필드 | 타입 | 필수 | 판정에 쓰나 | 비고 |
|---|---|---|---|---|
| `turn` | int `(1, None)` | **필수** | 씀 | 1부터. 순서가 어긋난 로그를 본 적 있다 |
| `request_time` | str |  | 씀 | 2026-10 에 timestamp 에서 개명. 지연 판정에는 쓸 수 없다 — 턴 시각 차이에 사용자가 생각한 시간이 섞인다 |
| `user_question` | str | **필수** | 씀 |  |
| `llm_response` | str |  | 씀 | 자원 부족 시 서비스가 정해진 안내 문구를 여기 넣는다 (case9) |
| `retrieved_data` | str|list |  | 씀 | 청크가 \n\n 또는 \n 으로 연결된 문자열로 오는 배포가 있다. 파서가 쪼갠다. 비어 있으면 검색 결과 0건이고, 서비스가 '검색 없이 답할 수 있다'고 판단한 경우도 여기 해당한다 (case21). **이 턴의 것이다** — 앞 턴들의 것은 history_input.retrieved_data 로 온다 |
| `tool_output` | str|list |  | 씀 | **이 턴의** 도구 결과이고 통문자열로 온다. 문서 검색 결과와 같은 성격이고 답변 생성에 들어가서 retrieved_data 와 함께 청크 풀로 간다 — 빼고 보면 도구 결과를 제대로 쓴 답변이 case22 로, 그 인용이 case24 로 집계된다. 앞 턴들의 것은 history_input.tool_output 이고 거긴 구조체 배열이다 |
| `history_input` | dict |  | 씀 | 서비스가 이 턴을 답할 때 모델에 **실제로 넣은 입력**. 직전 턴까지다. history_chat[{role, content}] · memory · retrieved_data · tool_output[{turn_no, tool_calls[{name, arguments}], outputs[]}]. history_chat 의 role=='user' 가 pre_queries 를 대신하고 (없으면 prev_question, 그것도 없으면 턴 순서 추정), 안쪽 retrieved_data 와 tool_output 은 청크 풀로 간다. **tool_calls 는 안 쓴다** — outputs 와 인덱스로 짝이 맞는지 확인되지 않았다 |
| `carried_turn_nos` | str|list |  | 씀 | 서비스가 이 턴을 답할 때 실제로 끌고 들어간 앞 턴 번호들 ([1,2]). 자기 턴은 포함하지 않는다. 끌려오는 것은 그 턴들의 질문 · 답변 · tool_output 이다. 비어 있으면 파서가 턴 순서 최근 N개로 떨어진다 |
| `carried_turn_count` | int `(0, None)` |  | 씀 | carried_turn_nos 의 개수. 둘이 어긋나면 로그 쪽 결함이다 |
| `memory` | str |  | 씀 | 서비스가 들고 있던 요약 맥락. **판정 LLM 에는 넘기지 않는다** - 다른 LLM 이 쓴 해석이라 넘기면 우리 관측이 그쪽으로 끌려간다. history_quote 코드 대조 대상에만 더한다 |
| `prev_question` | str|list |  | 씀 | 실행 환경로그에서 list 로 관측됨 (2026-09-01, 16,141건). **pre_queries 의 2순위다** — history_input.history_chat 이 없을 때 쓴다. unused 였던 것을 내렸다: 의지하는 필드가 계약 경고에서 빠지면 안 된다 |
| `trace_matched` | str |  | 씀 | 2026-10 에 bool 에서 str 로. 'true'/'yes'/'y'/'1'/'n' 을 파서가 흡수한다. 2턴 이상 대화라는 뜻이지만 선언값과 실제 턴 수가 어긋난 로그를 본 적 있다 |
| `ask_on` | str |  | 안 씀 | 사용자가 질문한 플랫폼 |
| `answered_by` | str |  | 안 씀 | 실제로 답변한 플랫폼. ask_on 과 다를 수 있다. **집계 축 후보** — 어느 플랫폼이 실패하는지를 가르려면 이게 필요하다 |
| `route_intent` | str |  | 안 씀 | 라우터가 어떤 의도로 라우팅했는지. 값 집합 미확인. '검색 불필요' 가 구분되면 case21 을 결과(retrieved 0건) 가 아니라 의도로 가를 수 있다 |
| `fallback` | str |  | 안 씀 | 모델이 스스로 '다른 서비스가 더 잘 답하겠다'고 판단해 그쪽에서 시도했다가 적절치 않아 ask_on 으로 돌아와 답했는지. **자원 부족(case9)과 무관하다** — 서비스 장애가 아니라 모델의 자체 판단이다. 쓸 자리가 아직 안 보인다 |
| `llm_eval_result` | str |  | 씀 | 직전 턴과의 관계 분류. turn 1 에서는 비어 있다. 실제 라벨 목록은 운영 taxonomy 에 있다 |
| `llm_eval_score` | float `(0, 100)` |  | 씀 |  |
| `llm_eval_score_top1` | float `(0, 100)` |  | 안 씀 | 1순위 라벨의 점수. **읽는 곳이 없다** — 필터는 alternatives 로 새 점수표에 맞춰 다시 계산하고, 없을 때만 llm_eval_score 를 쓴다. 2026-10 컬럼 목록에서 빠졌는데 llm_emotion_score_top1 은 남아 있다 — 둘은 같은 공식의 짝이라 비대칭이 이상하다. 누락인지 확인 필요 |
| `llm_eval_alternatives` | list |  | 씀 | [{label, probability}]. 확률가중 기대점수 계산에 쓴다 |
| `llm_eval_context_summarized` | bool |  | 안 씀 | 라벨을 매길 때 대화 맥락을 요약본으로 넣었는지. 파이프라인은 읽지 않는다 - 라벨 값이 미덥지 않을 때 이 값이 참인 턴을 갈라 보는 용도 |
| `llm_emotion_result` | str |  | 씀 |  |
| `llm_emotion_score` | float `(0, 100)` |  | 씀 |  |
| `llm_emotion_score_top1` | float `(0, 100)` |  | 안 씀 | llm_eval_score_top1 과 같다 — 읽는 곳이 없다 |
| `llm_emotion_alternatives` | list |  | 씀 |  |
| `llm_emotion_context_summarized` | bool |  | 안 씀 | 감정 라벨 쪽의 같은 표시 |
