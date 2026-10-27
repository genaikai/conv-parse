"""출력 빌더 테스트. pre_data_format 형태를 유지하는지 본다."""

import json

from ragdiag.conv import parse_conversations, to_case
from ragdiag.features.arbitrate import arbitrate
from ragdiag.output import build_output, summarize
from ragdiag.results import Check, ChunkSupport, Sufficiency, TurnResult
from tests.helpers import checks, obs, probs

RAW = {"users": [{
    "user_id": "EMP-원본", "db_login_id": "login1", "job_grade": "대리",
    "db_dept_name": "인사팀", "db_job_name": "인사운영", "db_position_name": "팀원",
    "conversations": [{"chat_id": "c1", "turns": [
        {"turn": 1, "user_question": "q1", "llm_response": "a1",
         "retrieved_data": json.dumps(["청크 A"])},
        {"turn": 2, "user_question": "q2", "llm_response": "a2",
         "retrieved_data": json.dumps(["청크 B"]),
         "llm_eval_result": "질의 킬로"},
    ]}],
}]}


def _insufficient(case, verified=True):
    return {"own": Sufficiency("own", "q", [ChunkSupport(0, 0.05, "retrieved")],
                               "insufficient", verified=verified)}


def _pairs():
    conv = parse_conversations(RAW)[0]
    case = to_case(conv, 2)
    result = TurnResult(case=case, observation=obs(), checks=checks(),
                        sufficiency=_insufficient(case), n_calls=2, n_kev_calls=5)
    result.probabilities.update(probs(complaint_target={"content_missing": 0.9}))
    arbitrate(result)
    return [(conv, result)]


def test_output_keeps_the_pre_data_format_shape():
    out = build_output(_pairs())
    assert list(out) == ["analysis_results"]
    user = out["analysis_results"][0]
    for key in ("job_grade", "db_dept_name", "db_job_name", "conversations"):
        assert key in user
    turn = user["conversations"][0]["turns"][0]
    for key in ("turn", "pre_queries", "llm_ans_on_last_q", "current_query", "chunk_data"):
        assert key in turn


def test_no_user_identifier_is_invented():
    """로그에 사용자 식별자가 없다 (2026-10). 없는 것을 빈 칸으로라도 내보내면 안 된다.

    출력은 원본 로그 옆에 놓여 조인에 쓰인다. 늘 비어 있는 user_id 칸이 있으면
    받는 쪽은 "이 사용자는 식별자가 없는 사용자" 로 읽고 그걸로 조인을 시도한다.
    되짚는 길은 chat_id 하나뿐이고, 그 값이 전역 유일이라 그걸로 족하다.
    """
    user = build_output(_pairs())["analysis_results"][0]
    assert not {"user_id", "user_id_hashed", "db_login_id",
                "db_position_name"} & set(user)
    assert user["conversations"][0]["chat_id"]


def test_classification_is_kept_in_its_own_block():
    """원본 필드와 섞으면 '이게 원본인가 우리가 붙인 건가'를 매번 확인해야 한다."""
    turn = build_output(_pairs())["analysis_results"][0]["conversations"][0]["turns"][0]
    assert set(turn) == {"turn", "pre_queries", "llm_ans_on_last_q",
                         "current_query", "chunk_data", "classification"}
    assert turn["classification"]["case_id"] == "D1"


def test_chunk_data_comes_from_the_answered_turn():
    turn = build_output(_pairs())["analysis_results"][0]["conversations"][0]["turns"][0]
    assert turn["chunk_data"] == ["청크 A"]      # turn 1 의 것
    assert turn["classification"]["answered_turn"] == 1


def test_not_applicable_checks_are_not_written_out():
    turn = build_output(_pairs())["analysis_results"][0]["conversations"][0]["turns"][0]
    written = turn["classification"]["evidence"].get("checks", [])
    assert all(c["verdict"] != "not_applicable" for c in written)


def test_violated_checks_are_written_out():
    conv, result = _pairs()[0]
    result.checks["arithmetic"] = Check("arithmetic", "violated", "3+4=8")
    turn = build_output([(conv, result)])["analysis_results"][0]["conversations"][0]["turns"][0]
    names = {c["name"] for c in turn["classification"]["evidence"]["checks"]}
    assert "arithmetic" in names


def test_failed_turn_records_the_error():
    conv = parse_conversations(RAW)[0]
    result = TurnResult(case=to_case(conv, 2), error="JudgeError: 연결 실패")
    turn = build_output([(conv, result)])["analysis_results"][0]["conversations"][0]["turns"][0]
    assert turn["classification"]["error"].startswith("JudgeError")


def test_failed_turn_names_the_step_it_died_in():
    """관측에서 몰려 깨지는 것과 흩어져 깨지는 것은 조치가 다르다.

    관측이면 프롬프트·토큰 쪽이고, 충족도에만 몰리면 청크가 길어서 잘리는 것이다.
    단계 이름이 없으면 실데이터 한 번 돌린 뒤 어디를 고칠지 정할 수 없다.
    """
    import sys
    from pathlib import Path

    from ragdiag.pipeline import judge_cases

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from stub_judge import ScriptedJudge, make_case

    def classify(scenario):
        return judge_cases([make_case(scenario)], ScriptedJudge(), workers=1, progress=False)[0]

    assert classify("rich|missing|sufficient|supported|fail-observe").error.startswith("[observe]")
    assert classify("rich|missing|sufficient|supported|fail-sufficiency").error.startswith("[sufficiency]")
    assert classify("rich|missing|sufficient|supported|fail-claims").error.startswith("[claims]")


def test_no_complaint_still_runs_every_stage_but_lands_on_N0():
    """v3 는 분기하지 않는다 - 불만이 없어도 충족도 · 주장을 돈다 (정확성 우선).

    관측 하나가 틀려도 내용 결함이 태그로 남고, 관측 오류가 교차 검증된다. 주 라벨은 N0 다.
    """
    import sys
    from pathlib import Path

    from ragdiag.pipeline import judge_cases

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from stub_judge import ScriptedJudge, make_case

    result = judge_cases([make_case("clean|none|sufficient|supported|ok")], ScriptedJudge(),
                         workers=1, progress=False)[0]
    assert result.classification.primary_case == "N0", result.classification
    assert result.sufficiency and result.claim_verdicts, "분기 없이 전부 돌아야 한다"


def test_output_is_json_serializable():
    json.dumps(build_output(_pairs()), ensure_ascii=False)


def test_summary_reports_label_group_and_grade():
    text = summarize(_pairs())
    assert "D1" in text and "검색 근거" in text and "3 근거 확정" in text
    assert "결정(kev) 호출 5회" in text


def test_sufficiency_carries_the_verified_flag_and_chunk_evidence():
    """화면이 읽는 것은 청크 단위 근거다 - 인용이 아니라 인덱스와 확률."""
    conv = parse_conversations(RAW)[0]
    case = to_case(conv, 2)
    result = TurnResult(
        case=case, observation=obs(), checks=checks(),
        sufficiency={"own": Sufficiency("own", "q", [ChunkSupport(0, 0.93, "retrieved")],
                                        "sufficient", verified=True)})
    arbitrate(result)
    suf = build_output([(conv, result)])["analysis_results"][0]["conversations"][0]["turns"][0][
        "classification"]["evidence"]["sufficiency"]
    assert suf["verdict"] == suf["final_verdict"] == "sufficient"
    assert suf["verified"] is True
    assert suf["evidence"] == [{"chunk_index": 0, "p": 0.93, "source": "retrieved", "scope": "own"}]
