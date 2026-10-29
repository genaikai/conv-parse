# 결정 트리 v4 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** v3 의 후보·등급 중재 파이프라인을 설계 문서의 결정 트리(코드 확정 → 불만 판정 → 근거 판정 → 불만 부분 근거 판정)로 갈아끼우고, 결과 파일 · 전달본 · 대시보드를 묶음 다섯 + 검토 기준으로 다시 짠다.

**Architecture:** `features/` 등록부(turn/stage 실행 · 낙오자 · 체크포인트)는 그대로 두고 판정 기능을 다섯(integrity · code_rules · complaint · evidence · complaint_evidence)으로 줄인다. 각 기능은 `TurnResult.steps` 에 한 칸을 남기고 `turn.close(...)` 로 닫는다. 문항은 `questions.py` 한 곳, 묶음·단계·고정 문장은 `taxonomy.py` 한 곳이 원본이고 결과 파일은 그 문장을 키로 쓴다.

**Tech Stack:** Python 3.11, pytest, 표준 라이브러리 (pydantic 은 kev 에뮬레이션에만), streamlit+pandas (대시보드).

**Spec:** `docs/design/decision_tree_v4.md`

## Global Constraints

- 저장소 관례: 한국어 주석 · 독스트링, 이유 먼저. 데이터 파일은 커밋하지 않는다 (fixture 는 코드). 루트에는 README.md · TODO.md 만.
- 묶음 id 는 영문 `normal · user · evidence · generation · system`, 검토는 `review`. 표시 이름은 `정상 · 사용자 · 근거 · 생성 · 시스템 · 검토`.
- 단계 이름(결과 파일 `stopped_at` · `steps[].step`): `코드 확정` · `불만 판정` · `근거 판정` · `불만 부분 근거 판정`.
- 확신 임계는 `settings.KEV_CONFIDENT = 0.9` 하나. noul: `p ≥ 0.9` 예, `p ≤ 0.1` 아니오, 사이 모름. choice: 최빈 선택지 `p ≥ 0.9` 면 그 선택지, 아니면 모름.
- 모름은 그 문항에서 멈추고 `review` 로 닫는다 (근거 판정의 칸별 문항만 예외 — 묶음에 안 끼어든다).
- kev 요청: 불만 판정 1 · 근거 판정 1 (칸이 전부 비면 0) · 불만 부분 근거 판정 1. 일반 LLM 0.
- history 재구성 상한 3턴. `history_chat` 이 있으면 자르지 않는다.
- 결과 파일 턴 하나의 키 순서: `chat_id, turn, event_time, target_turn, target_event_time, verdict, steps, flags, axes, text`.
- `tests/test_boundary.py` 의 CORE/LOCAL_ONLY 목록과 README 복사 목록을 같이 고친다. `tests/test_spec_compliance.py` 가 문서 ↔ 코드를 대조한다.
- 커밋 메시지는 한국어 한 줄 + `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. 커밋은 태스크 끝마다.

## Review Focus

1. `history_chat` 이 **있는데 비었고** 앞 턴이 있다 → 재구성 3턴 + 플래그 `앞 턴 누락: true`. 있고 1턴만 있으면 그대로 1턴 + 플래그 true(2턴 중 1). → Task 3 테스트.
2. 불만 판정 문항 1 이 **아니오** 인데 3 이 예 → 정상이어야 한다 (순서가 kev 가 아니라 코드). → Task 5 테스트.
3. 근거 판정 칸별이 **전부 확신 아니오** 인데 전체가 `일부` → 불만 부분 근거 판정으로 가야 한다 (칸별은 묶음에 안 끼어든다). → Task 6 테스트.
4. 근거 네 칸이 전부 비었다 → kev 0회, 근거(빈 묶음), `where` 는 네 칸 이름 전부. → Task 6 테스트.
5. kev 가 문항 하나를 안 돌려줬거나 예외 → 그 턴은 `error` 로 남고 다른 턴은 계속 (each_turn 규약) · 결과 파일에 `verdict` 없이 `error` 만. → Task 8 테스트.

---

### Task 1: 묶음 · 단계 · 문항 — 원본 한 곳씩

**Files:**
- Rewrite: `src/ragdiag/taxonomy.py`
- Rewrite: `src/ragdiag/questions.py`
- Create: `tests/test_taxonomy_v4.py`
- Delete: `tests/test_arbitrate.py`, `tests/test_requests.py`, `tests/test_verify.py`, `tests/test_legibility.py`, `tests/test_golden_sets.py`, `tests/test_citation_robustness.py`, `tests/test_quote_robustness.py`, `tests/test_per_stage_model.py`, `tests/test_checks.py`, `tests/test_features.py`, `tests/test_carried.py`, `tests/test_v3_pipeline.py`, `tests/test_snapshot.py`, `tests/snapshots/judgment.py` (이 태스크에서 지워야 뒤 태스크가 import 깨짐 없이 pytest 를 돈다. 남은 깨진 테스트는 각 태스크가 다시 쓴다)

**Interfaces:**
- Produces `taxonomy.py`:
  - `@dataclass(frozen=True) class Bucket: id: str; name: str; owner: str`
  - `BUCKETS: dict[str, Bucket]` — 순서 normal · user · evidence · generation · system · review. owner 는 설계 문서 묶음 표의 "고치는 사람" 그대로 (review 는 `"사람"`).
  - `STEP_CODE = "코드 확정"`, `STEP_COMPLAINT = "불만 판정"`, `STEP_EVIDENCE = "근거 판정"`, `STEP_COMPLAINT_EVIDENCE = "불만 부분 근거 판정"`, `STEPS: tuple[str, ...]` 그 순서.
  - `BECAUSE: dict[str, str]` — 키는 `"<단계>:<출구>"`. 출구: 코드 확정은 규칙 id (`service_error` · `empty_answer` · `degenerate`), 불만 판정은 문항 id + `:yes`/`:no` 중 묶음을 정하는 쪽 (`complains:no`, `refusal:yes`, `illegible:yes`, `truncated:yes`, `language:yes`, `emotion_only:yes`, `new_demand:yes`, `no_doc:yes`), 근거 판정은 `any:all` · `any:none` · `empty`, 불만 부분 근거 판정은 `targeted:yes` · `targeted:no`. 값은 고정 한국어 문장 (예: `"근거 판정:any:all" → "근거에 답이 전부 있었는데 답변이 살리지 못했다"`, `"근거 판정:empty" → "청크도 도구 결과도 앞 턴 근거도 메모리도 없었다"`).
  - `because_review(step: str, question_text: str, p: float) -> str` → `f"{question_text} — 확신이 없다 (p {p:.2f})"`.
  - `stopped_at_review(step: str, question_text: str) -> str` → `f"{step} · {question_text}"`.
- Produces `questions.py`:
  - `noul(instructions, true, false)` · `choice(instructions, options)` 그대로 둔다.
  - `COMPLAINT: dict[str, dict]` — **삽입 순서가 읽는 순서**. id 와 문장:

    | id | TEXT |
    |---|---|
    | `complains` | 후속 발화가 답변을 문제 삼는다 |
    | `refusal` | 정책·권한 거절이고 그걸 불평한다 |
    | `illegible` | 답변이 읽을 수 없는 글이다 |
    | `truncated` | 답변이 중간에 끊겼다 |
    | `language` | 답변이 질문과 다른 언어다 |
    | `emotion_only` | 후속 발화가 감정 표출뿐이다 |
    | `new_demand` | 앞 질문에 없던 새 요구를 하며 불평한다 |
    | `no_doc` | 문서·도구 없이 답할 질문이다 |

    criteria 는 설계 문서 "불만 판정" 표의 괄호 설명을 true/false 로 풀어 쓴다 (`language` 의 true 에 "질문이 요구한 언어가 있으면 그게 기준" 을 넣는다. `illegible` 은 기존 LEGIBILITY 문항의 지시문을 재사용).
  - `COMPLAINT_ROUTE: dict[str, tuple[str, str | None]]` — id → `(예일 때 묶음 id 또는 None, 아니오일 때 묶음 id 또는 None)`. None 은 "다음 문항". `complains: (None, "normal")`, `refusal: ("system", None)`, `illegible: ("system", None)`, `truncated: ("system", None)`, `language: ("generation", None)`, `emotion_only: ("user", None)`, `new_demand: ("user", None)`, `no_doc: ("generation", None)`.
  - `SLOTS: tuple[tuple[str, str], ...]` = `(("retrieved", "이번 턴 검색 청크"), ("tool", "이번 턴 도구 결과"), ("history", "앞 턴 근거"), ("memory", "메모리"))`.
  - `EVIDENCE_SLOT: dict[str, dict]` — id `in_<slot>` 넷, noul, 지시문 "`<칸 이름>` 에 질문의 일부라도 답하는 내용이 있는가. 주제만 같은 것은 아니오".
  - `EVIDENCE_ANY: dict[str, dict]` — id `any`, `choice(..., {"all": "질문이 묻는 것 전부에 답하는 내용이 네 칸을 합쳐 있다", "partial": "일부에만 있다", "none": "없다"})`.
  - `COMPLAINT_EVIDENCE: dict[str, dict]` — id `targeted`, noul "불만이 가리키는 부분에 답이 근거에 있다".
  - `TEXT: dict[str, str]` — 모든 문항 id → 결과 파일 키 문장 (`in_retrieved` → "이번 턴 검색 청크에 답이 있다", `any` → "근거 전체에 답이 있다", `targeted` → "불만이 가리키는 부분에 답이 근거에 있다").
  - `SKIPPED = "비어 있어 묻지 않음"`.

- [ ] **Step 1: 지울 테스트 · 스냅숏을 지운다** (위 Delete 목록). `git rm`.

- [ ] **Step 2: 실패하는 테스트를 쓴다** — `tests/test_taxonomy_v4.py`

```python
from ragdiag import questions, taxonomy

