# 대화 로그 실패 분류기

업무 지식 챗봇(RAG)의 대화 로그에서 **사용자가 직전 답변에 불만을 표한 턴**을 찾아,
그 실패가 어떤 유형인지 taxonomy case 로 분류한다.

개별 답변을 고치는 도구가 아니다. **집계했을 때 어디를 고쳐야 하는지** — 문서인지,
검색기인지, 프롬프트인지, 인프라인지 — 를 찾는 도구다.

## 한눈에

```
대화 로그 ─┐                                       ┌─▶ 결과 JSON ─┬─▶ 대시보드      우리가 읽는다
           ├─▶ 턴 고르기 ─▶ 짝짓기 ─▶ 판정 ────────┤              └─▶ 실행 요약
필터      ─┘   필터 조건     불만 턴 N+1 ↔          │
                            그 불만이 겨냥한        └─▶ 전달본 JSON                실무가 읽는다
                            턴 N 의 답변 · 문서
```

| 프로그램 | 무엇을 | 누가 읽나 |
|---|---|---|
| `src/run.py` | 로그를 읽어 턴마다 case 를 붙인다. **LLM 을 부르는 유일한 곳** | — |
| `src/handover.py` | 결과 파일을 TYPE → case → 사례로 다시 담는다 (LLM 호출 없음) | 챗봇을 고칠 실무 |
| `src/dashboard.py` | 같은 결과를 분포 · 부서 · 판정 근거로 훑는다 | 판정을 돌린 우리 |

**설계를 관통하는 세 문장.**

1. **case 는 LLM 이 고르지 않는다** — 좁은 관측만 묻고 조합은 코드 진리표가 한다.
2. **단계마다 입력을 일부러 뺀다** — 더 주면 원인이 아니라 인상을 판정하게 된다.
3. **LLM 이 제안하고 코드가 거부권을 가진다** — 인용 대조 · 요구 확인 · 검증기 10종.

| 문서 | 내용 |
|---|---|
| [docs/process_flow.md](docs/process_flow.md) | 단계별 입력 · 출력, 일부러 안 쓰는 입력과 그 이유 |
| [docs/taxonomy.md](docs/taxonomy.md) | case 전체 목록과 이 로그로 판정 가능한지 여부 |
| [docs/handover.md](docs/handover.md) | 전달본에 무엇을 담고 무엇을 빼나 |
| [docs/design/](docs/design/README.md) | 단계별 개선 기록 — 무엇을 재고 왜 그렇게 정했나 |
| [TODO.md](TODO.md) | 실행 환경에서 돌리기 전에 그쪽에서 만들어야 할 것 |

## 입력

**대화 로그** (`--conv-data`) — 사용자 → 대화 → 턴. 턴 하나가 (질문, 답변) 한 쌍이다.

```
users[]
  job_grade · db_dept_name · db_job_name          사용자 식별자는 로그에 없다
  conversations[]
    chat_id
    turns[]
      turn · event_time · user_question · llm_response
      retrieved_data                        그 질문으로 검색된 청크
      tool_output                           도구 결과. 문서와 같은 성격이고 답변에 들어간다
      carried_turn_nos · carried_turn_count 이 턴을 답할 때 실제로 끌고 간 앞 턴들
      memory                                서비스가 들고 있던 요약 (판정 LLM 엔 안 준다)
      llm_eval_result · llm_eval_score · llm_eval_alternatives              대화 맥락 라벨 A~R
      llm_emotion_result · llm_emotion_score · llm_emotion_alternatives     감정 라벨 A~I
      llm_eval_context_summarized · llm_emotion_context_summarized          맥락을 요약해 라벨을
                                                                            매겼는지 (읽지 않는다)
```

`llm_eval_*` · `llm_emotion_*` 는 앞선 LLM 판정이 직전 턴을 보고 매긴 값이라 첫 턴에는 없다.
**턴을 고르는 데만 쓰고 판정 LLM 에는 넘기지 않는다** — 넘기면 독립적인 두 번째 의견이어야
할 판정이 첫 번째 의견의 확인 도장이 된다.

**필터** (`--filter-data`, 선택) — 어느 턴을 볼지의 조건. 없으면 판정 가능한 후속 턴 전부.

