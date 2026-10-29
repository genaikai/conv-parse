"""플래그 열 — 판정에 안 끼어들고 멈추지 않는다."""

from ragdiag.features import integrity

from helpers import ctx, turn


def test_missing_prior_turns_flag():
    c = ctx(turn(history_present=True, history_turn_count=1, prior_turn_nos=[1, 2, 3]))
    integrity.process_data(c)
    [t] = c.turns
    assert t.flags["앞 턴 누락"] is True and t.is_open


def test_complete_history_is_not_flagged():
    c = ctx(turn(history_present=True, history_turn_count=2, prior_turn_nos=[1, 2, 3]))
    integrity.process_data(c)
    assert c.turns[0].flags["앞 턴 누락"] is False


def test_old_logs_do_not_judge_missing_turns():
    c = ctx(turn(history_present=False))
    integrity.process_data(c)
    assert c.turns[0].flags["앞 턴 누락"] == "옛 로그 — 판정 안 함"


def test_reconstruction_count_and_question_pii_are_columns():
    c = ctx(turn(history_reconstructed=2, pre_queries=["제 번호는 010-1234-5678 입니다"]))
    integrity.process_data(c)
    flags = c.turns[0].flags
    assert flags["history 재구성 턴 수"] == 2 and flags["질문에 개인정보"] is True
    assert set(flags) == {"앞 턴 누락", "history 재구성 턴 수", "질문에 개인정보"}