def test_buckets_are_five_plus_review_in_order():
    assert list(taxonomy.BUCKETS) == ["normal", "user", "evidence", "generation", "system", "review"]
    assert taxonomy.BUCKETS["evidence"].name == "근거"
    assert taxonomy.BUCKETS["review"].owner == "사람"

def test_complaint_questions_keep_the_reading_order():
    assert list(questions.COMPLAINT) == ["complains", "refusal", "illegible", "truncated",
                                         "language", "emotion_only", "new_demand", "no_doc"]
    assert set(questions.COMPLAINT_ROUTE) == set(questions.COMPLAINT)
    assert questions.COMPLAINT_ROUTE["complains"] == (None, "normal")

def test_every_question_has_a_result_sentence_and_sentences_are_unique():
    ids = [*questions.COMPLAINT, *questions.EVIDENCE_SLOT, *questions.EVIDENCE_ANY, *questions.COMPLAINT_EVIDENCE]
    assert set(ids) <= set(questions.TEXT)
    sentences = [questions.TEXT[i] for i in ids]
    assert len(sentences) == len(set(sentences))

def test_every_exit_has_a_fixed_sentence():
    for qid, (yes, no) in questions.COMPLAINT_ROUTE.items():
        if yes: assert f"{taxonomy.STEP_COMPLAINT}:{qid}:yes" in taxonomy.BECAUSE
        if no:  assert f"{taxonomy.STEP_COMPLAINT}:{qid}:no" in taxonomy.BECAUSE
    for key in ("any:all", "any:none", "empty"):
        assert f"{taxonomy.STEP_EVIDENCE}:{key}" in taxonomy.BECAUSE
    for key in ("service_error", "empty_answer", "degenerate"):
        assert f"{taxonomy.STEP_CODE}:{key}" in taxonomy.BECAUSE
    for key in ("targeted:yes", "targeted:no"):
        assert f"{taxonomy.STEP_COMPLAINT_EVIDENCE}:{key}" in taxonomy.BECAUSE

def test_any_question_is_a_three_way_choice():
    assert list(questions.EVIDENCE_ANY["any"]["criteria"]) == ["all", "partial", "none"]
