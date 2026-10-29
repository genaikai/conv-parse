"""코드 확정 — 규칙 셋, 처음 걸린 것이 시스템으로 닫는다."""

from ragdiag.features import code_rules
from ragdiag.features.code_rules import degenerate, empty_answer, service_error

from helpers import ctx, turn


def test_empty_answer_is_a_rule():
    assert empty_answer.check("  \n")[0] is True
    assert empty_answer.check("네")[0] is False


def test_the_three_rules_in_order():
    assert [r.NAME for r in code_rules.RULES] == ["service_error", "empty_answer", "degenerate"]


def test_first_hit_closes_as_system_and_later_rules_are_not_looked_at():
    c = ctx(turn(answer=""))
    code_rules.process_data(c)
    [t] = c.turns
    assert t.verdict.bucket == "system" and t.verdict.stopped_at == "코드 확정"
    assert t.verdict.because == "답변이 비어 있다 — 판정할 답이 없다"
    assert t.steps[0].step == "코드 확정"
    assert t.steps[0].rules == {"service_error": "아니오", "empty_answer": "예", "degenerate": "보지 않음"}


def test_clean_answer_leaves_the_turn_open_with_all_rules_recorded():
    c = ctx(turn(answer="연차는 15일입니다."))
    code_rules.process_data(c)
    [t] = c.turns
    assert t.is_open and set(t.steps[0].rules.values()) == {"아니오"}


def test_degenerate_still_catches_repeats():
    assert degenerate.check("5555555555555")[0] is True
    assert service_error.check("서비스에 문제가 있거나, 사용자 분들이 많아서 서버에 부하가 걸리고 있어요")[0] is True
