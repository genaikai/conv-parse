"""불만 판정 — kev 8문항 한 요청, 코드가 순서로 읽는다."""

import pytest

from ragdiag import taxonomy
from ragdiag.decide import ScriptedBackend
from ragdiag.features import complaint
from ragdiag.judge import Judge

from helpers import case, ctx, turn


def _run(script: dict, capture: list | None = None, **case_kw):
    backend = ScriptedBackend(lambda state, questions: script)
    judge = Judge(backend=None, cache_dir=None, decision=backend)
    c = ctx(turn(case=case(**case_kw)), judge=judge)
    complaint.process_data(c)
    if capture is not None:
        capture.extend(backend.calls)
    return c.turns[0]


def test_no_complaint_is_normal_even_if_later_questions_say_yes():
    t = _run({"complains": False, "illegible": True})
    assert t.verdict.bucket == "normal" and t.verdict.stopped_at == "불만 판정"
    assert t.verdict.because == taxonomy.BECAUSE["불만 판정:complains:no"]
    step = t.steps[-1]
    assert step.step == "불만 판정" and step.answers["illegible"]["answer"] == "예"   # 여덟 전부 실린다
    assert len(step.answers) == 8


@pytest.mark.parametrize("qid,bucket", [("refusal", "system"), ("illegible", "system"),
                                        ("truncated", "system"), ("language", "generation"),
                                        ("emotion_only", "user"), ("new_demand", "user"),
                                        ("no_doc", "generation")])
def test_each_yes_exit(qid, bucket):
    t = _run({"complains": True, qid: True})
    assert t.verdict.bucket == bucket
    assert t.verdict.because == taxonomy.BECAUSE[f"불만 판정:{qid}:yes"]
    assert t.verdict.sure and t.verdict.stopped_at == "불만 판정"


def test_earlier_yes_wins_over_later_yes():
    t = _run({"complains": True, "truncated": True, "no_doc": True})
    assert t.verdict.bucket == "system"


def test_all_no_leaves_the_turn_open_for_evidence():
    t = _run({"complains": True})
    assert t.is_open and t.steps[-1].step == "불만 판정"


def test_unsure_stops_at_that_question():
    t = _run({"complains": True, "refusal": 0.55, "no_doc": True})
    assert t.verdict.bucket == "review" and not t.verdict.sure
    assert t.verdict.stopped_at == "불만 판정 · 정책·권한 거절이고 그걸 불평한다"
    assert t.steps[-1].answers["refusal"] == {"answer": "모름", "p": 0.55}


def test_state_has_history_and_no_documents():
    calls = []
    _run({"complains": False}, calls, history_messages=[{"role": "user", "content": "q0"}],
         llm_ans_on_last_q="답", current_query="아니요")
    [(state, qids)] = calls
    assert set(state) == {"history", "question", "answer", "followup"}
    assert state["history"] == [{"role": "user", "content": "q0"}]
    assert state["question"] == "q" and state["answer"] == "답" and state["followup"] == "아니요"
    assert qids == list(complaint.questions.COMPLAINT)


def test_one_kev_call_per_turn():
    t = _run({"complains": True})
    assert t.n_kev_calls == 1 and t.n_calls == 0