```

- [ ] **Step 3: 실패 확인** — `pytest tests/test_taxonomy_v4.py -v` → ImportError/AttributeError.

- [ ] **Step 4: `taxonomy.py` · `questions.py` 를 위 인터페이스대로 다시 쓴다.** 옛 내용(GROUPS · LABELS · TAGS · from_v2 · OBSERVE · SUFFICIENCY …)은 전부 지운다. 독스트링에 설계 문서 경로와 "문장을 고치면 결과 키가 바뀐다" 를 적는다.

- [ ] **Step 5: 통과 확인** — `pytest tests/test_taxonomy_v4.py -v` → PASS.

- [ ] **Step 6: 커밋** — `v4 묶음 · 단계 · 문항 — 원본 한 곳씩`

---

### Task 2: 판정 결과 모양 — StepResult · Verdict · TurnResult · 확신 읽기

**Files:**
- Rewrite: `src/ragdiag/results.py`
- Modify: `src/ragdiag/settings.py` (KEV_LEAN · CHUNK_EVIDENCE_P · CHUNK_PARTIAL_P · LEGIBILITY · SEARCH_TOOL_NAMES 삭제), `src/ragdiag/config.py` (SPEC · TO_SETTINGS 에서 같은 키 삭제, `RETIRED` 에 `thresholds.kev_lean` · `thresholds.chunk_evidence` · `thresholds.chunk_partial` · `run.legibility` · `tools.search_names` 를 사유와 함께 추가, `llm.model_*`/`url_*`/`key_*` 단계별 키도 RETIRED 로), `configs/env.example.yaml` 에서 그 키 제거
- Create: `tests/test_results.py`
- Modify: `tests/test_config.py` (지운 키를 기대하는 단언 제거)

**Interfaces:**
- `read_noul(answer: Answer) -> str` → `"예" | "아니오" | "모름"` (임계 `settings.KEV_CONFIDENT`, 아니오는 `p ≤ 1 - KEV_CONFIDENT`).
- `read_choice(answer: Answer) -> str` → 최빈 선택지 id 또는 `"모름"`.
- `answer_payload(answer: Answer) -> dict` → noul `{"answer": "예"|"아니오"|"모름", "p": round(p, 3)}`, choice `{"answer": <선택지 한국어: all→"전부", partial→"일부", none→"없음", 모름→"모름">, "p": round(p,3)}`.
- `@dataclass class StepResult: step: str; rules: dict[str, str] | None = None; answers: dict[str, Any] | None = None` — `answers` 값은 `answer_payload` 결과 또는 `questions.SKIPPED` 문자열. **키는 문항 문장(`questions.TEXT`)** 이 아니라 **id** 로 들고 있고 출력 때 문장으로 바꾼다 (output.py).
- `@dataclass class Verdict: bucket: str; sure: bool; stopped_at: str; because: str; where: list[str]`.
- `@dataclass class TurnResult: case: Case; steps: list[StepResult]; verdict: Verdict | None = None; flags: dict[str, Any]; error: str | None; usage: Usage; n_calls: int = 0; n_kev_calls: int = 0`
  - `close(self, bucket: str, step: str, because: str, where: list[str] | None = None) -> None` — `sure=True`, `stopped_at=step`.
  - `review(self, step: str, question_id: str, p: float) -> None` — `bucket="review"`, `sure=False`, `stopped_at=taxonomy.stopped_at_review(step, questions.TEXT[question_id])`, `because=taxonomy.because_review(...)`, `where=[]`.
  - `is_open` property: `verdict is None and error is None`.
- `RunContext.open_turns()` 는 `is_open` 을 쓰도록 Task 4 에서 고친다.

- [ ] **Step 1: 실패하는 테스트** — `tests/test_results.py`

```python
from ragdiag import settings
from ragdiag.decide import Answer
from ragdiag.results import TurnResult, read_choice, read_noul, answer_payload
from helpers import case   # Task 3 에서 helpers.case 를 v4 Case 로 바꾼다. 이 태스크에서는 임시로 최소 Case 를 직접 만든다

def test_noul_reads_three_ways():
    assert read_noul(Answer("noul", p=0.95)) == "예"
    assert read_noul(Answer("noul", p=0.05)) == "아니오"
    assert read_noul(Answer("noul", p=0.55)) == "모름"
    assert read_noul(Answer("noul", p=0.9)) == "예"      # 경계 포함

def test_choice_needs_confident_mode():
    a = Answer("choice", p=0.92, choice="partial", probabilities={"all": 0.04, "partial": 0.92, "none": 0.04})
    assert read_choice(a) == "partial"
    assert read_choice(Answer("choice", p=0.6, choice="all", probabilities={"all": 0.6})) == "모름"
    assert answer_payload(a) == {"answer": "일부", "p": 0.92}

def test_close_and_review_set_the_verdict():
    t = TurnResult(case=_case())
    assert t.is_open
    t.review("불만 판정", "refusal", 0.55)
    assert t.verdict.bucket == "review" and not t.verdict.sure
    assert t.verdict.stopped_at == "불만 판정 · 정책·권한 거절이고 그걸 불평한다"
    assert "0.55" in t.verdict.because
    assert not t.is_open
```

- [ ] **Step 2: 실패 확인** — `pytest tests/test_results.py -v`.

- [ ] **Step 3: `results.py` 를 다시 쓴다.** Check · Candidate · Classification · Sufficiency · ClaimVerdict 는 지운다. settings/config 키를 지우고 RETIRED 에 옮긴다.

- [ ] **Step 4: 통과 확인** — `pytest tests/test_results.py tests/test_config.py -v`.

- [ ] **Step 5: 커밋** — `v4 판정 결과 모양 — 단계 칸 · 결론 · 확신 읽기`

---

### Task 3: Case 와 파싱 — history 메시지 · 재구성 · 식별자 · 축

**Files:**
- Modify: `src/ragdiag/schema.py` (pydantic 모델 전부 삭제 — Observation · ObservationText · SufficiencyJudgment · LegibilityCheck · GroundingCheck · Claims · Claim · QuotePair · Evidence · Label · Verdict · UsedRag; Case 만 남기고 필드 추가)
- Modify: `src/ragdiag/conv.py` (`HistoryInput.messages`, `parse_history_input`, `to_case`, 새 `reconstruct_history`)
- Modify: `src/ragdiag/assemble.py` (`records_to_payload`: `_stub` 턴은 본문이 없을 때만. 앞 3턴 본문이 records 에 있으면 그대로 싣는다) · `docs/assemble.md` 계약에 한 줄
- Modify: `tests/helpers.py` (`case()` 만 남기고 obs/checks/probs/turn 삭제; 새 필드 기본값)
- Modify: `tests/test_conv.py`, `tests/test_history_input.py`, `tests/test_assemble.py` (깨진 단언 교체 + 아래 테스트 추가)

**Interfaces:**
- `Case` 추가 필드 (기본값 있음, 기존 필드 유지):
  - `event_time: str = ""` (N+1), `target_event_time: str = ""` (N)
  - `history_messages: list[dict] = []` — `[{"role": "user"|"assistant", "content": str}, …]` 순서대로. 불만 판정의 history.
  - `history_reconstructed: int = 0` — 재구성했으면 그 턴 수.
  - `answered_by: str = ""`, `ask_on: str = ""`, `fallback: str = ""` — turn N 의 것.
  - 속성 `retrieved_chunks` · `tool_chunks` · `history_chunks` : `rag_chunks` 를 `chunk_sources` 로 가른 목록 (`"retrieved"` / `tool*` / `history_*`).
  - `prior_answers` 필드는 지운다 (history_messages 가 대신한다). `legibility` 등 v3 전용 필드는 없다.
- `HistoryInput.messages: list[dict]` — role/content 쌍, 빈 content 는 건너뜀.
- `reconstruct_history(prior: list[Turn], answered: Turn, limit: int = 3) -> list[dict]` — `answered.carried_turn_nos` 가 있으면 그 번호의 턴, 없으면 `prior` 에서 answered 를 뺀 최근 `limit` 개. 턴마다 user 메시지 → assistant 메시지. **3 개 상한은 carried 쪽에도 건다.**
- `to_case` 규칙: `history.present and history.messages` → 그대로, `history_reconstructed = 0`. 그 밖에 (`not present`, 또는 present 인데 messages 비었고 prior 가 있음) → 재구성. 첫 턴은 빈 목록.

- [ ] **Step 1: 실패하는 테스트** — `tests/test_history_input.py` 에 추가

```python
def test_history_chat_is_kept_as_ordered_messages():
    case = _case_with_history([("user", "반차 어떻게 신청해요"), ("assistant", "그룹웨어에서요")])
    assert case.history_messages == [{"role": "user", "content": "반차 어떻게 신청해요"},
                                     {"role": "assistant", "content": "그룹웨어에서요"}]
    assert case.history_reconstructed == 0

