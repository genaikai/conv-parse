"""결과 파일 모양 — 결론 · 이유 · 지나온 단계, 말로 쓴다."""

import json
from types import SimpleNamespace

import pytest

from ragdiag.output import build_output, build_turn, summarize, summary_of
from ragdiag.pipeline import judge_cases

from stub_judge import ScriptedJudge, make_case, scenarios

CONV = SimpleNamespace(chat_id="chat", user=SimpleNamespace(dept="부서", job_grade="직급", job_name="직무"))
RUN = {"started": "2026-10-29T10:00:00", "conv_data": "x.json", "kev": "scripted", "threshold": 0.9}


@pytest.fixture(scope="module")
def results():
    out = judge_cases([make_case(s) for s in scenarios()], ScriptedJudge(), workers=1,
                      progress=False)
    return {r.case.case_id.split(":")[1]: r for r in out}


def test_turn_keys_are_in_reading_order(results):
    turn = build_turn(results["generation-all"], CONV)
    assert list(turn) == ["chat_id", "turn", "event_time", "target_turn", "target_event_time",
                          "verdict", "steps", "flags", "axes", "text"]
    assert list(turn["verdict"]) == ["bucket", "sure", "stopped_at", "because", "where"]
    assert turn["verdict"]["bucket"] == "생성" and turn["verdict"]["sure"] is True
    assert turn["verdict"]["where"] == ["이번 턴 검색 청크"]
    assert (turn["turn"], turn["target_turn"]) == (2, 1)
    assert turn["event_time"] == "2026-10-21 09:02:00" and turn["target_event_time"] == "2026-10-21 09:01:00"


def test_answers_are_keyed_by_sentence_not_id(results):
    steps = build_turn(results["generation-all"], CONV)["steps"]
    assert [s["step"] for s in steps] == ["코드 확정", "불만 판정", "근거 판정"]
    assert "후속 발화가 답변을 문제 삼는다" in steps[1]["answers"] and "complains" not in steps[1]["answers"]
    assert steps[1]["answers"]["후속 발화가 답변을 문제 삼는다"] == {"answer": "예", "p": 0.95}
    assert steps[2]["answers"]["이번 턴 도구 결과에 답이 있다"] == "비어 있어 묻지 않음"
    assert steps[0]["rules"] == {"자원 부족 문구": "아니오", "빈 답변": "아니오", "붕괴": "아니오"}


def test_only_the_steps_that_ran_are_written(results):
    assert [s["step"] for s in build_turn(results["system-code"], CONV)["steps"]] == ["코드 확정"]
    assert [s["step"] for s in build_turn(results["partial-no"], CONV)["steps"]] == \
        ["코드 확정", "불만 판정", "근거 판정", "불만 부분 근거 판정"]


def test_review_turn_names_the_question_it_stopped_at(results):
    v = build_turn(results["review-complaint"], CONV)["verdict"]
    assert v["bucket"] == "검토" and v["sure"] is False
    assert v["stopped_at"] == "불만 판정 · 정책·권한 거절이고 그걸 불평한다"
    assert "0.55" in v["because"]


def test_flags_axes_and_text_blocks(results):
    turn = build_turn(results["normal"], CONV)
    assert turn["flags"] == {"앞 턴 누락": False, "history 재구성 턴 수": 0, "질문에 개인정보": False}
    assert turn["axes"] == {"부서": "부서", "직급": "직급", "직무": "직무",
                            "answered_by": "rag", "ask_on": "web", "fallback": ""}
    assert set(turn["text"]) == {"question", "answer", "followup", "history",
                                 "이번 턴 검색 청크", "이번 턴 도구 결과", "앞 턴 근거", "메모리"}


def test_no_text_drops_the_block(results):
    assert "text" not in build_turn(results["normal"], CONV, with_text=False)


def test_error_turn_has_only_identity_and_error(results):
    r = results["normal"]
    saved = r.error
    r.error = "[complaint] JudgeError: x"
    try:
        turn = build_turn(r, CONV)
    finally:
        r.error = saved
    assert set(turn) == {"chat_id", "turn", "event_time", "target_turn", "target_event_time", "error"}


def test_summary_counts_buckets_stops_and_review_questions(results):
    s = summary_of(list(results.values()))
    assert set(s["buckets"]) == {"정상", "사용자", "근거", "생성", "시스템", "검토"}
    assert sum(s["buckets"].values()) + s["errors"] == s["turns"] == len(results)
    assert s["buckets"] == {"정상": 1, "사용자": 1, "근거": 3, "생성": 3, "시스템": 2, "검토": 1}
    assert s["stopped_at"] == {"코드 확정": 1, "불만 판정": 5, "근거 판정": 3, "불만 부분 근거 판정": 2}
    assert s["review_at"] == {"불만 판정 · 정책·권한 거절이고 그걸 불평한다": 1}
    assert s["kev_calls"] == 1 + 1 + 1 + 1 + 1 + 2 + 2 + 3 + 3 + 1   # system-code 0, evidence-empty 1


def test_output_file_has_run_summary_turns_and_is_json(results):
    pairs = [(CONV, r) for r in results.values()]
    payload = build_output(pairs, RUN)
    assert list(payload) == ["run", "summary", "turns"]
    assert payload["run"] == RUN and len(payload["turns"]) == len(results)
    json.dumps(payload, ensure_ascii=False)
    text = summarize(pairs)
    assert "생성" in text and "검토" in text and all(len(line) <= 80 for line in text.splitlines())
