"""불만 부분 근거 판정 — 근거가 일부일 때만. 불만이 가리키는 부분이 근거에 있었나."""

from ragdiag.decide import ScriptedBackend
from ragdiag.features import complaint_evidence, evidence
from ragdiag.judge import Judge

from helpers import case, ctx, turn


def _run(script: dict, capture: list | None = None, *, run_evidence_first: bool = False):
    backend = ScriptedBackend(lambda state, questions: script)
    judge = Judge(backend=None, cache_dir=None, decision=backend)
    c = ctx(turn(case=case(rag_chunks=["청크"], chunk_sources=["retrieved"],
                           current_query="부서를 물었는데요")), judge=judge)
    if run_evidence_first:
        evidence.process_data(c)
    complaint_evidence.process_data(c)
    if capture is not None:
        capture.extend(backend.calls)
    return c.turns[0]


def test_yes_means_generation():
    t = _run({"targeted": True})
    assert t.verdict.bucket == "generation" and t.verdict.stopped_at == "불만 부분 근거 판정"
    assert t.verdict.because == "근거가 일부였지만 불만이 가리키는 부분은 근거에 있었다"
    assert t.steps[-1].answers == {"targeted": {"answer": "예", "p": 0.95}}


def test_no_means_evidence():
    t = _run({"targeted": False})
    assert t.verdict.bucket == "evidence"
    assert t.verdict.because == "근거가 일부였고 불만이 가리키는 부분이 근거에 없었다"


def test_unsure_is_review():
    t = _run({"targeted": 0.5})
    assert t.verdict.bucket == "review"
    assert t.verdict.stopped_at == "불만 부분 근거 판정 · 불만이 가리키는 부분에 답이 근거에 있다"


def test_state_has_followup_and_slots_but_no_answer():
    calls = []
    _run({"targeted": True}, calls)
    [(state, qids)] = calls
    assert qids == ["targeted"]
    assert set(state) == {"question", "followup", "이번 턴 검색 청크"}
    assert "answer" not in state and state["followup"] == "부서를 물었는데요"


def test_a_turn_evidence_closed_is_not_asked_again():
    t = _run({"in_retrieved": True, "any": "all", "targeted": False}, run_evidence_first=True)
    assert t.verdict.bucket == "generation" and t.n_kev_calls == 1


def test_a_partial_turn_goes_on_to_this_step():
    t = _run({"in_retrieved": True, "any": "partial", "targeted": False}, run_evidence_first=True)
    assert t.verdict.bucket == "evidence" and t.n_kev_calls == 2
    assert [s.step for s in t.steps] == ["근거 판정", "불만 부분 근거 판정"]


def test_where_comes_from_the_evidence_step():
    """근거 판정을 지난 턴이라 where 가 있어야 한다 — 근거면 빈 칸 · 아니오 칸, 생성이면 예 칸."""
    t = _run({"in_retrieved": True, "any": "partial", "targeted": False}, run_evidence_first=True)
    assert t.verdict.where == ["이번 턴 도구 결과", "앞 턴 근거", "메모리"]
    t = _run({"in_retrieved": True, "any": "partial", "targeted": True}, run_evidence_first=True)
    assert t.verdict.where == ["이번 턴 검색 청크"]