def test_empty_history_chat_with_prior_turns_is_reconstructed_up_to_three():
    conv = _conversation(n_turns=6, history_chat=[])        # turn 6 이 불만, 5 가 답변, 1~4 가 앞 턴
    case = to_case(conv, followup_turn=6)
    assert case.history_reconstructed == 3
    assert [m["content"] for m in case.history_messages if m["role"] == "user"] == ["q2", "q3", "q4"]

def test_partial_history_chat_is_not_padded():
    conv = _conversation(n_turns=6, history_chat=[("user", "q4"), ("assistant", "a4")])
    case = to_case(conv, followup_turn=6)
    assert case.history_reconstructed == 0 and len(case.history_messages) == 2

def test_first_turn_has_no_history_and_no_reconstruction():
    conv = _conversation(n_turns=2, history_chat=None)
    case = to_case(conv, followup_turn=2)
    assert case.history_messages == [] and case.history_reconstructed == 0

def test_case_carries_both_event_times_and_turn_axes():
    conv = _conversation(n_turns=2, history_chat=None)
    case = to_case(conv, followup_turn=2)
    assert case.event_time == conv.turns[1].event_time
    assert case.target_event_time == conv.turns[0].event_time
    assert case.answered_by == conv.turns[0].answered_by
```

(`_conversation` · `_case_with_history` 는 그 파일의 기존 보조 함수를 쓰거나 같은 방식으로 만든다.)

- [ ] **Step 2: 실패 확인** — `pytest tests/test_history_input.py -v`.

- [ ] **Step 3: schema.py · conv.py · assemble.py · helpers.py 를 고친다.** `assemble.records_to_payload` 에서는 selected 행의 `n_prior` 로 만든 앞 턴 번호 중 records 에 본문이 있는 것은 `_stub` 없이 싣는다. `docs/assemble.md` 의 records.jsonl 절에 "`history_input` 이 빈 답변 턴은 앞 3턴의 `user_question` · `llm_response` 행도 넣는다 (turn 번호 포함)" 를 더한다.

- [ ] **Step 4: 통과 확인** — `pytest tests/test_conv.py tests/test_history_input.py tests/test_assemble.py -v`.

- [ ] **Step 5: 커밋** — `v4 Case — history 메시지 · 3턴 재구성 · 두 식별자`

---

### Task 4: 등록부 정리 — integrity · code_rules, 나머지 기능 삭제

**Files:**
- Modify: `src/ragdiag/features/__init__.py` (JUDGES · REPORTS · CHECKS 재정의, import 정리)
- Modify: `src/ragdiag/features/_shared.py` (`grade_from_p` · `top_cases` 삭제, `call_llm` 삭제, `bucket_counts(turns) -> Counter` 추가)
- Modify: `src/ragdiag/features/_context.py` (`open_turns` 가 `is_open`)
- Rewrite: `src/ragdiag/features/integrity/__init__.py` (플래그 dict)
- Create: `src/ragdiag/features/code_rules/__init__.py` + `empty_answer.py`; Move: `short_circuit/service_error.py` · `degenerate.py` → `code_rules/` (CASE/REASON/NOTES 상수 제거, `check(turn) -> bool, detail` 로 단순화)
- Delete: `features/arbitrate` `arithmetic` `carried` `claims` `consistency` `dates` `format` `history_quote` `injection` `language` `legibility` `length` `memory_check` `observe` `python_syntax` `quoted_spans` `quotes` `request_quote` `short_circuit` `sql_shape` `sufficiency` `tool_numbers` `template`(있으면) ; `src/ragdiag/verify.py` `requests.py` `prompts.py` `golden.py`; `src/ragdiag/fixtures/v3_cases.py` `judgments.py` `observations.py` `messy.py` `public_docs.py`
- Modify: `features/classification/__init__.py` (묶음 건수 · 멈춘 단계 건수 · kev 호출 수), `filter_fp` (`primary_case == "N0"` → `verdict.bucket == "normal"`), `failures` 그대로, `llm_fallback` 그대로
- Modify: `src/ragdiag/features/pii/__init__.py` → `find_pii` 만 남기고 `process_data` 삭제 (integrity 가 부른다)
- Create: `tests/test_code_rules.py`, `tests/test_integrity.py`

**Interfaces:**
- `features.JUDGES = (integrity, code_rules, complaint, evidence, complaint_evidence)` — complaint 셋은 Task 5~7 에서 만든다. 이 태스크에서는 **빈 자리 없이** `JUDGES = (integrity, code_rules)` 로 두고 Task 5~7 이 하나씩 더한다.
- `features.REPORTS = (classification, llm_fallback, filter_fp, failures)`.
- `integrity.process_data`: 턴마다 `turn.flags = {"앞 턴 누락": bool | "옛 로그 — 판정 안 함", "history 재구성 턴 수": int, "질문에 개인정보": bool}`. 앞 턴 누락 = `case.history_present and case.history_turn_count < max(len(case.prior_turn_nos) - 1, 0)`; 옛 로그는 `not case.history_present`. 개인정보는 `find_pii(case.pre_queries[-1])` 비어 있지 않음. 멈추지 않는다.
- `code_rules.RULES = (service_error, empty_answer, degenerate)`; 각 모듈 `NAME: str`, `check(answer: str) -> tuple[bool, str]`. `process_data`: 순서대로 돌려 `StepResult(step=STEP_CODE, rules={name: "예"|"아니오"})` 를 `turn.steps` 에 넣고, 처음 걸리면 `turn.close("system", STEP_CODE, BECAUSE[f"{STEP_CODE}:{name}"])` 하고 **그 뒤 규칙은 `"보지 않음"`** 으로 적는다. 안 걸리면 전부 `"아니오"`.
- `empty_answer.check`: `not answer.strip()` → `(True, "답변이 비어 있음")`.

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_code_rules.py
from ragdiag.features import code_rules
from ragdiag.features.code_rules import empty_answer

def test_empty_answer_is_a_rule():
    assert empty_answer.check("  \n")[0] is True
    assert empty_answer.check("네")[0] is False

def test_first_hit_closes_as_system_and_later_rules_are_not_looked_at(ctx_with):
    ctx = ctx_with(answer="")
    code_rules.process_data(ctx)
    [t] = ctx.turns
    assert t.verdict.bucket == "system" and t.verdict.stopped_at == "코드 확정"
    assert t.steps[0].rules == {"service_error": "아니오", "empty_answer": "예", "degenerate": "보지 않음"}

def test_clean_answer_leaves_the_turn_open_with_all_rules_recorded(ctx_with):
    ctx = ctx_with(answer="연차는 15일입니다.")
    code_rules.process_data(ctx)
    [t] = ctx.turns
    assert t.is_open and set(t.steps[0].rules.values()) == {"아니오"}

# tests/test_integrity.py
def test_missing_prior_turns_flag(ctx_with):
    ctx = ctx_with(history_present=True, history_turn_count=1, prior_turn_nos=[1, 2, 3])
    integrity.process_data(ctx)
    assert ctx.turns[0].flags["앞 턴 누락"] is True and ctx.turns[0].is_open

def test_old_logs_do_not_judge_missing_turns(ctx_with):
    ctx = ctx_with(history_present=False)
    integrity.process_data(ctx)
    assert ctx.turns[0].flags["앞 턴 누락"] == "옛 로그 — 판정 안 함"
```

