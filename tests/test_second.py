"""2차 판정 (LLM) — kev 가 모름이라 한 문항 하나를 일반 LLM 에 다시 묻는다 (설계 "모름 줄이기")."""

import pytest

from ragdiag import second, settings, taxonomy
from ragdiag.backends import Usage
from ragdiag.decide import ScriptedBackend
from ragdiag.features import complaint, complaint_evidence, evidence, integrity
from ragdiag.judge import Judge

from helpers import case, ctx, turn


class ScriptedLLM:
    """문항 id → 답. 적지 않은 문항은 모름. 받은 프롬프트를 남긴다."""

    model = "llm-test"

    def __init__(self, answers: dict | None = None, reasoning: str = "앞 질문에 없던 요구다"):
        self.answers = answers or {}
        self.reasoning = reasoning
        self.calls: list[tuple[str, str]] = []

    def complete(self, system, user, out_model, hint=""):
        self.calls.append((system, user))
        qid = next(q for q in self.answers if f"[{q}]" in user) if any(f"[{q}]" in user for q in self.answers) else None
        answer = self.answers.get(qid, "모름")
        return out_model(reasoning=self.reasoning, answer=answer), Usage(7, 3)


def _run(kev: dict, llm: ScriptedLLM | None, *features, **case_kw):
    judge = Judge(backend=llm, cache_dir=None,
                  decision=ScriptedBackend(lambda state, questions: kev))
    c = ctx(turn(case=case(**case_kw)), judge=judge)
    for f in (integrity, *features):
        f.process_data(c)
    return c.turns[0]


# --- 모양 -------------------------------------------------------------------

def test_model_offers_the_question_choices_plus_unsure():
    from ragdiag import questions
    noul = second.build_model(questions.COMPLAINT["refusal"])
    assert noul.model_fields["answer"].annotation.__args__ == ("예", "아니오", "모름")
    assert list(noul.model_fields) == ["reasoning", "answer"]
    pick = second.build_model(questions.EVIDENCE_ANY["any"])
    assert pick.model_fields["answer"].annotation.__args__ == ("all", "partial", "none", "모름")


def test_prompt_carries_the_state_the_question_and_the_kev_p():
    from ragdiag import questions
    text = second.user_text({"question": "식비 상한?", "answer": "규정에 따릅니다"}, "refusal",
                            questions.COMPLAINT["refusal"], 0.62)
    assert "[refusal]" in text and "식비 상한?" in text and "0.62" in text
    assert questions.COMPLAINT["refusal"]["instructions"][:20] in text


# --- 불만 판정 -----------------------------------------------------------------

def test_llm_yes_closes_the_turn_but_not_as_sure():
    llm = ScriptedLLM({"refusal": "예"})
    t = _run({"complains": True, "refusal": 0.7}, llm, complaint)
    assert t.verdict.bucket == "system" and t.verdict.sure is False
    assert t.verdict.because == taxonomy.BECAUSE["불만 판정:refusal:yes"]
    assert t.verdict.stopped_at == "불만 판정"
    assert t.verdict.second_pass == "불만 판정 · 정책·권한 거절이고 그걸 불평한다 — kev p 0.70, LLM 예"
    assert [s.step for s in t.steps] == ["불만 판정", "2차 판정 (LLM)"]
    assert t.steps[-1].answers == {"refusal": {"kev_p": 0.7, "answer": "예", "이유": "앞 질문에 없던 요구다"}}
    assert t.n_calls == 1 and t.n_kev_calls == 1


def test_llm_no_continues_the_tree():
    llm = ScriptedLLM({"new_demand": "아니오"})
    t = _run({"complains": True, "new_demand": 0.62, "no_doc": True}, llm, complaint)
    assert t.verdict.bucket == "generation" and t.verdict.sure is False
    assert t.verdict.because == taxonomy.BECAUSE["불만 판정:no_doc:yes"]
    assert "LLM 아니오" in t.verdict.second_pass


def test_llm_no_can_leave_the_turn_open_for_evidence():
    llm = ScriptedLLM({"new_demand": "아니오"})
    t = _run({"complains": True, "new_demand": 0.62}, llm, complaint)
    assert t.is_open and t.second and t.steps[-1].step == "2차 판정 (LLM)"


def test_llm_unsure_is_review_with_the_record():
    llm = ScriptedLLM({})
    t = _run({"complains": True, "refusal": 0.7}, llm, complaint)
    assert t.verdict.bucket == "review" and t.verdict.sure is False
    assert t.verdict.stopped_at == "불만 판정 · 정책·권한 거절이고 그걸 불평한다"
    assert t.verdict.second_pass.endswith("LLM 모름")
    assert t.steps[-1].answers["refusal"]["answer"] == "모름"


def test_a_second_unsure_in_the_same_turn_is_asked_again():
    llm = ScriptedLLM({"refusal": "아니오", "truncated": "예"})
    t = _run({"complains": True, "refusal": 0.7, "truncated": 0.8}, llm, complaint)
    assert t.verdict.bucket == "system" and t.n_calls == 2
    assert [s.step for s in t.steps] == ["불만 판정", "2차 판정 (LLM)", "2차 판정 (LLM)"]
    assert " / " in t.verdict.second_pass


def test_no_llm_backend_means_review_as_before():
    t = _run({"complains": True, "refusal": 0.7}, None, complaint)
    assert t.verdict.bucket == "review" and t.verdict.second_pass == "" and not t.second


def test_switch_off(restore_second):
    settings.SECOND_PASS = False
    t = _run({"complains": True, "refusal": 0.7}, ScriptedLLM({"refusal": "예"}), complaint)
    assert t.verdict.bucket == "review" and t.n_calls == 0


# --- 근거 판정 · 불만 부분 ---------------------------------------------------------

def test_evidence_choice_is_asked_with_the_options():
    llm = ScriptedLLM({"any": "none"})
    t = _run({"complains": True, "in_retrieved": False,
              "any": {"all": 0.5, "partial": 0.45, "none": 0.05}}, llm, complaint, evidence)
    assert t.verdict.bucket == "evidence" and t.verdict.sure is False
    assert t.verdict.because == taxonomy.BECAUSE["근거 판정:any:none"]
    assert t.steps[-1].answers["any"]["answer"] == "없음"
    assert "LLM 없음" in t.verdict.second_pass


def test_evidence_partial_from_llm_goes_on_to_the_last_step():
    llm = ScriptedLLM({"any": "partial", "targeted": "예"})
    t = _run({"complains": True, "in_retrieved": True, "targeted": 0.6,
              "any": {"all": 0.5, "partial": 0.45, "none": 0.05}}, llm, complaint, evidence,
             complaint_evidence)
    assert t.verdict.bucket == "generation" and t.verdict.sure is False
    assert t.n_calls == 2 and t.n_kev_calls == 3
    assert t.verdict.where == ["이번 턴 검색 청크"]


@pytest.fixture
def restore_second():
    saved = settings.SECOND_PASS
    yield
    settings.SECOND_PASS = saved