| 키 | 거는 곳 |
|---|---|
| `role` · `org` · `org_tree` | 직급 · 직위 · 부서 · 직무. `"전체"` 나 빈 값은 제한 없음 |
| `turn` | 턴 구간 — `"1-5 턴"`, `"51 턴 이상"` |
| `use_date` · `start_date` · `end_date` | 기간 |
| `eval_range` · `emotion_range` | 점수 구간. alternatives 확률과 `query_scores` 로 **다시 계산한** 값에 건다 |
| `eval_labels` · `emotion_labels` | 라벨. `"I. 매우부정"` 처럼 글자 · 이름 표기를 모두 받는다 |

필터 대신 이미 고른 턴 목록(`chat_id` + `turn`, JSON 배열 또는 JSONL)을 `--turns` 로
줄 수도 있다. 어느 쪽이든 **로그는 자르지 않고 전체를 넣는다** — 판정 대상이 고른 턴의
직전 답변이기 때문이다.

**eval.jsonl 경로** — conv-eval.json 이 너무 클 때. 턴마다 점수 · 라벨 · 조직 · 시각만 있는
가벼운 eval.jsonl 로 **먼저 고르고**, 고른 턴의 본문만 CSV 에서 꺼낸다.

```
eval.jsonl + filter.json ──① assemble.py select (여기)──▶ selected.jsonl   좌표만: chat_id · event_time · target_event_time · n_prior
selected.jsonl + csv     ──② lookup (사내 스크립트)   ──▶ records.jsonl    턴 N · N+1 레코드. 기본 보존
records.jsonl            ──③ run.py --conv-data records.jsonl --turns selected.jsonl ──▶ 결과
```

② 는 저장소 밖이다 — CSV 를 아는 코드는 CSV 가 있는 곳에 둔다. 저장소는 ② 에게 파일 계약
([docs/assemble.md](docs/assemble.md))과 `assemble.py check` 를 준다. filter.json 에 eval 조건
(`eval_range` · `eval_labels`)이 있으면 ① 이 멈춘다 — eval.jsonl 에는 `llm_eval_*` 가 비어 온다.

## 처리 흐름

입력은 파싱 → 턴 고르기 → 짝짓기(불만 턴 N+1 ↔ 턴 N 의 답변 · 근거 · 도구 호출 · memory)를 거쳐
Case 하나가 된다. 그 뒤는 **질문 넷**이다.

```
                    ┌──────────────────────────────────────────────────────────────┐
  Case ───────────▶ │ ⑴ 판정할 답이 있기는 한가?                          코드      │
                    │    자원 부족 문구 · 글자 반복 · 템플릿 토큰 · 인젝션 수행 · 유출 │
                    └──────────────────────────────────────────────────────────────┘
                         │ 없다 ──▶ I1 · I2 · S2 · S3  (등급 4, 모델 호출 0)  ──▶ 끝
                         │ 있다
                         ▼
                    ┌──────────────────────────────────────────────────────────────┐
                    │ ⑵ 사용자가 무엇을 불평했나?                         kev + LLM │
                    │    불만 종류 · 질문 종류 · 거절했나 · 복합질문 · 앞 조건 무시   │
                    │    + 요구(언어 · 길이 · 표) · 못 내는 형태(그림 · 링크)       │
                    └──────────────────────────────────────────────────────────────┘
                         │ 불만 없음 ───▶ N0            거절에 불만 ───▶ S1
                         │ 요구 어김 ───▶ G1 (코드 확인)  못 내는 형태 ─▶ U1 (⑶ 을 덮는다)
                         │ 내용 불만
                         ▼
                    ┌──────────────────────────────────────────────────────────────┐
                    │ ⑶ 근거가 있었나? 모델이 그걸 썼나?                  kev + 코드 │
                    │    청크마다 "요구에 답하나"  ·  답변 주장마다 "근거와 맞나"      │
                    │    + 맥락: 앞 질문의 조건 · memory · 앞 답변과 모순            │
                    └──────────────────────────────────────────────────────────────┘
                         │
                         │              모델이 근거대로 말함      근거와 다르게 말함
                         │   근거 있음   G3 · G4(일부만)          G5
                         │   근거 없음   D1 검색 실패 · T1 도구 안 부름 · T2 엉뚱한 도구
                         │   맥락 어김   G2 (조건 · memory · 모순)
                         │   문서 아님   G6 (계산 · 코드 · 상식)
                         ▼
                    ┌──────────────────────────────────────────────────────────────┐
                    │ ⑷ 제일 확실한 증거의 라벨을 집는다                   코드      │
                    │    등급  4 코드 확정 › 3 근거 대조 › 2 kev 확신 › 1 기울어짐   │
                    │    동급이면 라벨 순서. 후보 없음 → unclassified                │
                    │    나머지 후보는 태그로. 플래그(C1 · C2) · 이벤트(U2) 는 곁에   │
                    └──────────────────────────────────────────────────────────────┘
                         │
                         ▼  주 라벨 · 등급 · 태그 · 플래그 · 이벤트
```

