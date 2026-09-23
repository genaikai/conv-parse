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
    quotes = example["활용했어야_할_문서"]
    assert quotes == [{"문서번호": 0, "구절": "국내 출장 식비는 1일 3만원을 상한으로 한다."}]
    assert "청크 전문" not in json.dumps(out, ensure_ascii=False)


def test_dropped_citations_do_not_travel():
    """대조에 떨어진 인용은 판정에도 안 쓰였다. 실무에 보내면 없는 근거를 믿게 된다."""
    out = handover.build(result(turn("case22", evidence=SUFFICIENCY)))
    assert "지어낸 구절" not in json.dumps(out, ensure_ascii=False)


@pytest.mark.parametrize("case_id,field", [
    ("case22", "활용했어야_할_문서"),
    ("case18", "답변과_어긋나는_문서"),
    ("case17", "활용한_문서"),
])
def test_the_document_field_says_why_it_is_there(case_id, field):
    """같은 인용이라도 case 마다 읽는 법이 다르다. 이름이 같으면 잘못 읽는다."""
    out = handover.build(result(turn(case_id, evidence=SUFFICIENCY)))
    example = out["분류"][0]["세부"][0]["사례"][0]
    assert field in example
    assert example[f"{field}_설명"]


@pytest.mark.parametrize("case_id", ["case20", "case21"])
def test_retrieval_failures_carry_what_was_missing_not_documents(case_id):
    """쓸 문서가 없다는 것이 결론이다. 문서 칸을 두면 빈 배열만 남아 혼란스럽다."""
    evidence = {"sufficiency": {"verdict": "insufficient", "final_verdict": "insufficient",
                                "missing": "협력사 출입증 신규 발급 소요일", "evidence": []},
                "observation": {"unmet_need": "발급 소요일"}}
    out = handover.build(result(turn(case_id, evidence=evidence)))
    example = out["분류"][0]["세부"][0]["사례"][0]
    assert example["문서에_없던_것"] == "협력사 출입증 신규 발급 소요일"
    assert not any("문서" == k or k.endswith("_할_문서") for k in example if k != "문서에_없던_것")


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
    assert out["미분류"]["사례"][0]["사유"]["요약"]
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
    example = out["분류"][0]["세부"][0]["사례"][0]
    assert example["함께_관찰됨"] == [{"case": "case3", "이름": "복합 질문을 함"}]


def test_every_case_gets_a_reason_even_without_a_template():
    """틀이 없는 case 도 빈 사유로 나가면 안 된다."""
    for case_id in ("case5", "case7", "case19", "case23"):
        out = handover.build(result(turn(case_id, type_id="TYPE2")))
        example = out["분류"][0]["세부"][0]["사례"][0]
        assert example["사유"]["요약"], case_id


def test_broken_turns_are_skipped_not_counted():
    """판정이 깨진 턴은 분류가 없다. 실패 건수에 섞이면 통계가 틀어진다."""
    broken = {"turn": 1, "classification": {"error": "JudgeError: 형식 검증 실패"}}
    out = handover.build(result(broken, turn("case22", evidence=SUFFICIENCY)))
    assert out["대상"]["분석한 턴"] == 1
