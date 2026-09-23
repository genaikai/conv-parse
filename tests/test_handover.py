"""실무 전달본이 약속한 모양을 지키는지.

이 파일이 지키는 약속은 넷이다. 넷 다 실무가 **잘못 읽으면 엉뚱한 곳을 고치게 되는**
것들이라 조용히 깨지면 안 된다.

  - 청크 전문이 아니라 인용 대조를 통과한 구절만 싣는다
  - 신뢰도 등급을 싣지 않는다
  - 정상 턴(case0)은 빼고, 미분류는 맨 뒤에 따로 싣는다
  - 사유에 내부 용어가 없다
"""

from __future__ import annotations

import json

import pytest

from ragdiag.features import handover


def turn(case_id, *, case_name="이름", type_id="TYPE5", type_name="검색 문제",
         evidence=None, secondary=None, notes=None, chunks=None):
    return {
        "turn": 3,
        "pre_queries": ["앞 질문", "국내 출장 식비 상한은?"],
        "llm_ans_on_last_q": "규정에 따라 지급됩니다.",
        "current_query": "그러니까 얼마냐고요",
        "chunk_data": chunks if chunks is not None else ["청크 전문 " * 40],
        "classification": {
            "case_id": case_id, "case_name": case_name,
            "type_id": type_id, "type_name": type_name,
            "category": "category_2", "confidence": "high",
            "reason": "가져온 문서가 요구를 충족하지 못함 (verdict=insufficient)",
            "secondary_cases": secondary or [],
            "notes": notes or [],
            "evidence": evidence or {},
            "llm_calls": 3,
        },
    }


def result(*turns):
    return {"analysis_results": [{
        "user_id": "u1", "db_dept_name": "해외영업팀",
        "conversations": [{"conversation_id": "C-1", "turns": list(turns)}],
    }]}


SUFFICIENCY = {
    "sufficiency": {
        "verdict": "sufficient", "final_verdict": "sufficient", "missing": "",
        "evidence": [{"chunk_index": 0, "quote": "국내 출장 식비는 1일 3만원을 상한으로 한다.",
                      "ratio": 1.0}],
        # 대조에 떨어진 것. 판정에 안 쓰였으므로 전달본에도 실리면 안 된다.
        "dropped_evidence": [{"quote": "지어낸 구절", "reason": "원문 없음"}],
    },
    "observation": {"unmet_need": "국내 출장 식비 상한 금액",
                    "complaint_quote": "그러니까 얼마냐고요"},
}


# ---------------------------------------------------------------------------
# 문서를 추리는 규칙
# ---------------------------------------------------------------------------

def test_only_verified_quotes_travel_not_whole_chunks():
    """청크 전문을 통째로 주면 어느 것이 문제인지 도로 찾아야 한다."""
    out = handover.build(result(turn("case22", evidence=SUFFICIENCY)))
    example = out["분류"][0]["세부"][0]["사례"][0]
    assert example["분석"]["문서"]["구절"] == [
        {"문서번호": 0, "구절": "국내 출장 식비는 1일 3만원을 상한으로 한다."}]
    assert "청크 전문" not in json.dumps(out, ensure_ascii=False)


def test_dropped_citations_do_not_travel():
    """대조에 떨어진 인용은 판정에도 안 쓰였다. 실무에 보내면 없는 근거를 믿게 된다."""
    out = handover.build(result(turn("case22", evidence=SUFFICIENCY)))
    assert "지어낸 구절" not in json.dumps(out, ensure_ascii=False)


@pytest.mark.parametrize("case_id,kind", [
    ("case22", "활용했어야_할_문서"),
    ("case18", "답변과_어긋나는_문서"),
    ("case17", "활용한_문서"),
])
def test_the_document_says_why_it_is_there(case_id, kind):
    """같은 인용이라도 case 마다 읽는 법이 다르다.

    다만 **키 이름으로 가르지 않는다** - 받아 쓰는 쪽이 네 이름을 다 알고 하나씩
    있는지 봐야 한다. 키는 언제나 `문서` 고, 어떻게 읽을지는 `성격` 이 말한다.
    """
    out = handover.build(result(turn(case_id, evidence=SUFFICIENCY)))
    document = out["분류"][0]["세부"][0]["사례"][0]["분석"]["문서"]
    assert document["성격"] == kind
    assert document["설명"]