- **⑴ 만 턴을 멈춘다.** ⑵ ⑶ 은 분기 없이 전부 돈 뒤 후보만 내고, ⑷ 가 고른다 (정확성 우선).
  관측 하나가 틀려도 내용 결함이 태그로 남는 이유다.
- **⑶ 의 표가 라벨 묶음을 가른다.** 세로축은 충족도(근거에 답이 있나), 가로축은 주장 검증(답변이
  근거와 맞나). 근거가 없으면 어길 것도 없으니 그 자리는 "왜 없었나"(T1 · T2 · D1)로 쪼개진다.
- **범주 판정은 kev, 문장은 일반 LLM.** kev(`kev.url`)가 없으면 일반 LLM 이 같은 문항에 답하는
  에뮬레이션으로 돈다 — 확률이 보정돼 있지 않아 요약에 그렇게 찍힌다.
- **코드 단계로는** ⑴ = `short_circuit` · `legibility`, ⑵ = `observe` 와 요구 · 조건 대조,
  ⑶ = `sufficiency` · `claims` · `memory_check` · `consistency`, ⑷ = `arbitrate`. 그 앞에 도는
  `integrity`(C1 · C2 · U2) 와 코드 검증기는 ⑴ 에서 닫히는 턴에도 태그가 남게 먼저 도는 장부다.
  순서가 적힌 곳은 `src/ragdiag/features/__init__.py` 의 `JUDGES` 뿐이다.
- **턴 하나가 판정 전부를 끝까지 간다** (`run.mode: turn`, 기본). 끝난 턴부터 10초마다 결과
  파일에 쌓이고, 너무 오래 끄는 턴은 `[단계] 낙오` 로 닫힌다. 판정은 `.cache/` 에 저장돼 재사용된다.

**각 단계가 무엇을 받고 무엇을 일부러 안 받는지**는 [docs/process_flow.md](docs/process_flow.md),
설계와 그 이유는 [docs/design/taxonomy_v3.md](docs/design/taxonomy_v3.md).

## 분류 체계

라벨은 `묶음글자 + 번호` 이고 묶음은 증상이 아니라 **누가 고치는가**다. 같은 묶음 안의 "무엇을
어겼나" 는 라벨이 아니라 **태그**다 (`G1:언어` · `G5:어긋남` …). 라벨이 많으면 셀이 비어 표가
안 읽힌다.

| 묶음 | 고칠 곳 | 라벨 |
|---|---|---|
| N(none) 실패 아님 | 필터 | N0 정상 후속 |
| U(user) 입력 | 질문 유도 · UI | U1 낼 수 없는 형태 요구 · *U2 질문에 개인정보 (이벤트)* |
| C(context) 맥락 기록 | 로그 · 적재 · 맥락 관리 | *C1 앞 턴 누락 · C2 memory 어긋남 (플래그)* |
| T(tool) 도구 호출 | 오케스트레이션 · 도구 연동 | T1 호출 없음 · T2 결과가 질문과 무관 · T3 빈 결과에 단정 |
| D(document) 검색 근거 | 검색기 · 문서 | D1 검색 근거에 답 없음 |
| G(generation) 생성 | 생성 프롬프트 · 모델 | G1 명시 요구 · G2 맥락 · G3 의도와 다름 · G4 복합 일부만 · G5 근거 활용 · G6 일반 지식/계산/코드 |
| S(safety) 정책 · 보안 | 권한 정책 · 입력 방어 · 출력 필터 | S1 정책 거절 · S2 인젝션 수행 · S3 답변 정보 유출 |
| I(infra) 서빙 | 인프라 · 모델 서빙 | I1 자원 부족 문구 · I2 붕괴 · 읽을 수 없음 |

- **플래그**(C) 와 **이벤트**(U2) 는 실패율 분모 밖이다. C1 이 선 턴은 G2 를 판정하지 않는다 —
  맥락을 봤는지 모르는 모델에게 맥락 불이행을 물을 수 없다.