`ctx_with(**case_kw)` 는 `tests/conftest.py` 의 fixture 로 만든다: `RunContext(turns=[TurnResult(case=case(**kw))], judge=None, workers=1, progress=False)`. `answer=` 는 `llm_ans_on_last_q` 로 넘긴다.

- [ ] **Step 2: 실패 확인** — `pytest tests/test_code_rules.py tests/test_integrity.py -v`.

- [ ] **Step 3: 삭제 · 이동 · 재작성.** 등록부 독스트링의 "기능을 만들려면" 절은 유지. `features/template` 폴더가 있으면 새 모양(StepResult 를 남기는 빈 기능)으로 바꾼다.

- [ ] **Step 4: 통과 확인** — `pytest tests/test_code_rules.py tests/test_integrity.py -v`, 그리고 `python -c "import ragdiag.features"` 가 import 에러 없이 끝난다.

- [ ] **Step 5: 커밋** — `v4 등록부 — 코드 확정 셋 · 플래그 열, 중재 계열 기능 삭제`

---

### Task 5: 불만 판정 (kev 8문항, 순서로 읽음)

**Files:**
- Create: `src/ragdiag/features/complaint/__init__.py`
- Modify: `src/ragdiag/features/__init__.py` (JUDGES 에 complaint 추가)
- Modify: `src/ragdiag/judge.py` — `STAGES` · `complete` 계열 메서드(observe · observe_text · judge_sufficiency_from · check_legibility · extract_claims · quote_pair …) · prompts import 삭제. `DECISION_STAGES = ("complaint", "evidence", "complaint_evidence")`. `models()` 는 `{"decision": <결정 모델>}` 만. `all_backends()` 는 에뮬레이션 백엔드가 있으면 그것.
- Create: `tests/test_complaint.py`

**Interfaces:**
- `complaint.NAME = "complaint"`.
- `state_of(case: Case) -> dict` → `{"history": case.history_messages, "question": case.last_query, "answer": case.llm_ans_on_last_q, "followup": case.current_query}`.
- `read(answers: dict[str, Answer]) -> tuple[str | None, str | None, float | None]` → `(bucket_id, because_key, None)` 로 닫힘 / `(None, None, None)` 으로 다음 단계 / `("review", question_id, p)` 로 모름. COMPLAINT 순서대로 `read_noul` → `COMPLAINT_ROUTE` 적용.
- `process_data(ctx)`: `each_turn(..., parallel=True)`. 턴마다 `call_kev(turn, ctx, "complaint", state, questions.COMPLAINT)`, `StepResult(step=STEP_COMPLAINT, answers={qid: answer_payload(a)})` 를 **여덟 전부** 넣고 `read` 결과대로 `close`/`review`/그대로.

- [ ] **Step 1: 실패하는 테스트** — `tests/test_complaint.py`. `ScriptedBackend` 로 `Judge(backend=None, cache_dir=None, decision=ScriptedBackend(script))` 를 만들고 `ctx_with(..., judge=judge)` 로 돌린다. `script` 는 `{qid: bool|float}` 를 돌려준다.

```python
def test_no_complaint_is_normal_even_if_later_questions_say_yes(run):
    t = run({"complains": False, "illegible": True})
    assert t.verdict.bucket == "normal" and t.verdict.stopped_at == "불만 판정"
    assert t.steps[-1].answers["illegible"]["answer"] == "예"     # 여덟 전부 실린다

@pytest.mark.parametrize("qid,bucket", [("refusal", "system"), ("illegible", "system"), ("truncated", "system"),
                                        ("language", "generation"), ("emotion_only", "user"),
                                        ("new_demand", "user"), ("no_doc", "generation")])
def test_each_yes_exit(run, qid, bucket):
    t = run({"complains": True, qid: True})
    assert t.verdict.bucket == bucket and t.verdict.because == taxonomy.BECAUSE[f"불만 판정:{qid}:yes"]

def test_all_no_leaves_the_turn_open_for_evidence(run):
    t = run({"complains": True})
    assert t.is_open and t.steps[-1].step == "불만 판정"

def test_unsure_stops_at_that_question(run):
    t = run({"complains": True, "refusal": 0.55, "no_doc": True})
    assert t.verdict.bucket == "review"
    assert t.verdict.stopped_at == "불만 판정 · 정책·권한 거절이고 그걸 불평한다"

def test_state_has_history_and_no_documents(run_capture):
    state = run_capture({"complains": False})
    assert set(state) == {"history", "question", "answer", "followup"}

def test_one_kev_call_per_turn(run):
    t = run({"complains": True})
    assert t.n_kev_calls == 1
```

- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현.** judge.py 정리까지. `judge.decide` 캐시 키의 단계 이름이 바뀌므로 옛 캐시는 자연히 빗나간다 — 독스트링에 한 줄.
- [ ] **Step 4: 통과 확인** — `pytest tests/test_complaint.py tests/test_decide.py -v`.
- [ ] **Step 5: 커밋** — `v4 불만 판정 — kev 8문항 한 요청, 코드가 순서로 읽는다`

---

### Task 6: 근거 판정 (kev 5문항, 전체가 정함)

**Files:**
- Create: `src/ragdiag/features/evidence/__init__.py`
- Modify: `src/ragdiag/features/__init__.py`
- Create: `tests/test_evidence.py`

