"""eval.jsonl 경로 — select · records 접기 · check · run.py 끝까지.

docs/assemble.md 의 계약을 그대로 잰다. 실 CSV 는 없으므로 ② 의 출력은 손으로 쓴
records.jsonl(pseudo_data/eval_jsonl) 과 테스트 안의 작은 사전이다.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ragdiag import assemble
from ragdiag.assemble import AssembleError, records_to_payload, select
from ragdiag.conv import parse_conversations
from ragdiag.filters import parse_filter
from ragdiag.fixtures import eval_jsonl as sample

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def SAMPLE(tmp_path_factory):
    """합성 네 파일. 저장소에는 코드만 있다 — 데이터 파일은 커밋하지 않는다."""
    folder = tmp_path_factory.mktemp("eval_jsonl")
    sample.write_example(folder)
    return folder
ORG = {"job_grade": "선임", "db_dept_name": "플랫폼개발팀", "db_job_name": "백엔드 개발"}


def ev(cid, turn, t, score=50.0, emo="중립", **extra):
    row = {"chat_id": cid, "turn": turn, "event_time": t, **ORG,
           "llm_eval_result": None, "llm_eval_score": None, "llm_eval_alternatives": [],
           "llm_emotion_result": emo, "llm_emotion_score": score,
           "llm_emotion_score_top1": score, "llm_emotion_alternatives": []}
    row.update(extra)
    return row


def spec(**state):
    return parse_filter({"name": "t", "state": state})


# ---------------------------------------------------------------------------
# ① select
# ---------------------------------------------------------------------------

def test_select_emits_coordinates_and_n_prior_only():
    rows = [ev("C1", 1, "t1"), ev("C1", 2, "t2", 85.0, "불만"), ev("C1", 3, "t3", 90.0, "불만")]
    out = select(rows, spec(emotion_range=[80, 100])).rows
    assert [(r["chat_id"], r["event_time"], r["target_event_time"], r["n_prior"]) for r in out] == [
        ("C1", "t2", "t1", 0), ("C1", "t3", "t2", 1)]
    # 본문 · 조직 · eval 은 싣지 않는다. 감정 판정만 따라간다
    assert set(out[0]) == {*assemble.SELECTED_KEYS, *assemble.EMOTION_KEYS}
    assert out[0]["llm_emotion_result"] == "불만"


def test_first_turn_is_never_a_candidate_even_with_high_score():
    rows = [ev("C1", 1, "t1", 99.0, "불만"), ev("C2", 1, "t1", 10.0), ev("C2", 2, "t2", 99.0, "불만")]
    out = select(rows, spec(emotion_range=[80, 100])).rows
    assert [r["chat_id"] for r in out] == ["C2"]


def test_followup_without_its_previous_turn_in_the_file_is_dropped():
    rows = [ev("C1", 3, "t3", 99.0, "불만")]          # 턴 2 가 파일에 없다
    result = select(rows, spec(emotion_range=[80, 100]))
    assert result.rows == []
    assert result.steps[0].dropped == 1


def test_eval_conditions_abort_before_anything_is_written():
    rows = [ev("C1", 1, "t1"), ev("C1", 2, "t2", 85.0, "불만")]
    with pytest.raises(AssembleError) as e:
        select(rows, spec(eval_range=[0, 50]))
    assert "아직 지원하지 않습니다" in str(e.value) and "eval_range" in str(e.value)
    with pytest.raises(AssembleError) as e:
        select(rows, spec(eval_labels=["A"]))
    assert "eval_labels" in str(e.value)


def test_org_and_date_conditions_apply_from_the_jsonl_rows():
    rows = [ev("C1", 1, "2026-10-01 09:00:00"), ev("C1", 2, "2026-10-01 09:05:00", 85.0, "불만"),
            ev("C2", 1, "2026-10-09 09:00:00"), ev("C2", 2, "2026-10-09 09:05:00", 85.0, "불만")]
    out = select(rows, spec(emotion_range=[80, 100], use_date=True,
                            start_date="2026-10-05", end_date="2026-10-31")).rows
    assert [r["chat_id"] for r in out] == ["C2"]
    out = select(rows, spec(org_tree={"db_dept_name": ["다른팀"]})).rows
    assert out == []


def test_duplicate_event_time_in_a_chat_is_warned_not_hidden():
    rows = [ev("C1", 1, "same"), ev("C1", 2, "same", 85.0, "불만")]
    result = select(rows, spec())
    assert any("겹치는" in w for w in result.warnings)


def test_select_report_lists_the_filter_steps():
    rows = [ev("C1", 1, "t1"), ev("C1", 2, "t2", 85.0, "불만")]
    report = select(rows, spec(emotion_range=[90, 100])).report
    assert "emotion_score" in report and "진단 가능 후속 턴" in report


# ---------------------------------------------------------------------------
# ③ records → payload
# ---------------------------------------------------------------------------

def rec(cid, t, **fields):
    return {"chat_id": cid, "event_time": t, **ORG, **fields}


def sel(cid, t, target, n_prior, **emotion):
    return {"chat_id": cid, "event_time": t, "target_event_time": target, "n_prior": n_prior, **emotion}


def test_turn_numbers_come_from_n_prior_and_missing_prior_turns_are_stubbed():
    selected = [sel("C1", "t3", "t2", 1, llm_emotion_result="불만", llm_emotion_score=88.0)]
    records = [rec("C1", "t2", user_question="q2", llm_response="a2"),
               rec("C1", "t3", user_question="q3")]
    payload = records_to_payload(records, selected)
    [conv] = parse_conversations(payload)
    assert conv.chat_id == "C1"
    assert [t.turn for t in conv.turns] == [1, 2, 3]
    assert conv.turn_at(1).user_question == ""                      # 자리만
    assert conv.turn_at(2).llm_response == "a2"
    assert conv.turn_at(3).user_question == "q3"
    assert conv.turn_at(3).emotion_result == "불만" and conv.turn_at(3).emotion_score == 88.0
    assert conv.user.dept == "플랫폼개발팀"
    # 턴 레코드에서 chat_id 는 대화 층으로 올라갔고, 앞 턴 자리는 계약 대조에서 빠진다
    turns = payload["users"][0]["conversations"][0]["turns"]
    assert "chat_id" not in turns[1] and turns[0].get(assemble.STUB_KEY) is True


def test_two_complaints_in_one_chat_share_one_conversation():
    selected = [sel("C1", "t2", "t1", 0), sel("C1", "t4", "t3", 2)]
    records = [rec("C1", "t1", user_question="q", llm_response="a"), rec("C1", "t2", user_question="q"),
               rec("C1", "t3", user_question="q", llm_response="a"), rec("C1", "t4", user_question="q")]
    [conv] = parse_conversations(records_to_payload(records, selected))
    assert [t.turn for t in conv.turns] == [1, 2, 3, 4]


@pytest.mark.parametrize("records, needle", [
    ([rec("C1", "t2", user_question="q")], "못 찾은 행"),                                   # t1 없음
    ([rec("C1", "t1", user_question="q", llm_response="a"), rec("C1", "t2", user_question="q"),
      rec("C1", "t9", user_question="q")], "더 넣은 행"),
    ([rec("C1", "t1", user_question="q", llm_response="a"), rec("C1", "t2", user_question="q"),
      rec("C1", "t2", user_question="q")], "행이 둘"),
    ([{"event_time": "t1"}, rec("C1", "t2", user_question="q")], "chat_id 나 event_time 이 없다"),
])
def test_mismatched_records_stop_with_a_sentence(records, needle):
    with pytest.raises(AssembleError) as e:
        records_to_payload(records, [sel("C1", "t2", "t1", 0)])
    assert needle in str(e.value)


def test_conflicting_n_prior_for_the_same_coordinate_stops():
    selected = [sel("C1", "t2", "t1", 0), sel("C1", "t3", "t2", 5)]     # t2 가 2번이면서 6번
    records = [rec("C1", "t1", user_question="q", llm_response="a"), rec("C1", "t2", user_question="q"),
               rec("C1", "t3", user_question="q")]
    with pytest.raises(AssembleError) as e:
        records_to_payload(records, selected)
    assert "턴 번호가 둘" in str(e.value)


def test_selected_row_missing_a_key_is_named():
    with pytest.raises(AssembleError) as e:
        records_to_payload([], [{"chat_id": "C1", "event_time": "t2"}])
    assert "target_event_time" in str(e.value) and "n_prior" in str(e.value)


# ---------------------------------------------------------------------------
# check · 샘플 파일 · CLI
# ---------------------------------------------------------------------------

def test_sample_files_pass_check_and_eval_keys_do_not_trip_the_contract(SAMPLE):
    selected = assemble.read_jsonl(SAMPLE / "selected.jsonl")
    records = assemble.read_jsonl(SAMPLE / "records.jsonl")
    assert assemble.check(selected, records) == []


def test_check_reports_contract_mismatches_as_sentences():
    selected = [sel("C1", "t2", "t1", 0)]
    records = [rec("C1", "t1", user_question="q", llm_response=42), rec("C1", "t2", user_question="q")]
    problems = assemble.check(selected, records)
    assert any("llm_response" in p for p in problems)


def test_sample_select_reproduces_the_fixture_selected_rows(SAMPLE, tmp_path):
    rows = assemble.read_jsonl(SAMPLE / "eval.jsonl")
    spec_ = parse_filter(json.loads((SAMPLE / "filter.json").read_text(encoding="utf-8")))
    assert select(rows, spec_).rows == sample.SELECTED_ROWS


def _run(*argv):
    return subprocess.run([sys.executable, *argv], cwd=ROOT, capture_output=True, text=True)


def test_cli_select_and_check_and_run_dry_run(SAMPLE, tmp_path):
    out = tmp_path / "selected.jsonl"
    r = _run("src/assemble.py", "select", "--eval-jsonl", str(SAMPLE / "eval.jsonl"),
             "--filter-data", str(SAMPLE / "filter.json"), "--out", str(out))
    assert r.returncode == 0, r.stderr
    assert "2건" in r.stderr

    r = _run("src/assemble.py", "check", str(out), str(SAMPLE / "records.jsonl"))
    assert r.returncode == 0, r.stderr
    assert "통과" in r.stderr

    r = _run("src/run.py", "--conv-data", str(SAMPLE / "records.jsonl"), "--turns", str(out),
             "--dry-run", "--output-dir", str(tmp_path / "out"))
    assert r.returncode == 0, r.stderr + r.stdout
    assert "selected 2 turns" in r.stdout
    assert "MISMATCH" not in r.stdout
    assert "C-0002:3" in r.stderr


def test_cli_select_aborts_on_eval_condition(SAMPLE, tmp_path):
    f = tmp_path / "filter.json"
    f.write_text(json.dumps({"state": {"eval_range": [0, 40]}}), encoding="utf-8")
    r = _run("src/assemble.py", "select", "--eval-jsonl", str(SAMPLE / "eval.jsonl"),
             "--filter-data", str(f), "--out", str(tmp_path / "s.jsonl"))
    assert r.returncode == 2
    assert "아직 지원하지 않습니다" in r.stderr
    assert not (tmp_path / "s.jsonl").exists()


def test_run_refuses_records_without_selected(SAMPLE, tmp_path):
    r = _run("src/run.py", "--conv-data", str(SAMPLE / "records.jsonl"), "--dry-run",
             "--output-dir", str(tmp_path))
    assert r.returncode == 2
    assert "--turns" in r.stderr


def test_run_stops_when_records_and_selected_disagree(SAMPLE, tmp_path):
    bad = tmp_path / "selected.jsonl"
    bad.write_text(json.dumps(sel("C-0001", "없는시각", "2026-10-20 09:10:01", 0)) + "\n", encoding="utf-8")
    r = _run("src/run.py", "--conv-data", str(SAMPLE / "records.jsonl"), "--turns", str(bad),
             "--dry-run", "--output-dir", str(tmp_path))
    assert r.returncode == 2
    assert "못 찾은 행" in r.stderr


def test_example_command_writes_the_four_files(tmp_path):
    r = _run("src/assemble.py", "example", str(tmp_path / "ex"))
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in (tmp_path / "ex").iterdir()) == [
        "eval.jsonl", "filter.json", "records.jsonl", "selected.jsonl"]


def test_prior_turn_rows_with_a_turn_number_fill_the_stubs():
    """history_input 이 빈 답변 턴은 ② 가 앞 3턴 본문도 넣는다 — turn 번호를 달고."""
    selected = [sel("C1", "t5", "t4", 3)]
    records = [rec("C1", "t4", user_question="q4", llm_response="a4"),
               rec("C1", "t5", user_question="q5"),
               rec("C1", "t3", turn=3, user_question="q3", llm_response="a3"),
               rec("C1", "t2", turn=2, user_question="q2", llm_response="a2")]
    [conv] = parse_conversations(records_to_payload(records, selected))
    assert [t.turn for t in conv.turns] == [1, 2, 3, 4, 5]
    assert conv.turn_at(3).llm_response == "a3" and conv.turn_at(1).user_question == ""
    turns = records_to_payload(records, selected)["users"][0]["conversations"][0]["turns"]
    assert turns[2].get(assemble.STUB_KEY) is None and turns[0].get(assemble.STUB_KEY) is True


def test_prior_turn_row_beyond_n_prior_stops():
    selected = [sel("C1", "t3", "t2", 1)]
    records = [rec("C1", "t2", user_question="q2", llm_response="a2"),
               rec("C1", "t3", user_question="q3"),
               rec("C1", "t9", turn=7, user_question="q7")]
    with pytest.raises(AssembleError) as e:
        records_to_payload(records, selected)
    assert "turn 7" in str(e.value) and "n_prior" in str(e.value)


def test_request_time_rows_are_selected_and_written_as_event_time():
    """eval.jsonl 이 request_time 으로 와도 고르고, selected 에는 event_time 으로 쓴다 (② 가 보는 이름 하나)."""
    rows = [ev("C1", 1, "t1"), ev("C1", 2, "t2", score=90.0, emo="불만")]
    for r in rows:
        r["request_time"] = r.pop("event_time")
    out = select(rows, spec(emotion_labels=["불만"])).rows
    assert [(r["event_time"], r["target_event_time"]) for r in out] == [("t2", "t1")]


def test_records_may_carry_request_time_instead_of_event_time():
    selected = [sel("C1", "t2", "t1", 0)]
    records = [{"chat_id": "C1", "request_time": "t1", **ORG, "user_question": "q1", "llm_response": "a1"},
               {"chat_id": "C1", "request_time": "t2", **ORG, "user_question": "q2"}]
    [conv] = parse_conversations(records_to_payload(records, selected))
    assert [t.turn for t in conv.turns] == [1, 2]
    assert conv.turn_at(1).event_time == "t1" and conv.turn_at(2).user_question == "q2"