@pytest.mark.parametrize("case_id", ["case20", "case21"])
def test_retrieval_failures_carry_what_was_missing_not_documents(case_id):
    """쓸 문서가 없다는 것이 결론이다. 문서 칸을 두면 빈 배열만 남아 혼란스럽다."""
    evidence = {"sufficiency": {"verdict": "insufficient", "final_verdict": "insufficient",
                                "missing": "협력사 출입증 신규 발급 소요일", "evidence": []},
                "observation": {"unmet_need": "발급 소요일"}}
    out = handover.build(result(turn(case_id, evidence=evidence)))
    document = out["분류"][0]["세부"][0]["사례"][0]["분석"]["문서"]
    assert document["성격"] == "문서에_없던_것"
    assert document["없던_내용"] == "협력사 출입증 신규 발급 소요일"
    assert document["구절"] == []


# ---------------------------------------------------------------------------
# 담지 않기로 한 것
# ---------------------------------------------------------------------------

def test_confidence_never_travels():
    """실무가 쓸 기준이 아니다. case 마다 뜻이 달라서 같은 무게로 읽으면 틀린다."""
    out = handover.build(result(turn("case22", evidence=SUFFICIENCY)))
    dumped = json.dumps(out, ensure_ascii=False)
    assert "confidence" not in dumped and "신뢰도" not in dumped


def test_normal_turns_are_left_out_but_counted():
    """case0 은 챗봇 지표가 아니라 필터 지표다. 빼되 몇 건인지는 남긴다."""
    out = handover.build(result(turn("case0", type_id="TYPE0"),
                                turn("case22", evidence=SUFFICIENCY)))
    assert out["대상"] == {"로그": "", "분석한 턴": 2, "실패로 판정": 1, "정상으로 판정": 1}
    assert all(g["type"] != "TYPE0" for g in out["분류"])


def test_unclassified_is_shown_at_the_end_not_hidden():
    """숨기면 실패 건수가 줄어 보이고, 원본과 대조할 때 신뢰를 잃는다."""
    out = handover.build(result(turn("unclassified", type_id="", type_name="")))
    assert out["분류"] == []
    assert out["미분류"]["건수"] == 1
    example = out["미분류"]["사례"][0]
    assert example["분석"]["사유"]["요약"]
    # 모양이 다른 사례를 만들지 않는다. 어느 쪽 미분류인지도 meta_data 안이다.
    assert list(example)[-1] == "분석"
    # case 칸에 이미 id 가 있다. 같은 말을 두 번 담지 않는다.
    assert example["분석"]["meta_data"]["구분"] == "분류 실패 (수동 검토 대상)"
    assert example["분석"]["meta_data"]["case"] == "unclassified"
    assert list(out)[-1] == "미분류"


def test_internal_wording_does_not_reach_the_reader():
    """'verdict=insufficient' 같은 말은 읽는 사람이 모르는 용어다."""
    out = handover.build(result(turn("case20", evidence={
        "sufficiency": {"missing": "없던 것", "evidence": []}, "observation": {}})))
    dumped = json.dumps(out, ensure_ascii=False)
    for internal in ("verdict=", "insufficient", "complaint_target", "unmet_need"):
        assert internal not in dumped, internal


# ---------------------------------------------------------------------------
# 묶는 축
# ---------------------------------------------------------------------------

def test_groups_are_type_first_and_ordered_by_count():
    """처음 보는 것은 '어디가 제일 많이 터지나' 다."""
    out = handover.build(result(
        turn("case22", evidence=SUFFICIENCY),
        turn("case12", type_id="TYPE3", type_name="의도 파악 실패"),
        turn("case12", type_id="TYPE3", type_name="의도 파악 실패"),
        turn("case12", type_id="TYPE3", type_name="의도 파악 실패"),
    ))
    assert [g["type"] for g in out["분류"]] == ["TYPE3", "TYPE5"]
    assert out["분류"][0]["건수"] == 3
    assert out["분류"][0]["세부"][0]["case"] == "case12"


def test_secondary_cases_ride_along_without_taking_over():
    """한 턴이 검색 실패이면서 복합 질문일 수 있다. 주 라벨은 하나다."""
    out = handover.build(result(turn(
        "case22", evidence=SUFFICIENCY,
        secondary=[{"case_id": "case3", "case_name": "복합 질문을 함"}])))
    meta = out["분류"][0]["세부"][0]["사례"][0]["분석"]["meta_data"]
    assert meta["함께_관찰됨"] == [{"case": "case3", "이름": "복합 질문을 함"}]


def test_every_case_gets_a_reason_even_without_a_template():
    """틀이 없는 case 도 빈 사유로 나가면 안 된다."""
    for case_id in ("case5", "case7", "case19", "case23"):
        out = handover.build(result(turn(case_id, type_id="TYPE2")))
        example = out["분류"][0]["세부"][0]["사례"][0]
        assert example["분석"]["사유"]["요약"], case_id