**Interfaces:**
- `evidence.NAME = "evidence"`.
- `slots_of(case: Case) -> dict[str, list[str]]` → `{"retrieved": case.retrieved_chunks, "tool": case.tool_chunks, "history": case.history_chunks, "memory": [case.memory] if case.memory.strip() else []}`.
- `state_of(case, slots) -> dict` → `{"question": case.last_query, <칸 이름>: list, …}` — 칸 이름은 `questions.SLOTS` 의 한국어.
- `questions_for(slots) -> dict` → 비어 있지 않은 칸의 `EVIDENCE_SLOT` + `EVIDENCE_ANY`.
- `read(answers, slots) -> ...` 규칙:
  - any 전부 → `close("generation", STEP_EVIDENCE, BECAUSE["근거 판정:any:all"], where=[칸 이름 for 칸별 예])`
  - any 없음 → `close("evidence", ..., BECAUSE["근거 판정:any:none"], where=[빈 칸 이름 + 칸별 아니오 칸 이름])`
  - any 일부 → 그대로 열어 둠 (다음 단계). `turn.flags` 에 안 적고 `steps` 만 남긴다.
  - any 모름 → `review(STEP_EVIDENCE, "any", p)`
- 네 칸 전부 비면 kev 안 부르고 `StepResult(step=STEP_EVIDENCE, answers={모든 id: SKIPPED})` + `close("evidence", STEP_EVIDENCE, BECAUSE["근거 판정:empty"], where=[네 칸 이름 전부])`.
- `process_data`: `each_turn(..., parallel=True)`. 불만 판정을 지나 열린 턴만 온다 (등록부 순서).

- [ ] **Step 1: 실패하는 테스트**

```python
def test_all_slots_empty_closes_without_kev(run):
    t = run(slots={}, script={})
    assert t.n_kev_calls == 0 and t.verdict.bucket == "evidence"
    assert t.verdict.where == ["이번 턴 검색 청크", "이번 턴 도구 결과", "앞 턴 근거", "메모리"]
    assert t.steps[-1].answers["any"] == "비어 있어 묻지 않음"

def test_empty_slots_are_not_asked(run_capture):
    questions_asked = run_capture(slots={"retrieved": ["청크"]}, script={"any": "all", "in_retrieved": True})
    assert set(questions_asked) == {"in_retrieved", "any"}

def test_all_means_generation_with_where(run):
    t = run(slots={"retrieved": ["c"], "history": ["h"]}, script={"in_retrieved": True, "in_history": False, "any": "all"})
    assert t.verdict.bucket == "generation" and t.verdict.where == ["이번 턴 검색 청크"]

def test_none_means_evidence_with_where(run):
    t = run(slots={"retrieved": ["c"]}, script={"in_retrieved": False, "any": "none"})
    assert t.verdict.bucket == "evidence" and t.verdict.where == ["이번 턴 검색 청크", "이번 턴 도구 결과", "앞 턴 근거", "메모리"]

def test_partial_stays_open_even_if_every_slot_said_no(run):
    t = run(slots={"retrieved": ["c"], "tool": ["t"]}, script={"in_retrieved": False, "in_tool": False, "any": "partial"})
    assert t.is_open

def test_slot_unsure_does_not_matter_when_any_is_confident(run):
    t = run(slots={"retrieved": ["c"]}, script={"in_retrieved": 0.5, "any": "all"})
    assert t.verdict.bucket == "generation" and t.verdict.where == []

def test_any_unsure_is_review(run):
    t = run(slots={"retrieved": ["c"]}, script={"in_retrieved": True, "any": {"all": 0.5, "partial": 0.4, "none": 0.1}})
    assert t.verdict.bucket == "review" and t.verdict.stopped_at == "근거 판정 · 근거 전체에 답이 있다"

def test_state_has_no_answer_and_no_followup(run_capture_state):
    state = run_capture_state(slots={"retrieved": ["c"]}, script={"any": "none"})
    assert "answer" not in state and "followup" not in state
```

- [ ] **Step 2: 실패 확인.** — [ ] **Step 3: 구현.** — [ ] **Step 4: 통과 확인** `pytest tests/test_evidence.py -v`.
- [ ] **Step 5: 커밋** — `v4 근거 판정 — 칸별은 어디, 전체가 있었나`

---

### Task 7: 불만 부분 근거 판정 (일부일 때만)

**Files:**
- Create: `src/ragdiag/features/complaint_evidence/__init__.py`
- Modify: `src/ragdiag/features/__init__.py` (JUDGES 완성: integrity · code_rules · complaint · evidence · complaint_evidence)
- Create: `tests/test_complaint_evidence.py`

**Interfaces:**
- `state_of(case, slots) -> dict` → evidence 의 state + `"followup": case.current_query`. 답변 없음.
- `read`: `targeted` 예 → `close("generation", STEP_COMPLAINT_EVIDENCE, BECAUSE[...targeted:yes])`, 아니오 → `close("evidence", ...)`, 모름 → `review`.
- 여기 오는 턴은 evidence 가 열어 둔 것뿐이다 (`where` 조건 없음 — 등록부 순서가 보장).

- [ ] **Step 1: 실패하는 테스트** — 예/아니오/모름 셋과 "state 에 answer 가 없다", "evidence 가 닫은 턴은 안 돈다 (n_kev_calls 그대로)".
- [ ] **Step 2–4: 실패 확인 · 구현 · 통과.**
- [ ] **Step 5: 커밋** — `v4 불만 부분 근거 판정 — 근거가 일부일 때만`

---

### Task 8: 결과 파일 · 요약 · 진입점

**Files:**
- Rewrite: `src/ragdiag/output.py`
- Modify: `src/ragdiag/pipeline.py` (`build_outcome(owners, results, filter_report, run_info, with_text)`; `Outcome.summary()`; `make_judge(backend, use_cache, decision)` — per_stage 삭제)
- Modify: `src/ragdiag/__main__.py` — 삭제: `--golden` `--observe-only` `--golden-set` `--model-<stage>` `--base-url-<stage>` `--api-key-<stage>` `per_stage_backends` `run_golden` `run_routing_golden` `run_legibility_golden` `run_judge_golden` `_probe_case`; 추가: `--no-text`; `check_llm` 은 `LLMDecisionBackend(backend).decide({"answer": "테스트"}, {"probe": questions.noul("답변이 비었는가")})` 로 1회 호출해 소요 시간을 찍는다; 요약 metrics 에서 `llm calls` 는 에뮬레이션일 때만 의미가 있으니 kev 다음 줄로; `_checkpointer` 는 새 `build_output` 서명으로.
- Modify: `src/ragdiag/summary.py` 가 taxonomy 를 import 하면 제거.
- Rewrite: `tests/stub_judge.py` (ScriptedBackend 만 쓰는 `ScriptedJudge`; case_id 접미어로 경로를 고른다: `normal` · `system-code` · `system-refusal` · `generation-lang` · `user-emotion` · `evidence-empty` · `evidence-none` · `generation-all` · `partial-yes` · `partial-no` · `review-complaint`), `tests/test_output.py`, `tests/test_run_mode.py`, `tests/test_straggler.py` (import 만 고침)
- Create: `tests/snapshots/v4.py` + `tests/test_snapshot.py` (경로 11개의 `verdict` 를 dict 로 박아 둔 스냅숏)