- **신뢰도는 주 라벨의 증거 등급**이다: 4 코드 확정 · 3 근거 확정 → `high`, 2 확신(p ≥ 0.9) →
  `medium`, 1 기울어짐 → `low`, 0 → `unclassified`. 등급 1 · 0 은 표본 검토 대상이다.
- 지연 · 잘림 · 컨텍스트 초과 · 구 문서 · 권한 조회는 로그에 정보가 없어 **이 방법으로 못 보는
  문제**다. 없는 문제가 아니다.

라벨 정의와 태그 전체는 [docs/taxonomy.md](docs/taxonomy.md).

## 출력

`output/<끝난시각>_<로그>_<필터>.json` — 입력과 같은 사용자 → 대화 → 턴 모양이고, 턴마다
짝지은 입력과 판정이 붙는다.

```json
{
  "turn": 2,
  "pre_queries": ["국내 출장 갈 때 식비는 얼마까지 쓸 수 있나요?"],
  "llm_ans_on_last_q": "출장 식비는 회사 규정에 따라 지급되며 …",
  "current_query": "부서별로 다르다는 게 아니라 규정상 …",
  "chunk_data": ["국내 출장 식비는 1일 3만원을 상한으로 한다.", "…"],
  "classification": {
    "case_id": "G5", "case_name": "근거 활용 실패",
    "type_id": "G", "type_name": "생성", "owner": "생성 프롬프트 · 모델",
    "confidence": "high", "grade": 3,
    "reason": "답변의 주장 1건이 근거와 어긋남",
    "tags": ["G5:어긋남", "복합질문"], "secondary_cases": [], "flags": [], "events": [],
    "candidates": [{"label": "G5", "grade": 3, "reason": "…", "tags": ["G5:어긋남"]}],
    "evidence": { "observation": {}, "probabilities": {}, "sufficiency": {}, "claims": [],
                  "memory": {}, "consistency": {}, "quotes": [], "checks": [] },
    "llm_calls": 2, "kev_calls": 9, "answered_turn": 1
  }
}
```

앞 네 칸이 **짝지은 입력**이다 — 이전 질문들 · 비판받은 답변(턴 N) · 불만(턴 N+1) ·
그 답변의 근거. `evidence` 는 판정 근거로, 관측과 문항별 확률 · 충족도(청크마다 p) · 주장별
판정 · memory · 일관성 · 어긋난 인용 · 코드 검증이 들어간다. `case_id` 칸 이름은 옛 결과 파일과
같지만 값은 v3 라벨이다. 집계만 있고 근거가 없으면 "왜 이 라벨이지"에서 막힌다.
판정이 실패한 턴은 `classification.error` 만 남는다 (`[단계] 예외` · `[단계] 낙오` —
낙오는 재실행하면 그 턴만 다시 묻는다).

`output/<끝난시각>_<로그>_<필터>_summary.txt` — 실행 조건, 입력 형식 대조, 지표. 화면 끝에도 같은 것이 찍힌다.

| 지표 | 뜻 |
|---|---|
| `classified` · `llm calls` · `kev calls` | 분류 성공 · 실패 건수, 상위 라벨, 등급 분포, 무결성 · 이벤트 건수, 호출 수 |
| `decision` | 결정 백엔드. `(에뮬레이션)` 이면 kev 없이 일반 LLM 이 범주를 답한 것 |
| `filter FP` | N0(정상) 비율과 몰린 eval 라벨 — 챗봇이 아니라 필터를 좁힐 신호 |
| `llm_fallback` | 판정 LLM 의 응답이 잘려 조건을 바꿔 되살린 호출 — 다음엔 `--thinking off` |
| `failed at` | 실패가 몰린 단계 |

## 실무 전달본

위 결과 파일은 **되짚는 사람**을 위한 것이다. 챗봇을 고칠 사람은 다른 것을 묻는다 —
무엇이 제일 많이 터지나, 그중 하나를 보여 달라, 왜 그렇게 판정했나. 축을
**묶음 → 라벨 → 태그 → 사례**로 바꿔 다시 담고, 무결성 · 이벤트는 별도 표로 낸다.

```bash
./venv/bin/python src/handover.py output/<결과.json>     # → <결과>_handover.json
```

