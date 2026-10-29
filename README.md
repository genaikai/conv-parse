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
| `src/run.py` | 로그를 읽어 턴마다 묶음을 붙인다. **kev 를 부르는 유일한 곳** | — |
| `src/handover.py` | 결과 파일을 묶음 → 들어온 길 → 사례로 다시 담는다 (kev 호출 없음) | 챗봇을 고칠 실무 |
| `src/dashboard.py` | 같은 결과를 분포 · 부서 · 판정 근거로 훑는다 | 판정을 돌린 우리 |

**설계를 관통하는 세 문장.**

1. **묶음은 kev 가 고르지 않는다** — 좁은 문항만 묻고, 코드가 순서대로 읽어 처음 걸리는 묶음을 붙인다.
2. **단계마다 입력을 일부러 뺀다** — 더 주면 원인이 아니라 인상을 판정하게 된다.
3. **모름은 흘리지 않는다** — 확신 없는 문항에서 멈춰 검토로. 막힌 문항이 곧 고칠 곳이다.

| 문서 | 내용 |
|---|---|
| [docs/process_flow.md](docs/process_flow.md) | 단계별 입력 · 출력, 일부러 안 쓰는 입력과 그 이유 |
| [docs/taxonomy.md](docs/taxonomy.md) | 묶음 다섯 · 네 단계의 문항 · 플래그 |
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
Case 하나가 된다. 그 뒤는 **결정 트리**다 — 질문을 순서대로 묻고 처음 걸리는 묶음 하나를 붙인다.

```
Case
 코드 확정       자원 부족 문구 · 빈 답변 · 붕괴                      코드     ─▶ 시스템
 불만 판정       문제 삼지 않음 → 정상 · 거절 불만 · 읽을 수 없음 ·  kev 1요청 ─▶ 정상 · 시스템 · 생성 · 사용자
                 잘림 → 시스템 · 언어 불일치 · 문서 무관 → 생성 ·   8문항
                 감정 표출만 · 새 요구 → 사용자
 근거 판정       네 칸(이번 청크 · 도구 결과 · 앞 턴 근거 · 메모리)   kev 1요청 ─▶ 전부 → 생성 · 없음 → 근거
                 에 답이 있었나. 전체 문항이 정한다                   5문항       일부 → 다음
 불만 부분 근거  불만이 가리키는 부분의 근거가 있었나                 kev 1요청 ─▶ 예 → 생성 · 아니오 → 근거
 어디서든 모름                                                               ─▶ 검토 (멈춘 문항 기록)
```

- **처음 걸리는 데서 멈춘다.** 후보도 등급도 중재도 없다. 결과 한 줄이 "어느 단계 어느 문항에서
  멈췄고 뭐라 답했나" 다.
- **단계마다 입력을 뺀다.** 불만 판정은 문서를, 근거 판정은 답변과 불만을 안 본다 — 주면 원인이
  아니라 인상을 판정한다.
- **모름은 그 자리에서 검토.** `p ≥ 0.9` 예, `p ≤ 0.1` 아니오, 사이는 모름. 다음 문항으로 흘리지 않는다.
- **범주 판정은 전부 kev.** `kev.url` 이 없으면 일반 LLM 이 같은 문항에 답하는 에뮬레이션으로 돈다 —
  확률이 보정돼 있지 않아 요약에 그렇게 찍힌다. 턴당 kev 요청 최대 3, 일반 LLM 0.
- **코드 단계로는** `integrity`(플래그 열) → `code_rules` → `complaint` → `evidence` →
  `complaint_evidence`. 순서가 적힌 곳은 `src/ragdiag/features/__init__.py` 의 `JUDGES` 뿐이다.
- **턴 하나가 판정 전부를 끝까지 간다** (`run.mode: turn`, 기본). 끝난 턴부터 10초마다 결과
  파일에 쌓이고, 너무 오래 끄는 턴은 `[단계] 낙오` 로 닫힌다. 판정은 `.cache/` 에 저장돼 재사용된다.

**각 단계가 무엇을 받고 무엇을 일부러 안 받는지**는 [docs/process_flow.md](docs/process_flow.md),
설계와 그 이유는 [docs/design/decision_tree_v4.md](docs/design/decision_tree_v4.md).

## 분류 체계

묶음은 증상이 아니라 **누가 고치는가**다. 다섯이고, 세부(안 씀 · 어긋남 · 조건 · 포맷 …)는
처음부터 가르지 않는다 — 데이터를 본 뒤 2단계에서 태그로 더한다.