**Interfaces:**
- `build_turn(result: TurnResult, conv, with_text: bool = True) -> dict` — 설계 문서 "결과 파일" 모양. `steps[].answers` 의 키를 `questions.TEXT[id]` 로 바꾼다. `axes = {"부서", "직급", "직무", "answered_by", "ask_on", "fallback"}`. `text = {"question", "answer", "followup", "history", <네 칸 이름>}`. `error` 가 있으면 `{"chat_id", "turn", "event_time", "target_turn", "target_event_time", "error"}` 만.
- `build_output(pairs, run_info: dict, with_text: bool = True) -> dict` → `{"run": run_info, "summary": summary_of(results), "turns": [...]}`. `summary_of(results) -> dict` = `{"turns", "buckets": {한국어 이름: n}, "stopped_at": {단계: n}, "review_at": {stopped_at 문자열: n}, "errors": n, "kev_calls": n}`.
- `summarize(pairs) -> str` — 터미널 요약: 묶음 표(건수 · 비율) · 멈춘 단계 · 검토 상위 5 문항 · 오류 · kev 호출. 80칸.
- `run_info` 는 `__main__` 이 만든다: `{"started", "conv_data", "filter_data" | "turns", "kev": judge.models()["decision"], "kev_kind", "threshold": settings.KEV_CONFIDENT, "version"}`.

- [ ] **Step 1: 실패하는 테스트** — `tests/test_output.py`

```python
def test_turn_keys_are_in_reading_order(result_generation):
    turn = build_turn(result_generation, conv)
    assert list(turn) == ["chat_id", "turn", "event_time", "target_turn", "target_event_time",
                          "verdict", "steps", "flags", "axes", "text"]
    assert list(turn["verdict"]) == ["bucket", "sure", "stopped_at", "because", "where"]
    assert turn["verdict"]["bucket"] == "생성"

def test_answers_are_keyed_by_sentence_not_id(result_generation):
    step = build_turn(result_generation, conv)["steps"][1]
    assert "후속 발화가 답변을 문제 삼는다" in step["answers"] and "complains" not in step["answers"]

def test_no_text_drops_the_block(result_generation):
    assert "text" not in build_turn(result_generation, conv, with_text=False)

def test_error_turn_has_only_identity_and_error(result_error):
    assert set(build_turn(result_error, conv)) == {"chat_id", "turn", "event_time", "target_turn", "target_event_time", "error"}

def test_summary_counts_buckets_and_review_questions(pairs):
    s = summary_of([r for _, r in pairs])
    assert set(s["buckets"]) == {"정상", "사용자", "근거", "생성", "시스템", "검토"}
    assert sum(s["buckets"].values()) + s["errors"] == s["turns"]
```

그리고 `tests/test_snapshot.py`: `ScriptedJudge` 로 11 경로를 돌려 `verdict` dict 가 `snapshots/v4.py` 와 같다; `test_run_mode.py` 의 turn/stage 동일성은 그대로.

- [ ] **Step 2: 실패 확인.** — [ ] **Step 3: 구현.** — [ ] **Step 4: 통과** `pytest tests/test_output.py tests/test_snapshot.py tests/test_run_mode.py tests/test_straggler.py -v`, 그리고 `python src/run.py --dry-run` 이 0 으로 끝난다 (synth 데이터).
- [ ] **Step 5: 커밋** — `v4 결과 파일 — 결론 · 이유 · 지나온 단계, 말로 쓴다`

---

### Task 9: v4 fixture 와 끝까지 도는 테스트

**Files:**
- Create: `src/ragdiag/fixtures/v4_cases.py`
- Create: `tests/test_v4_pipeline.py`
- Modify: `src/ragdiag/fixtures/synth.py` 가 v3 라벨을 심으면 (planted signal) 그 부분만 고친다 — `tests/test_spec_compliance.py::test_synth_scales_without_losing_the_planted_signal` 가 보는 것을 v4 묶음으로.

**Interfaces:**
- `v4_cases.CASES: list[dict]` — 사례 하나: `dict(id, note, question, answer, followup, history=[...], retrieved=[...], tool=[...], history_evidence=[...], memory="", complaint={qid: bool|float}, evidence={qid: ...}, targeted=bool|float, expect=dict(bucket, stopped_at, where?, sure))`. 최소 사례: 코드 확정 셋(`sys-service-error` · `sys-empty` · `sys-degenerate`), 불만 판정 여덟 출구, 근거 판정 전부·없음·빈 묶음, 불만 부분 근거 예·아니오, 검토 둘(불만 판정 · 근거 판정), history 재구성 하나(`history_messages` 비움 + `history_reconstructed=3` 기대), 앞 턴 누락 플래그 하나. 반도체 사내 도메인 문장을 쓰되 `scripts/sync-allow.txt` 에 있는 어휘 규칙(C9)을 피한다 — "규격" 은 이미 예외 문구 안에서만.
- `tests/test_v4_pipeline.py::run(fx) -> TurnResult` — `ScriptedBackend` 가 `current_turn()` 의 case_id 로 fixture 를 찾아 단계별 답을 준다. 테스트 셋: 사례마다 `expect` 일치, `test_every_exit_is_covered` (BECAUSE 의 키 전부가 어느 사례의 `because` 로 나온다), `test_kev_calls_never_exceed_three`.

- [ ] **Step 1: 테스트 · fixture 를 쓴다** (fixture 가 곧 테스트 입력이라 둘을 같이).
- [ ] **Step 2: 돌려서 실패를 본다** — 깨지는 사례가 있으면 코드(Task 4~7)의 결함이다. 고친다.
- [ ] **Step 3: 통과** `pytest tests/test_v4_pipeline.py -v`.
- [ ] **Step 4: 커밋** — `v4 fixture — 출구마다 하나씩 끝까지 돈다`

---

### Task 10: 전달본

**Files:**
- Rewrite: `src/ragdiag/features/handover/__init__.py`
- Modify: `src/handover.py` (`"turns" not in result` 검사, 출력 줄: 묶음별 건수 · 검토 건수)
- Rewrite: `docs/handover.md`
- Rewrite: `tests/test_handover.py` (엔트리 목록 단언 `run.py · assemble.py · dashboard.py · handover.py` 유지)