def test_broken_turns_are_skipped_not_counted():
    """판정이 깨진 턴은 분류가 없다. 실패 건수에 섞이면 통계가 틀어진다."""
    broken = {"turn": 1, "classification": {"error": "JudgeError: 형식 검증 실패"}}
    out = handover.build(result(broken, turn("case22", evidence=SUFFICIENCY)))
    assert out["대상"]["분석한 턴"] == 1


def test_prior_questions_travel_with_the_answered_one():
    """챗봇은 앞 질문들을 함께 받아 답했다. 마지막 질문만 보면 답변이 멀쩡해 보인다.

    "국내 기준으로만" 이 두 턴 앞에 있고 답변이 해외로 답한 경우, 마지막 질문
    ("식비는 얼마인가요")만 실으면 읽는 사람이 무엇이 잘못됐는지 알 수 없다.
    """
    out = handover.build(result(turn("case22", evidence=SUFFICIENCY)))
    example = out["분류"][0]["세부"][0]["사례"][0]
    assert example["앞_질문들"] == ["앞 질문"]
    assert example["질문"] == "국내 출장 식비 상한은?"
    # 대화가 먼저, 그다음 사유, 식별자는 맨 뒤. 읽는 순서가 곧 중요도다.
    assert list(example) == ["앞_질문들", "질문", "답변", "사용자_반응", "분석"]


def test_a_single_turn_carries_no_empty_prior_list():
    """앞 질문이 없으면 빈 배열도 두지 않는다. 절반 넘는 턴이 한 질문뿐이다."""
    single = turn("case22", evidence=SUFFICIENCY)
    single["pre_queries"] = ["하나뿐인 질문"]
    example = handover.build(result(single))["분류"][0]["세부"][0]["사례"][0]
    assert "앞_질문들" not in example
    assert example["질문"] == "하나뿐인 질문"


def test_context_loss_points_at_the_condition_it_broke():
    """case14 는 앞 질문이 핵심이다. 어느 구절인지 짚지 않으면 찾아 읽어야 한다."""
    evidence = {"observation": {"unmet_need": "국내 식비 상한",
                                "history_quote": "국내 기준으로만 알려주세요"}}
    out = handover.build(result(turn("case14", type_id="TYPE3", evidence=evidence)))
    reason = out["분류"][0]["세부"][0]["사례"][0]["분석"]["사유"]
    assert any("국내 기준으로만" in step for step in reason["근거"])


def test_the_entry_point_lives_next_to_the_others():
    """실행 파일은 src/ 에 모은다.

    run.py · dashboard.py · handover.py 셋이 실행 파일이다. tools/ 는 실행 환경에서
    호출이 실패하는 것(claude CLI · Anthropic API)을 두는 자리라, LLM 을 부르지 않는
    이 도구는 거기 있을 이유가 없다. 흩어져 있으면 "무엇을 어디서 돌리나" 를 매번
    찾아야 한다.
    """
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src"
    assert sorted(p.name for p in src.glob("*.py")) == [
        "dashboard.py", "handover.py", "run.py"]