| 묶음 | 고칠 곳 | 들어오는 길 |
|---|---|---|
| 정상 | 필터 | 후속 발화가 앞 답변을 문제 삼지 않는다 |
| 사용자 | 질문 유도 · UI | 감정 표출뿐 · 앞 질문에 없던 새 요구 |
| 근거 | 검색기 · 도구 연동 · 문서 | 근거 어디에도 답 없음 · 근거 자체가 없음 · 일부인데 빠진 쪽을 불평 |
| 생성 | 프롬프트 · 모델 | 근거에 답이 있는데 못 살림 · 언어 불일치 · 문서 무관 질문 오답 · 일부인데 있던 쪽을 틀림 |
| 시스템 | 인프라 · 서빙 · 권한 정책 | 자원 부족 문구 · 빈 답변 · 붕괴 · 거절에 불만 · 읽을 수 없음 · 잘림 |

- **검토**는 묶음이 아니라 상태다 — kev 가 확신하지 못한 턴. 분모 밖이고 막힌 문항이 기준문을 고칠
  곳이다.
- **플래그**(앞 턴 누락 · history 재구성 · 질문에 개인정보)는 트리 밖 열이다. 판정에 안 끼어든다.
- 지연 · 컨텍스트 초과 · 구 문서 · 권한 조회는 로그에 정보가 없어 **이 방법으로 못 보는 문제**다.

묶음 · 문항 · 플래그 전체는 [docs/taxonomy.md](docs/taxonomy.md).

## 출력

`output/<끝난시각>_<로그>_<필터>.json` — `run` · `summary` · `turns`. 턴마다 결론 → 이유 → 지나온
단계 순이고 값은 코드가 아니라 말이다.

```json
{
  "chat_id": "c-0192", "turn": 4, "event_time": "…", "target_turn": 3, "target_event_time": "…",
  "verdict": { "bucket": "생성", "sure": true, "stopped_at": "근거 판정",
               "because": "근거에 답이 전부 있었는데 답변이 살리지 못했다", "where": ["이번 턴 검색 청크"] },
  "steps": [
    { "step": "코드 확정", "rules": { "자원 부족 문구": "아니오", "빈 답변": "아니오", "붕괴": "아니오" } },
    { "step": "불만 판정", "answers": { "후속 발화가 답변을 문제 삼는다": { "answer": "예", "p": 0.97 }, "…": "…" } },
    { "step": "근거 판정", "answers": { "이번 턴 검색 청크에 답이 있다": { "answer": "예", "p": 0.95 },
                                       "근거 전체에 답이 있다": { "answer": "전부", "p": 0.97 }, "…": "…" } }
  ],
  "flags": { "앞 턴 누락": false, "history 재구성 턴 수": 0, "질문에 개인정보": false },
  "axes":  { "부서": "…", "직급": "…", "직무": "…", "answered_by": "rag", "ask_on": "web", "fallback": "" },
  "text":  { "question": "…", "answer": "…", "followup": "…", "history": [], "이번 턴 검색 청크": ["…"] }
}
```

`because` 는 멈춘 자리마다 고정 문장이라 같은 결론은 늘 같은 문장이고, 전달본 · 대시보드가 그
문장으로 센다. `steps` 의 `p` 는 보인 답의 확신이다 ("아니오 0.95" = 확신 있는 아니오), 모름일
때만 P(예). 검토면 `stopped_at` 이 `"불만 판정 · <문항 문장>"` 이다. `text` 는 `--no-text` 로
뺀다. 판정이 실패한 턴은 식별자와 `error` 만 남는다 (`[단계] 예외` · `[단계] 낙오`).

`output/<끝난시각>_<로그>_<필터>_summary.txt` — 실행 조건, 입력 형식 대조, 지표. 화면 끝에도 같은 것이 찍힌다.

| 지표 | 뜻 |
|---|---|
| `classified` · `kev calls` · `stopped at` | 판정 성공 · 실패 건수, 묶음별 건수, 어디서 멈췄나, kev 요청 수 |
| `decision` | 결정 백엔드. `(에뮬레이션)` 이면 kev 없이 일반 LLM 이 범주를 답한 것 |
| `filter FP` | 정상 비율과 몰린 eval 라벨 — 챗봇이 아니라 필터를 좁힐 신호 |
| `llm_fallback` | 에뮬레이션 LLM 의 응답이 잘려 조건을 바꿔 되살린 호출 — 다음엔 `--thinking off` |
| `failed at` | 실패가 몰린 단계 |

## 실무 전달본

위 결과 파일은 **되짚는 사람**을 위한 것이다. 챗봇을 고칠 사람은 다른 것을 묻는다 —
무엇이 제일 많이 터지나, 그중 하나를 보여 달라, 왜 그렇게 판정했나. 축을
**묶음 → 들어온 길 → 사례**로 바꿔 다시 담고, 검토와 플래그는 따로 낸다.

```bash
./venv/bin/python src/handover.py output/<결과.json>     # → <결과>_handover.json
```

**LLM 을 부르지 않는다** — 문구가 마음에 안 들면 이것만 다시 돌린다. 사례 하나는
`질문 · 답변 · 사용자_반응`(실제로 오간 말)과 `분석`(사유 · 지나온 단계 · 근거 위치) 두 덩이다.
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
| `--no-text` | 결과 파일에 질문 · 답변 · 근거 본문을 싣지 않는다 (전달본의 사례 절이 빈다) |