**LLM 을 부르지 않는다** — 문구가 마음에 안 들면 이것만 다시 돌린다. 사례 하나는
`앞_질문들 · 질문 · 답변 · 사용자_반응`(실제로 오간 말)과 `분석`(우리가 본 것) 두 덩이다.
담는 것과 빼는 것은 [docs/handover.md](docs/handover.md).

> **첫 실행에서 `meta_data` 의 `부서` 와 `대화` 칸을 눈으로 본다.** 로그가 다른 필드
> 이름을 쓰면 **에러 없이** 빈 값이 된다. 원본으로 돌아갈 유일한 길이다.

## 실행

```bash
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
export LLM_API_URL=http://<서버>:8000      # OpenAI 호환 서버
export LLM_API_KEY=<키>

./venv/bin/python src/run.py --check-llm        # 서버 · 모델 · 1회 소요시간 점검
./venv/bin/python src/run.py --dry-run          # LLM 없이 턴 고르기까지 (로그가 없으면 합성 데이터)
./venv/bin/python src/run.py --conv-data <로그.json> --filter-data <필터.json>
./venv/bin/python src/handover.py output/<결과.json>   # 실무 전달본 (LLM 호출 없음)
./venv/bin/python -m pytest tests/ -q           # LLM 없이 도는 전부
```

| 옵션 | 뜻 |
|---|---|
| `--turns <목록>` | 필터 대신 고른 턴 목록. `--conv-data` 가 records.jsonl 이면 `assemble.py select` 가 낸 selected.jsonl (필수) |
| `--limit N` · `--workers N` | 앞에서 N건만 · 동시 판정 턴 수 |
| `--no-cache` | `.cache/` 의 판정을 재사용하지 않는다 |
| `--no-progress` | LLM 단계의 진행 표시를 끈다 (기본은 stderr 에 한 줄 — `(실패 N · 포기 M)` 까지) |
| `--output-dir` · `--out` | 결과 위치 (기본 `./output`) |
| `--thinking {auto,on,off}` · `--thinking-param {chat_template_kwargs,reasoning}` | 추론을 끄는 파라미터 이름이 서버마다 다르다 — vLLM · SGLang · llama.cpp 는 앞, OpenRouter 는 뒤. **틀리면 조용히 무시된다** (추론이 켜진 채 토큰을 태우고 잘려서 JSON 이 깨진다) |
| `--golden` · `--golden-set {observations,messy,sufficiency}` · `--observe-only` | 골든셋 채점 — 관측 65 · messy 80(라우팅까지) · 충족도 78 · 근거 활용 50. **실행 환경의 모델로 그대로 돌릴 수 있다** |

설정 우선순위는 **CLI > 설정 파일 > 환경변수 > 기본값**이다. 모든 키는
`configs/env.example.yaml` 에 있고, `--config` 를 안 주면 실행 위치의 `configs/env.yaml` 을 쓴다.

```bash
cp configs/env.example.yaml configs/env.yaml   # 커밋되지 않는다
python src/run.py --config configs/env.yaml --dry-run
```

- 판정 기준(인용 일치율 0.9 · 서비스 오류 확정 문구 · 이전 질문 개수 3)도 설정에서 바꾼다. 플래그가 없는 키는 `--set 키=값` 으로 준다.
- `llm_eval` · `llm_emotion` 의 **라벨 표는 `configs/query_taxonomy.md` · `configs/emotion_taxonomy.md`**
  에 있고 저장소에 함께 다닌다(형식: `A. 이름 -> 점수`). 분류 체계가 바뀌면 이 문서만 고친다.
  다른 점수표로 돌려보려면 `labels.query` · `labels.emotion` 으로 덮어쓴다.
- 실행 환경에서는 `llm.timeout_sec` 를 **120 정도로** 낮추는 것을 권한다. 낙오 기준이 서기 전(절반이
  끝나기 전)에 걸린 턴은 HTTP 타임아웃까지 기다리는데, 기본 600초는 사실상 무한 대기다.
- `run.legibility: false` 면 읽기(④′) 호출이 빠진다 — 코드 규칙(5555… · !!!!…)은 그대로 돈다.
- claude CLI · Anthropic API 로 판정하려면 `tools/dev_run.py` — 인자와 코드 경로가 같다.

## 대시보드

```bash
./venv/bin/pip install -r requirements-dashboard.txt
./venv/bin/python -m streamlit run src/dashboard.py -- --dept-class <체계.json> --job-class <체계.json>
```