def test_it_reuses_the_venv_switch():
    """진입점마다 다르게 굴면 "저건 되는데 이건 안 된다" 가 된다."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src" / "handover.py").read_text(
        encoding="utf-8")
    assert "from run import switch_venv" in source
    assert "switch_venv(sys.argv[1:])" in source


def test_identifiers_sit_in_meta_not_above_the_conversation():
    """읽는 사람이 먼저 보는 것은 대화지 대화 번호가 아니다."""
    out = handover.build(result(turn("case22", evidence=SUFFICIENCY)))
    example = out["분류"][0]["세부"][0]["사례"][0]
    assert list(example)[-1] == "분석"
    assert example["분석"]["meta_data"]["대화"] == "C-1"
    assert example["분석"]["meta_data"]["case"] == "case22"
    # 되짚을 때만 보는 것들이 위로 올라오면 안 된다.
    for key in ("대화", "턴", "부서", "case", "meta_data", "사유", "문서"):
        assert key not in example


def test_the_reason_is_not_buried_in_meta():
    """대화를 읽고 바로 묻는 것이 '그래서 뭐가 문제냐' 다. 펼쳐야 보이면 안 된다."""
    out = handover.build(result(turn("case22", evidence=SUFFICIENCY)))
    판정 = out["분류"][0]["세부"][0]["사례"][0]["분석"]
    assert list(판정).index("사유") < list(판정).index("meta_data")


def test_missing_values_do_not_become_placeholder_lines():
    """빈 값에 자리표시자를 기본값으로 두면 그게 그대로 나간다.

    실제로 "사용자가 원한 것: 사용자가 원한 것" 이 미분류 사례에 찍혔다.
    관측이 없는 턴(판정이 앞에서 끝난 경우)에서 흔하다.
    """
    out = handover.build(result(turn("case22", evidence={"observation": {}})))
    reason = out["분류"][0]["세부"][0]["사례"][0]["분석"]["사유"]
    assert not any(step.endswith(": 사용자가 원한 것") for step in reason["근거"])
    assert all(step.strip() for step in reason["근거"])


def test_what_the_judge_read_is_kept_apart_from_what_the_user_said():
    """정리된 질문과 요구는 판정 모델이 쓴 문장이다. 대화에 섞으면 원문과 구분이 안 된다."""
    evidence = {"observation": {
        "resolved_question": "협력사 직원 출입증을 신규로 발급받는 데 며칠이 걸리나요?",
        "unmet_need": "협력사 출입증 신규 발급 소요일수"}}
    out = handover.build(result(turn("case20", evidence=evidence)))
    example = out["분류"][0]["세부"][0]["사례"][0]
    assert example["분석"]["판정자가_읽은_것"] == {
        "질문": "협력사 직원 출입증을 신규로 발급받는 데 며칠이 걸리나요?",
        "원한_것": "협력사 출입증 신규 발급 소요일수"}
    # 대화 다음, 사유 앞. 읽은 것을 확인하고 진단으로 넘어가는 순서다.
    keys = list(example["분석"])
    assert keys.index("사유") < keys.index("판정자가_읽은_것") < keys.index("meta_data")


def test_the_requirement_is_not_repeated_in_the_reason():
    """칸으로 올렸으면 근거에서는 빼야 한다. 같은 말이 두 번 나가면 읽기만 나쁘다."""
    out = handover.build(result(turn("case22", evidence=SUFFICIENCY)))
    reason = out["분류"][0]["세부"][0]["사례"][0]["분석"]["사유"]
    assert not any(step.startswith("사용자가 원한 것: ") for step in reason["근거"])


def test_what_was_missing_is_not_said_twice():
    """`문서.없던_내용` 에 있는 것을 근거에 또 적으면 같은 문장이 두 번 나간다."""
    evidence = {"sufficiency": {"missing": "협력사 출입증 신규 발급 소요일", "evidence": []},
                "observation": {"unmet_need": "발급 소요일"}}
    example = handover.build(result(turn("case20", evidence=evidence)))[
        "분류"][0]["세부"][0]["사례"][0]
    assert example["분석"]["문서"]["없던_내용"] == "협력사 출입증 신규 발급 소요일"
    assert not any("협력사 출입증 신규 발급 소요일" in s for s in example["분석"]["사유"]["근거"])


def test_the_quote_list_stays_even_when_empty():
    """검색 실패면 구절이 없지만 칸은 남긴다. 받아 쓰는 쪽이 늘 배열을 기대할 수 있어야 한다."""
    evidence = {"sufficiency": {"missing": "없던 것", "evidence": []}, "observation": {}}
    document = handover.build(result(turn("case21", evidence=evidence)))[
        "분류"][0]["세부"][0]["사례"][0]["분석"]["문서"]
    assert document["구절"] == []


def test_code_only_cases_carry_no_judge_block():
    """case9 · case30 은 코드가 LLM 없이 확정한다. 관측이 없으니 칸도 없다."""
    out = handover.build(result(turn("case9", type_id="TYPE2", evidence={})))
    assert "판정자가_읽은_것" not in out["분류"][0]["세부"][0]["사례"][0]["분석"]


def test_the_conversation_reads_without_opening_anything():
    """판정 쪽 이야기는 한 칸으로 묶어 접을 수 있게 한다.

    대화와 섞여 있으면 읽는 사람이 매번 건너뛰어야 한다. 접은 채로 훑으면 무슨 일이
    있었고(대화 네 칸) 무엇을 고쳐야 하는지(문서)가 남는다.
    """
    out = handover.build(result(turn("case22", evidence=SUFFICIENCY)))
    example = out["분류"][0]["세부"][0]["사례"][0]
    접었을_때 = [k for k in example if k != "분석"]
    assert 접었을_때 == ["앞_질문들", "질문", "답변", "사용자_반응"]
    assert list(example["분석"]) == ["사유", "문서", "판정자가_읽은_것", "meta_data"]
