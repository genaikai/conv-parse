"""④′ 읽기 — 답변만 보고 "읽을 수 있는 글인가" 를 LLM 에 묻고, 아니면 case30 으로 끝낸다.

재는 것 셋: 답변만 준다(질문 · 불만 · 문서가 새면 "질문에 맞는 답인가" 를 재기
시작한다) · 인용이 원문과 안 맞으면 판정이 무효다 · 설정으로 끌 수 있다.
"""

from types import SimpleNamespace

import pytest

from ragdiag import prompts, settings
from ragdiag.features import legibility
from ragdiag.results import TurnResult
from ragdiag.schema import Case, LegibilityCheck

BROKEN = "연차는 입사일 기준 15일이며 ㅁㄴㅇㄹ 申請 the the the 승인을 받으면 ᄀᄁᄂ"


def _case(answer=BROKEN):
    return Case(case_id="c", user_id="-", dept="인사팀", job_grade="-", job_name="-",
                position_name="-", conversation_id="C", turn=2,
                pre_queries=["연차 며칠이에요"], llm_ans_on_last_q=answer,
                current_query="이게 뭔 말이에요", rag_chunks=["연차는 15일이다"])


class _Judge:
    def __init__(self, legible, quote=""):
        self.reply = LegibilityCheck(reasoning="r", quote=quote, legible=legible)
        self.calls = 0

    def check_legibility(self, case):
        self.calls += 1
        from ragdiag.backends import Usage
        return self.reply, Usage(input_tokens=1, output_tokens=1)


def _run(judge, answer=BROKEN):
    turn = TurnResult(case=_case(answer))
    ctx = SimpleNamespace(judge=judge, turns=[turn], workers=1, progress=False,
                          open_turns=lambda: [t for t in [turn] if t.classification is None])
    legibility.process_data(ctx)
    return turn


def test_the_prompt_gets_the_answer_and_nothing_else():
    case = _case()
    msg = prompts.legibility_user_message(case)
    assert case.llm_ans_on_last_q in msg
    for leaked in (case.pre_queries[0], case.current_query, case.rag_chunks[0], case.dept):
        assert leaked not in msg, leaked
    assert "유용한지" in prompts.LEGIBILITY_SYSTEM and "확신이 없으면 legible=true" in prompts.LEGIBILITY_SYSTEM


def test_illegible_with_a_real_quote_closes_the_turn_as_case30_medium():
    turn = _run(_Judge(legible=False, quote="ㅁㄴㅇㄹ 申請 the the the"))
    assert turn.classification.primary_case == "case30"
    assert turn.classification.confidence == "medium", "코드가 잡은 것(high)과 갈라야 한다"
    assert turn.legibility_quote.verified


def test_illegible_with_a_made_up_quote_is_void_and_the_turn_goes_on():
    """인용을 못 대면 판정이 무효다 - 이 판정이 틀리면 그 턴의 진짜 원인이 사라진다."""
    turn = _run(_Judge(legible=False, quote="지어낸 구절입니다"))
    assert turn.classification is None
    assert turn.legibility is not None and not turn.legibility_quote.verified


def test_legible_answers_go_on_untouched():
    judge = _Judge(legible=True)
    turn = _run(judge, answer="연차는 입사일 기준으로 매년 15일입니다.")
    assert judge.calls == 1 and turn.classification is None and turn.legibility.legible


def test_empty_answer_is_not_asked(monkeypatch):
    judge = _Judge(legible=False, quote="")
    turn = _run(judge, answer="   ")
    assert judge.calls == 0 and turn.legibility is None


def test_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "LEGIBILITY", False)
    judge = _Judge(legible=False, quote=BROKEN)
    turn = _run(judge)
    assert judge.calls == 0 and turn.classification is None


def test_config_key_reaches_the_setting(tmp_path, monkeypatch):
    from ragdiag.config import apply, load

    monkeypatch.setattr(settings, "LEGIBILITY", True)
    cfg = tmp_path / "c.yaml"
    cfg.write_text("run:\n  legibility: false\n", encoding="utf-8")
    apply(load(cfg))
    assert settings.LEGIBILITY is False


def test_output_carries_the_legibility_block():
    from ragdiag.output import _evidence_payload

    turn = _run(_Judge(legible=False, quote="지어낸 구절입니다"))
    ev = _evidence_payload(turn)
    assert ev["legibility"] == {"legible": False, "quote": "지어낸 구절입니다", "quote_verified": False}


def test_a_quote_from_inside_a_code_block_voids_the_judgment():
    """코드는 문법이 틀리거나 도중에 끝나도 붕괴가 아니다 - 코드 검증기의 일이다."""
    from ragdiag.features.legibility import inside_code_block

    answer = "```sql\nSELECT emp_no FROM trip_expense GROUP BY\n```"
    assert inside_code_block(answer, "SELECT emp_no FROM trip_expense GROUP BY")
    assert inside_code_block("```python\nprint(f\n", "print(f")           # 안 닫힌 펜스
    assert not inside_code_block("연차는 15일입니다. ㅁㄴㅇㄹ", "ㅁㄴㅇㄹ")

    turn = _run(_Judge(legible=False, quote="SELECT emp_no FROM trip_expense GROUP BY"), answer=answer)
    assert turn.classification is None and turn.legibility_quote.verified
