"""기울기 통과 — 불만 판정 2~8 의 "아니오 → 다음" 은 기울기만 본다 (설계 "모름 줄이기")."""

import pytest

from ragdiag import settings, taxonomy
from ragdiag.decide import Answer, ScriptedBackend
from ragdiag.features import complaint, integrity
from ragdiag.judge import Judge
from ragdiag.results import LEAN_NO, answer_payload, read_gate

from helpers import case, ctx, turn


def _run(script: dict):
    judge = Judge(backend=None, cache_dir=None,
                  decision=ScriptedBackend(lambda state, questions: script))
    c = ctx(turn(case=case()), judge=judge)
    integrity.process_data(c)
    complaint.process_data(c)
    return c.turns[0]


def test_gate_reads_four_ways():
    assert read_gate(Answer("noul", p=0.95)) == "예"
    assert read_gate(Answer("noul", p=0.05)) == "아니오"
    assert read_gate(Answer("noul", p=0.3)) == LEAN_NO
    assert read_gate(Answer("noul", p=0.5)) == LEAN_NO          # 경계 포함
    assert read_gate(Answer("noul", p=0.7)) == "모름"           # 결론 쪽으로 기울면 여전히 모름
    assert read_gate(Answer("noul", p=0.501)) == "모름"


def test_lean_payload_shows_the_confidence_of_no_and_the_word():
    assert answer_payload(Answer("noul", p=0.3), reader=read_gate) == {"answer": LEAN_NO, "p": 0.7}
    assert answer_payload(Answer("noul", p=0.3)) == {"answer": "모름", "p": 0.3}


def test_lean_no_passes_to_the_next_question_and_is_counted():
    t = _run({"complains": True, "refusal": 0.3, "emotion_only": 0.45, "no_doc": True})
    assert t.verdict.bucket == "generation"
    assert t.verdict.because == taxonomy.BECAUSE["불만 판정:no_doc:yes"] and t.verdict.sure
    assert t.steps[-1].answers["refusal"] == {"answer": LEAN_NO, "p": 0.7}
    assert t.flags[integrity.LEAN] == 2


def test_leaning_yes_still_stops():
    t = _run({"complains": True, "refusal": 0.7, "no_doc": True})
    assert t.verdict.bucket == "review"
    assert t.verdict.stopped_at == "불만 판정 · 정책·권한 거절이고 그걸 불평한다"
    assert t.flags[integrity.LEAN] == 0


def test_first_question_stays_symmetric():
    t = _run({"complains": 0.3})
    assert t.verdict.bucket == "review"
    assert t.verdict.stopped_at == "불만 판정 · 후속 발화가 답변을 문제 삼는다"
    assert t.steps[-1].answers["complains"] == {"answer": "모름", "p": 0.3}


def test_lean_count_only_counts_questions_passed_before_the_stop():
    t = _run({"complains": True, "refusal": 0.3, "truncated": 0.7, "no_doc": 0.4})
    assert t.verdict.bucket == "review" and t.flags[integrity.LEAN] == 1


def test_gate_is_only_for_questions_whose_no_goes_on():
    from ragdiag import questions
    for qid, (on_yes, on_no) in questions.COMPLAINT_ROUTE.items():
        if qid != "complains":
            assert on_no is None, qid


def test_pass_through_is_a_setting(restore_lean):
    settings.KEV_PASS_THROUGH = 0.3
    assert read_gate(Answer("noul", p=0.4)) == "모름"
    assert read_gate(Answer("noul", p=0.3)) == LEAN_NO


@pytest.fixture
def restore_lean():
    saved = settings.KEV_PASS_THROUGH
    yield
    settings.KEV_PASS_THROUGH = saved