`./output` 의 가장 최근 결과를 읽는다. 네 탭 — 분포 · 조직 · 개별 케이스 · 코퍼스 보강.
맨 위는 **판정 건강**(지어낸 인용 · 신뢰도 낮음 · 미분류 · 서비스 오류 · 생성 붕괴 · 정상)
이다. 여기가 나쁘면 아래 집계를 믿을 수 없어서 순서를 그렇게 뒀다. 넘길 표 셋은 CSV 로
내려받는다. 조직 분류 JSON 은 없어도 돈다 — 부서 · 직급이 로그 원본 값으로 나올 뿐이다.

## 구조

```
src/
  run.py              진입점 — 판정
  handover.py         진입점 — 실무 전달본 (결과 파일만 읽는다)
  dashboard.py        대시보드
  ragdiag/
    features/         기능 등록부 — FEATURES 순서가 곧 판정 순서
      short_circuit/                          LLM 전에 case 를 확정하는 규칙들 (service_error · degenerate)
      legibility/                             ④′ 읽을 수 있는 글인가 — LLM, 답변만 본다
      observe/  sufficiency/  grounding/      LLM 판정 — Step 1 · 2 · 3
      complaint_quote/  request_quote/  history_quote/  citation/   판정자의 주장을 원문과 대조
      pii/  language/  format/  arithmetic/ …  코드 검증기 10개
      route/                                  진리표 → case
      classification/  llm_fallback/  filter_fp/  failures/   집계
      handover/                               전달본 — FEATURES 에 없다. handover.py 가 부른다
    conv.py · filters.py · labels.py          로그 파싱 · 짝짓기 · 필터 (여기 전용)
    judge.py · backends.py · prompts.py       LLM 호출 · 캐시 · 프롬프트
    results.py · verify.py · taxonomy.py      턴 판정 결과 · 인용 대조 · case 메타데이터
    requests.py                               요구(형식·언어·길이)가 앞 질문에 있는지 확인
    output.py · pipeline.py · progress.py     출력 JSON · 단계별 함수 · 진행 표시
    textfmt.py                                터미널 표 정렬 (표시 폭)
    __main__.py · config.py · contracts.py · summary.py   실행 · 설정 · 입력 대조 · 요약
    fixtures/         합성 데이터 · 골든셋 다섯 벌(관측 · 라우팅 · 충족도 · 근거 활용 · 읽기) · 공개 규정 청크
tools/                개발 장비 전용 (claude CLI · API 백엔드)
```

기능(판정 단계 · 검증기 · 집계)을 더하려면 `features/template/` 을 복사하고
`features/__init__.py` 의 `JUDGES`(판정) 또는 `REPORTS`(집계) 에 한 줄 더한다. LLM 없이
case 를 바로 확정하는 규칙은 `features/short_circuit/_template.py` 를 복사하고 그 폴더의
`RULES` 에 한 줄.

## 부록: 실행 환경으로 옮기기

실데이터는 별도 실행 환경에 있고, 거기에는 이 저장소를 태그 단위로 복사해 쓴다.
작업 폴더에서 해야 할 일은 [TODO.md](TODO.md).

<!-- BEGIN 실행 환경 순서 -->
```bash
cd 작업 폴더
git clone <remote> .staging/log_analysis             # 최초 1회
bash .staging/log_analysis/scripts/sync.sh <태그>     # 매번 — log_analysis/ 를 통째로 교체
python log_analysis/src/run.py --check-llm
python log_analysis/src/run.py --dry-run
```
<!-- END 실행 환경 순서 -->

로그 파싱과 필터는 실행 환경 쪽 구현을 쓰고, `Case` 부터는 아래 모듈만 가져간다
(`tests/test_boundary.py` 가 실제 import 로 확인한다).

<!-- copy-list -->
```
ragdiag/settings.py   ragdiag/schema.py   ragdiag/taxonomy.py   ragdiag/prompts.py
ragdiag/questions.py  ragdiag/decide.py   ragdiag/backends.py   ragdiag/judge.py
ragdiag/verify.py     ragdiag/output.py   ragdiag/textfmt.py    ragdiag/requests.py
ragdiag/pipeline.py   ragdiag/results.py  ragdiag/progress.py
ragdiag/features/   (폴더 통째)
```
<!-- /copy-list -->