설정 우선순위는 **CLI > 설정 파일 > 환경변수 > 기본값**이다. 모든 키는
`configs/env.example.yaml` 에 있고, `--config` 를 안 주면 실행 위치의 `configs/env.yaml` 을 쓴다.

```bash
cp configs/env.example.yaml configs/env.yaml   # 커밋되지 않는다
python src/run.py --config configs/env.yaml --dry-run
```

- 판정 기준(kev 확신 임계 0.9 · 서비스 오류 확정 문구 · 재구성 턴 수 3)도 설정에서 바꾼다. 플래그가 없는 키는 `--set 키=값` 으로 준다.
- `llm_eval` · `llm_emotion` 의 **라벨 표는 `configs/query_taxonomy.md` · `configs/emotion_taxonomy.md`**
  에 있고 저장소에 함께 다닌다(형식: `A. 이름 -> 점수`). 분류 체계가 바뀌면 이 문서만 고친다.
  다른 점수표로 돌려보려면 `labels.query` · `labels.emotion` 으로 덮어쓴다.
- 실행 환경에서는 `llm.timeout_sec` 를 **120 정도로** 낮추는 것을 권한다. 낙오 기준이 서기 전(절반이
  끝나기 전)에 걸린 턴은 HTTP 타임아웃까지 기다리는데, 기본 600초는 사실상 무한 대기다.
- claude CLI · Anthropic API 로 판정하려면 `tools/dev_run.py` — 인자와 코드 경로가 같다.

## 대시보드

```bash
./venv/bin/pip install -r requirements-dashboard.txt
./venv/bin/python -m streamlit run src/dashboard.py -- --dept-class <체계.json> --job-class <체계.json>
```

`./output` 의 가장 최근 결과를 읽는다. 네 탭 — 분포(묶음 × 들어온 길 · 어디서 멈췄나 · 어디서
막혔나) · 조직 · 개별 케이스(결론 → 지나온 단계 → 본문) · 근거 보강. 맨 위는 **판정 건강**(정상 ·
검토 · 시스템 · 오류 · 앞 턴 누락)이다. 여기가 나쁘면 아래 집계를 믿을 수 없어서 순서를 그렇게
뒀다. 넘길 표는 CSV 로 내려받는다. 조직 분류 JSON 은 없어도 돈다.

## 구조

```
src/
  run.py              진입점 — 판정
  assemble.py         진입점 — eval.jsonl 경로 (select · check · example)
  handover.py         진입점 — 실무 전달본 (결과 파일만 읽는다)
  dashboard.py        대시보드
  ragdiag/
    features/         기능 등록부 — JUDGES 순서가 곧 판정 순서
      integrity/  pii/                        플래그 열 — 앞 턴 누락 · history 재구성 · 질문에 개인정보
      code_rules/                             코드 확정 — service_error · empty_answer · degenerate
      complaint/  evidence/  complaint_evidence/   kev 단계 셋 — 불만 판정 · 근거 판정 · 불만 부분 근거 판정
      classification/  llm_fallback/  filter_fp/  failures/   집계
      handover/                               전달본 — JUDGES 에 없다. handover.py 가 부른다
    conv.py · filters.py · labels.py · assemble.py   로그 파싱 · 짝짓기 · 필터 · eval.jsonl 조립 (여기 전용)
    taxonomy.py · questions.py                묶음 · 단계 · 이유 문장 / kev 문항 (원본 두 곳)
    judge.py · decide.py · backends.py        kev 호출 · 캐시 · 에뮬레이션 · LLM 접속
    results.py · schema.py                    턴 판정 결과(StepResult · Verdict) · Case
    output.py · pipeline.py · progress.py     결과 JSON · 단계별 함수 · 진행 표시
    textfmt.py                                터미널 표 정렬 (표시 폭)
    __main__.py · config.py · contracts.py · summary.py   실행 · 설정 · 입력 대조 · 요약
    fixtures/         합성 데이터 · v4 사례(출구마다 하나) · eval.jsonl 예시
tools/                개발 장비 전용 (claude CLI · API 백엔드)
```

기능(판정 단계 · 집계)을 더하려면 `features/template/` 을 복사하고 `features/__init__.py` 의
`JUDGES`(판정) 또는 `REPORTS`(집계) 에 한 줄 더한다. 코드 확정 규칙은 `features/code_rules/` 에
파일 하나(`NAME` · `check(answer)`)를 두고 `RULES` 에 한 줄.

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
ragdiag/settings.py   ragdiag/schema.py   ragdiag/taxonomy.py   ragdiag/questions.py
ragdiag/decide.py     ragdiag/backends.py ragdiag/judge.py      ragdiag/output.py
ragdiag/textfmt.py    ragdiag/pipeline.py ragdiag/results.py    ragdiag/progress.py
ragdiag/features/   (폴더 통째)
```
<!-- /copy-list -->