**Interfaces:**
- `build(result: dict, source: str = "", generated_at: str | None = None) -> dict`:
  ```
  생성일시
  대상        { 로그 · 분석한 턴 · 실패로 판정 · 정상으로 판정 · 검토 · 오류 }
  제외한_실패  고정 문장 (지연 · 컨텍스트 초과 · 구 문서 · 권한 조회 · 인젝션 · 개인정보 유출 — 이 방법으로 안 본다)
  분류[]      { 묶음 · 고칠_곳 · 건수 · 들어온_길{because: n} · 사례[] }   건수 많은 순. normal · review 제외
                사례 { 질문 · 답변 · 사용자_반응 · 분석 { 사유 · 지나온_단계[] · 근거_위치 · meta_data{대화 · 턴 · 부서 · 직급 · 직무} } }
  검토        { 설명 · 건수 · 막힌_문항{stopped_at: n} · 사례[] }   맨 뒤
  플래그      { 앞 턴 누락: n · history 재구성: n · 질문에 개인정보: n }   있을 때만
  ```
  `지나온_단계` 는 `steps` 를 한 줄씩: 코드 확정 → `"코드 확정: 전부 아니오"`, kev 단계 → `"불만 판정: 문제 삼음 예 · 거절 아니오 · …"` 식으로 문장 앞 6자 + 답. `text` 가 없으면 사례의 질문·답변·반응 칸을 `"(본문 없음 — --no-text)"` 로.

- [ ] **Step 1: 실패하는 테스트** — 묶음이 건수 순 · normal 제외 · review 맨 뒤 · 플래그는 전부에서 센다 · 사례에 `p` 숫자가 안 들어간다 (`test_confidence_never_travels`) · `--no-text` 결과도 받는다.
- [ ] **Step 2–4.** — [ ] **Step 5: 커밋** — `v4 전달본 — 묶음 · 들어온 길 · 사례`

---

### Task 11: 대시보드

**Files:**
- Rewrite: `src/dashboard.py` (목표 600줄 이하)
- Modify: `tests/test_dashboard.py`

**Interfaces:**
- `load(path) -> pd.DataFrame` — `turns` 를 평평하게: `chat_id, turn, bucket, sure, stopped_at, because, where(문자열 " · " 결합), 부서, 직급, 직무, answered_by, ask_on, fallback, 앞 턴 누락, 질문에 개인정보, question, answer, followup, error`.
- 화면 다섯 절 (사이드바 필터: 묶음 · 확실/검토 · 부서/직급/직무):
  1. **분포** — 묶음 × 확실/검토 막대, `stopped_at` 건수.
  2. **어디서 막혔나** — review 의 `stopped_at` 상위 (기준문 고칠 곳).
  3. **조직별** — 축 하나 고르면 묶음 crosstab + 전체 대비 비율 (기존 `_by_org` 의 lift 로직은 묶음 열로).
  4. **근거 보강 목록** — bucket=근거 의 `question` 목록, `where` 와 함께 (코퍼스 보강 재료).
  5. **사례** — 한 턴 상세: verdict → steps 표(문장 · 답 · p) → flags → text (history · 네 칸은 접기).
- 검색은 `question` · `answer` · `followup` · `because` 에 대해.

- [ ] **Step 1: 테스트** — `load` 가 열을 만든다 · `--no-text` 결과도 연다 · 검색 토큰 "Q7Q" 가 `question` 에서 걸린다 (기존 검색 테스트 유지) · 조직 crosstab 열이 묶음 한국어 이름.
- [ ] **Step 2–4.** `python src/dashboard.py --help` 와 `streamlit` 없는 환경에서의 `_bail` 유지.
- [ ] **Step 5: 커밋** — `v4 대시보드 — 묶음 × 확실/검토, 어디서 막혔나`

---

### Task 12: 문서 · 설정 · 경계 테스트 · 전체 통과

**Files:**
- Rewrite: `docs/taxonomy.md` (묶음 표 · 네 단계 · 문항 표 · 플래그 — 설계 문서의 요약본), `docs/process_flow.md` (① ② 절은 유지, ③~⑦ 을 네 단계 절로 교체, "네 질문" 절은 네 단계 그림으로), README `## 처리 흐름` · 복사 목록 · 실행 표, `docs/design/README.md` 색인 (v3 두 문서는 "대체됨 — 기록" 으로), `todo/*.md` 중 v3 라벨을 가리키는 항목.
- Modify: `tests/test_boundary.py` CORE (`verify` `requests` `prompts` 제거), LOCAL_ONLY (`golden` 제거); `tests/test_spec_compliance.py` (문서 존재 · 라벨 어휘 대조 단언 갱신); `scripts/sync-allow.txt` (새 fixture 문구가 C9 에 걸리면 추가 — `bash scripts/sync.sh` 의 preflight 만 돌려 본다: 태그 인자 없이 거부되므로 preflight 함수를 직접 부르거나 임시 태그 이름으로 dry 체크. 방법은 `scripts/sync.sh` 를 읽고 정한다).
- Modify: `configs/env.example.yaml` 최종 정리, `src/ragdiag/contracts.py` 가 지운 것을 참조하면 수정.

- [ ] **Step 1: 문서를 쓴다.** 각 문서 머리에 "설계: docs/design/decision_tree_v4.md".
- [ ] **Step 2: 전체 테스트** — `venv/bin/pytest -q`. 전부 통과할 때까지 남은 깨짐을 고친다 (옛 테스트 중 v4 와 무관한 것은 지운다 — 각각 왜 지우는지 커밋 메시지에).
- [ ] **Step 3: 스모크** — `venv/bin/python src/run.py --dry-run` → 0; `venv/bin/python src/assemble.py example /tmp/x && …` 경로가 아직 도는지 (`tests/test_assemble.py` 가 본다).
- [ ] **Step 4: 커밋** — `v4 문서 · 설정 · 경계 — v3 흐름을 결정 트리로 바꿔 적는다`

---

## Self-review 메모

- 설계 문서 절 ↔ 태스크: 묶음(1) · 흐름/확신/모름(2,5,6,7) · 코드 확정(4) · 불만 판정/history 규칙(3,5) · 근거 판정(6) · 불만 부분(7) · 플래그(4) · 결과 파일(8) · 버리는 것(4,5,8) · fixture(9) · 설정·문서(2,12) · 전달본/대시보드(10,11) · eval.jsonl 계약(3). 미결(context 초과 · 2단계 태그)은 구현하지 않는다 — 의도.
- 이름 일치: `turn.close/review/is_open` (2) 를 4~7 이 쓰고, `StepResult.answers` 의 키는 id 이고 output(8) 만 문장으로 바꾼다. `questions.SLOTS` 의 한국어 이름을 evidence(6) · output(8) · handover(10) 가 공유한다.
- Review Focus 1~5 는 각각 Task 3 · 5 · 6 · 6 · 8 의 테스트에 있다.
