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
  user_id · db_login_id · job_grade · db_dept_name · db_job_name · db_position_name
  conversations[]
    conversation_id
    turns[]
      turn · timestamp · user_question · llm_response
      retrieved_data                        그 질문으로 검색된 청크
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

필터 대신 이미 고른 턴 목록(`conversation_id` + `turn`, JSON 배열 또는 JSONL)을 `--turns` 로
줄 수도 있다. 어느 쪽이든 **로그는 자르지 않고 전체를 넣는다** — 판정 대상이 고른 턴의
직전 답변이기 때문이다.

## 처리 흐름

```
conv_eval ─┐
filter    ─┴─▶ 파싱 → 턴 고르기 → 짝짓기 (불만 턴 N+1 ↔ 턴 N 의 답변 · 문서)
                 → 서비스 오류 문구?   코드   걸리면 case9 로 끝
                 → 생성 붕괴?         코드   5555… · !!!!… 같은 반복이면 case30 으로 끝
                 → 읽을 수 있나?     LLM    답변만 본다 · 토큰 잡탕이면 case30 으로 끝
                 → Step 1 관측         LLM    문서를 주지 않는다
                 → 인용 · 요구 확인    코드   판정자가 적은 요구가 앞 질문에 있었나
                 → 코드 검증기 10종    코드   언어 · 포맷 · 개인정보 · 인용 · 계산 …
                 → Step 2 충족도       LLM    답변을 주지 않는다   (도메인 + 내용 불만일 때만)
                 → 인용 대조           코드   지어낸 인용을 버린다
                 → Step 3 근거 활용    LLM    불만을 주지 않는다   (문서가 충분할 때만)
                 → 라우팅              코드   관측 + 검증 → case
```

- **단계 하나가 기능 하나다.** 위 순서는 `src/ragdiag/features/__init__.py` 의 `FEATURES` 에
  적힌 순서 그대로다. 판정 순서가 적힌 곳은 거기뿐이다.
- **턴 하나가 판정 전부를 끝까지 간다** (`run.mode: turn`, 기본). 느린 턴이 다른 턴을 막지
  않고, 끝난 턴부터 10초마다 결과 파일에 쌓여 중간에 끊어도 거기까지는 남는다. 너무 오래
  끄는 턴은 `[단계] 낙오` 로 닫는데, 재실행하면 그 턴만 다시 묻는다.
- **LLM 은 턴당 최대 4회**, 대부분 2회(읽기 + 관측)다. 판정은 `.cache/` 에 저장돼 재사용된다.

**각 단계가 무엇을 받고 무엇을 일부러 안 받는지, 왜 그런지**는
[docs/process_flow.md](docs/process_flow.md). 그 결정을 어떻게 측정해서 내렸는지는
[docs/design/](docs/design/README.md).

## 분류 체계

case 는 증상이 아니라 **누가 고치는가**로 묶인다. 같은 "답이 부실하다"도 문서에 답이 없었는지
(case20 · 문서 보강), 문서엔 있는데 답변이 안 썼는지(case22 · 프롬프트 수정)에 따라 고칠 곳이 정반대다.

| type | 고칠 곳 | case |
|---|---|---|
| TYPE0 실패가 아님 | 필터 | case0 |
| TYPE1 적절하지 않은 질문/요청 | 질문 유도 · UI | case1 ~ 6 |
| TYPE2 서비스 안정성 | 인프라 | case7 ~ 9 · case30 (생성 붕괴, 원본에 없음) |
| TYPE3 의도 파악 실패 | 생성 프롬프트 · 후처리 | case10 ~ 17 |
| TYPE4 할루시네이션 | 생성 프롬프트 | case18 ~ 19 |
| TYPE5 Retrieve Context | 검색기 · 문서 · 생성 | case20 ~ 24 |
| TYPE6 일반 질문 | 모델 · 도구 연동 | case25 ~ 27 |
| TYPE7 보안/정책 | 권한 정책 · 입력 방어 | case28 ~ 29 |

- case5 · 7 · 8 · 19 · 23 은 로그에 필요한 필드가 없어 나오지 않는다.
- 주 case 와 별개로 성립한 것은 `secondary_cases` 에. 정할 수 없으면
  `unclassified`(수동 검토 대상), 맞는 case 가 없으면 `out_of_taxonomy`.
- 신뢰도 `high` 는 코드로 검증된 것, `medium` 은 LLM 판정, `low`(case25) 는 판정자의
  사전지식에 의존한다 — **같은 무게로 집계하지 않는다.**

case 별 정의와 판정 가능 여부는 [docs/taxonomy.md](docs/taxonomy.md).

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
    "case_id": "case22", "case_name": "Retrieve 성공, 생성 실패",
    "type_id": "TYPE5", "confidence": "medium",
    "reason": "문서에 답이 있는데 답변이 쓰지 않음",
    "secondary_cases": [], "notes": [],
    "evidence": { "observation": {}, "sufficiency": {}, "grounding": {}, "checks": [] },
    "llm_calls": 3, "answered_turn": 1
  }
}
```

앞 네 칸이 **짝지은 입력**이다 — 이전 질문들 · 비판받은 답변(턴 N) · 불만(턴 N+1) ·
그 답변의 문서. `evidence` 는 판정 근거로, 관측 · 충족도와 인용(**버려진 것 포함**) ·
근거 활용 · 코드 검증이 들어간다. 집계만 있고 근거가 없으면 "왜 이 라벨이지"에서 막힌다.
판정이 실패한 턴은 `classification.error` 만 남는다 (`[단계] 예외` · `[단계] 낙오` —
낙오는 재실행하면 그 턴만 다시 묻는다).

`output/<끝난시각>_<로그>_<필터>_summary.txt` — 실행 조건, 입력 형식 대조, 지표. 화면 끝에도 같은 것이 찍힌다.

| 지표 | 뜻 |
|---|---|
| `classified` · `llm calls` | 분류 성공 · 실패 건수, 상위 case, LLM 호출 수 |
| `filter FP` | case0(정상) 비율과 몰린 eval 라벨 — 챗봇이 아니라 필터를 좁힐 신호 |
| `llm_fallback` | 판정 LLM 의 응답이 잘려 조건을 바꿔 되살린 호출 — 다음엔 `--thinking off` |
| `failed at` | 실패가 몰린 단계 |

## 실무 전달본

위 결과 파일은 **되짚는 사람**을 위한 것이다. 챗봇을 고칠 사람은 다른 것을 묻는다 —
무엇이 제일 많이 터지나, 그중 하나를 보여 달라, 왜 그렇게 판정했나. 축을
**TYPE → case → 사례**로 바꿔 다시 담는다.

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
| `--turns <목록>` | 필터 대신 고른 턴 목록 |
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
ragdiag/backends.py   ragdiag/judge.py    ragdiag/verify.py     ragdiag/output.py
ragdiag/textfmt.py    ragdiag/requests.py
ragdiag/pipeline.py   ragdiag/results.py  ragdiag/progress.py
ragdiag/features/   (폴더 통째)
```
<!-- /copy-list -->
