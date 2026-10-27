"""① 읽기 — 답변만 보고 "읽을 수 없는가" 를 결정 백엔드(kev)에 묻고, 확신이면 I2 로 끝낸다.

재는 것 셋: 답변만 준다(질문 · 불만 · 문서가 새면 "질문에 맞는 답인가" 를 재기 시작한다) ·
확신이 아니면 닫지 않고 p 만 남긴다 · 설정으로 끌 수 있다. 템플릿 토큰은 kev 없이 코드가 닫는다.
"""

from types import SimpleNamespace

from ragdiag import settings
from ragdiag.decide import ScriptedBackend
from ragdiag.features import legibility
from ragdiag.judge import Judge
from ragdiag.results import TurnResult
from ragdiag.schema import Case

BROKEN = "연차는 입사일 기준 15일이며 ㅁㄴㅇㄹ 申請 the the the 승인을 받으면 ᄀᄁᄂ"


def _case(answer=BROKEN):
    return Case(case_id="c", dept="인사팀", job_grade="-", job_name="-",
                chat_id="C", turn=2,
                pre_queries=["연차 며칠이에요"], llm_ans_on_last_q=answer,
                current_query="이게 뭔 말이에요", rag_chunks=["연차는 15일이다"])


class _Kev(ScriptedBackend):
    """P(읽을 수 없다) 를 정해 두고 무엇을 받았는지 기록한다."""

    def __init__(self, p):
        super().__init__(lambda state, q: {"illegible": p})
        self.states = []

    def decide(self, state, questions):
        self.states.append(state)
        return super().decide(state, questions)


def _run(kev, answer=BROKEN):
    turn = TurnResult(case=_case(answer))
    judge = Judge(None, cache_dir=None, decision=kev)
    ctx = SimpleNamespace(judge=judge, turns=[turn], workers=1, progress=False,
                          open_turns=lambda: [t for t in [turn] if t.classification is None])
    legibility.process_data(ctx)
    return turn


def test_the_state_gets_the_answer_and_nothing_else():
    kev = _Kev(0.1)
    case = _case()
    _run(kev)
    (state,) = kev.states
    assert state == {"답변": case.llm_ans_on_last_q}
    for leaked in (case.pre_queries[0], case.current_query, case.rag_chunks[0], case.dept):
        assert leaked not in str(state), leaked


def test_confident_illegible_closes_the_turn_as_I2_grade_2():
    turn = _run(_Kev(0.97))
    assert turn.classification.primary_case == "I2"
    assert turn.classification.grade == 2 and turn.classification.confidence == "medium", \
        "코드 규칙이 잡은 것(등급 4)과 갈라야 한다"
    assert turn.legibility_p == 0.97


def test_unsure_illegible_does_not_close_but_keeps_the_probability():
    """확신이 아니면 닫지 않는다 - 이 판정이 틀리면 그 턴의 진짜 원인이 사라진다."""
    turn = _run(_Kev(0.7))
    assert turn.classification is None
    assert turn.legibility_p == 0.7


def test_legible_answers_go_on_untouched():
    kev = _Kev(0.03)
    turn = _run(kev, answer="연차는 입사일 기준으로 매년 15일입니다.")
    assert len(kev.calls) == 1 and turn.classification is None and turn.legibility_p == 0.03


def test_empty_answer_is_not_asked():
    kev = _Kev(0.9)
    turn = _run(kev, answer="   ")
    assert kev.calls == [] and turn.legibility_p is None


def test_template_tokens_close_without_asking():
    """정상 답변에는 절대 없는 토큰이다 - 코드 확정(등급 4)이고 kev 를 부르지 않는다."""
    kev = _Kev(0.0)
    turn = _run(kev, answer="연차는 15일입니다.<|im_end|><|im_start|>assistant")
    assert kev.calls == [] and turn.classification.primary_case == "I2"
    assert turn.classification.grade == 4


def test_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "LEGIBILITY", False)
    kev = _Kev(0.99)
    turn = _run(kev)
    assert kev.calls == [] and turn.classification is None


def test_config_key_reaches_the_setting(tmp_path, monkeypatch):
    from ragdiag.config import apply, load

    monkeypatch.setattr(settings, "LEGIBILITY", True)
    cfg = tmp_path / "c.yaml"
    cfg.write_text("run:\n  legibility: false\n", encoding="utf-8")
    apply(load(cfg))
    assert settings.LEGIBILITY is False


def test_output_carries_the_legibility_block():
    from ragdiag.output import _evidence_payload

    turn = _run(_Kev(0.7))
    assert _evidence_payload(turn)["legibility"] == {"illegible_p": 0.7}
