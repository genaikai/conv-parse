"""판정 결과 모양 — 확신 읽기 · 닫기 · 검토."""

from ragdiag.decide import Answer
from ragdiag.results import TurnResult, answer_payload, read_choice, read_noul
from ragdiag.schema import Case


def _case() -> Case:
    return Case(case_id="c:2", dept="d", job_grade="g", job_name="j", chat_id="c", turn=2,
                pre_queries=["q"], llm_ans_on_last_q="a", current_query="그게 아니고요",
                rag_chunks=["청크"], chunk_sources=["retrieved"], n_fetched=1)


def test_noul_reads_three_ways():
    assert read_noul(Answer("noul", p=0.95)) == "예"
    assert read_noul(Answer("noul", p=0.05)) == "아니오"
    assert read_noul(Answer("noul", p=0.55)) == "모름"
    assert read_noul(Answer("noul", p=0.9)) == "예"        # 경계 포함
    assert read_noul(Answer("noul", p=0.1)) == "아니오"


def test_choice_needs_confident_mode():
    a = Answer("choice", p=0.92, choice="partial",
               probabilities={"all": 0.04, "partial": 0.92, "none": 0.04})
    assert read_choice(a) == "partial"
    assert read_choice(Answer("choice", p=0.6, choice="all", probabilities={"all": 0.6})) == "모름"
    assert answer_payload(a) == {"answer": "일부", "p": 0.92}
    assert answer_payload(Answer("noul", p=0.55)) == {"answer": "모름", "p": 0.55}


def test_close_and_review_set_the_verdict():
    t = TurnResult(case=_case())
    assert t.is_open
    t.review("불만 판정", "refusal", 0.55)
    assert t.verdict.bucket == "review" and not t.verdict.sure
    assert t.verdict.stopped_at == "불만 판정 · 정책·권한 거절이고 그걸 불평한다"
    assert "0.55" in t.verdict.because and t.verdict.where == []
    assert not t.is_open


def test_close_records_bucket_step_and_where():
    t = TurnResult(case=_case())
    t.close("generation", "근거 판정", "이유", where=["이번 턴 검색 청크"])
    assert (t.verdict.bucket, t.verdict.sure, t.verdict.stopped_at) == ("generation", True, "근거 판정")
    assert t.verdict.where == ["이번 턴 검색 청크"]


def test_an_errored_turn_is_not_open():
    t = TurnResult(case=_case())
    t.error = "[complaint] JudgeError: x"
    assert not t.is_open
