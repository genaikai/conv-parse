"""실무 전달본이 약속한 모양을 지키는지.

이 파일이 지키는 약속은 다섯이다. 다섯 다 실무가 **잘못 읽으면 엉뚱한 곳을 고치게 되는**
것들이라 조용히 깨지면 안 된다.

  - 청크 풀 전체가 아니라 근거로 선 청크만, 어긋남 인용은 원문 대조를 통과한 것만 싣는다
  - 신뢰도 · 등급을 싣지 않는다
  - 정상 턴(N0)은 빼고, 미분류는 맨 뒤에 따로 싣는다
  - 사유에 내부 용어가 없다 - 라벨과 태그가 문장을 정한다
  - 플래그 · 이벤트는 실패 건수 밖에서 따로 센다
"""

from __future__ import annotations

import json

import pytest

from ragdiag import taxonomy
from ragdiag.features import handover

CHUNK = "국내 출장 식비는 1일 3만원을 상한으로 한다. 해외 출장은 별표 2 에 따른다."
OTHER_CHUNK = "관계없는 청크 " * 20


def turn(label_id, *, tags=(), flags=(), events=(), evidence=None, secondary=None,
         notes=None, chunks=None):
    meta = taxonomy.describe(label_id)
    return {
        "turn": 3,
        "pre_queries": ["앞 질문", "국내 출장 식비 상한은?"],
        "llm_ans_on_last_q": "규정에 따라 지급됩니다.",
        "current_query": "그러니까 얼마냐고요",
        "chunk_data": chunks if chunks is not None else [CHUNK, OTHER_CHUNK],
        "classification": {
            **meta,
            "confidence": "high", "grade": 3,
            "reason": "가져온 문서가 요구를 충족하지 못함 (verdict=insufficient)",
            "tags": list(tags), "flags": list(flags), "events": list(events),
            "secondary_cases": secondary or [],
            "candidates": [{"label": label_id, "grade": 3, "reason": "…", "tags": []}],
            "notes": notes or [],
            "evidence": evidence or {},
            "llm_calls": 3, "kev_calls": 12,
        },
    }


def result(*turns):
    return {"analysis_results": [{
        "user_id": "u1", "db_dept_name": "해외영업팀",
        "conversations": [{"chat_id": "C-1", "turns": list(turns)}],
    }]}


SUFFICIENCY = {
    "sufficiency": {
        "verdict": "sufficient", "final_verdict": "sufficient", "missing": "", "verified": True,
        # 근거는 청크 인덱스와 확률이다. 문턱(0.8) 아래 청크는 여기 들어오지 않는다.
        "evidence": [{"chunk_index": 0, "p": 0.93, "source": "retrieved", "scope": "own"}],
        "scopes": {"own": {"need": "국내 출장 식비 상한 금액", "verdict": "sufficient",
                           "verified": True,
                           "supports": [{"chunk_index": 0, "p": 0.93, "source": "retrieved"},
                                        {"chunk_index": 1, "p": 0.12, "source": "retrieved"}]}},
    },
    "observation": {"unmet_need": "국내 출장 식비 상한 금액",
                    "complaint_target": "content_missing"},
}

MISSING = {
    "sufficiency": {"verdict": "insufficient", "final_verdict": "insufficient",
                    "missing": "협력사 출입증 신규 발급 소요일", "evidence": [], "scopes": {}},
    "observation": {"unmet_need": "발급 소요일"},
}


def first_example(out):
    return out["분류"][0]["세부"][0]["사례"][0]


# ---------------------------------------------------------------------------
# 문서를 추리는 규칙
# ---------------------------------------------------------------------------

def test_only_evidence_chunks_travel_not_the_whole_pool():
    """풀 전체를 주면 어느 것이 문제인지 도로 찾아야 한다. 근거로 선 청크와 그 확률만."""
    out = handover.build(result(turn("G5", tags=["G5:안씀"], evidence=SUFFICIENCY)))
    assert first_example(out)["분석"]["문서"]["구절"] == [
        {"문서번호": 0, "p": 0.93, "구절": CHUNK}]
    assert "관계없는 청크" not in json.dumps(out, ensure_ascii=False)


def test_unverified_conflict_quotes_do_not_travel():
    """대조에 떨어진 인용은 판정에도 안 쓰였다. 실무에 보내면 없는 근거를 믿게 된다."""
    evidence = {**SUFFICIENCY, "quotes": [
        {"kind": "G5:어긋남", "answer_quote": "1일 5만원", "source_quote": "1일 3만원",
         "verified": True},
        {"kind": "G5:어긋남", "answer_quote": "지어낸 구절", "source_quote": "지어낸 원문",
         "verified": False},
    ]}
    out = handover.build(result(turn("G5", tags=["G5:어긋남"], evidence=evidence)))
    document = first_example(out)["분석"]["문서"]
    assert document["어긋난_구절"] == [{"답변": "1일 5만원", "근거": "1일 3만원", "종류": "G5:어긋남"}]
    assert "지어낸 구절" not in json.dumps(out, ensure_ascii=False)


def test_a_contradiction_without_evidence_chunks_still_shows_the_pair():
    """앞 답변과의 모순(G2)은 충족도 근거가 없어도 어긋난 두 구절이 곧 문서다."""
    evidence = {"quotes": [{"kind": "G2:모순", "answer_quote": "연 15일",
                            "source_quote": "연 12일", "verified": True}]}
    out = handover.build(result(turn("G2", tags=["G2:모순"], evidence=evidence)))
    document = first_example(out)["분석"]["문서"]
    assert document["성격"] == "답변과_어긋나는_문서"
    assert document["구절"] == []
    assert document["어긋난_구절"][0]["종류"] == "G2:모순"


@pytest.mark.parametrize("tags,kind", [
    (["G5:안씀"], "활용했어야_할_문서"),
    (["G5:어긋남"], "답변과_어긋나는_문서"),
    (["G5:과거근거"], "활용했어야_할_문서"),
])
def test_the_document_says_why_it_is_there(tags, kind):
    """같은 청크라도 태그마다 읽는 법이 다르다.

    다만 **키 이름으로 가르지 않는다** - 받아 쓰는 쪽이 네 이름을 다 알고 하나씩
    있는지 봐야 한다. 키는 언제나 `문서` 고, 어떻게 읽을지는 `성격` 이 말한다.
    """
    out = handover.build(result(turn("G5", tags=tags, evidence=SUFFICIENCY)))
    document = first_example(out)["분석"]["문서"]
    assert document["성격"] == kind
    assert document["설명"]


def test_the_residual_label_reads_its_documents_as_used():
    out = handover.build(result(turn("G3", evidence=SUFFICIENCY)))
    assert first_example(out)["분석"]["문서"]["성격"] == "활용한_문서"


@pytest.mark.parametrize("label_id", ["D1", "T1", "T2", "T3"])
def test_retrieval_failures_carry_what_was_missing_not_documents(label_id):
    """쓸 문서가 없다는 것이 결론이다. 문서 칸을 두면 빈 배열만 남아 혼란스럽다."""
    out = handover.build(result(turn(label_id, evidence=MISSING)))
    document = first_example(out)["분석"]["문서"]
    assert document["성격"] == "문서에_없던_것"
    assert document["없던_내용"] == "협력사 출입증 신규 발급 소요일"
    assert document["구절"] == []


def test_missing_falls_back_to_the_unmet_need():
    """T1 은 충족도를 돌리지 않을 수 있다. 그래도 원한 것은 관측에 있다."""
    out = handover.build(result(turn("T1", evidence={"observation": {"unmet_need": "발급 소요일"}})))
    assert first_example(out)["분석"]["문서"]["없던_내용"] == "발급 소요일"


# ---------------------------------------------------------------------------
# 담지 않기로 한 것
# ---------------------------------------------------------------------------

def test_confidence_and_grade_never_travel():
    """실무가 쓸 기준이 아니다. 라벨마다 뜻이 달라서 같은 무게로 읽으면 틀린다."""
    out = handover.build(result(turn("G5", tags=["G5:안씀"], evidence=SUFFICIENCY)))
    dumped = json.dumps(out, ensure_ascii=False)
    for word in ("confidence", "신뢰도", "grade", "등급", "candidates"):
        assert word not in dumped, word


def test_normal_turns_are_left_out_but_counted():
    """N0 은 챗봇 지표가 아니라 필터 지표다. 빼되 몇 건인지는 남긴다."""
    out = handover.build(result(turn("N0"), turn("G5", tags=["G5:안씀"], evidence=SUFFICIENCY)))
    assert out["대상"] == {"로그": "", "분석한 턴": 2, "실패로 판정": 1, "정상으로 판정": 1}
    assert all(g["type"] != "N" for g in out["분류"])


def test_unclassified_is_shown_at_the_end_not_hidden():
    """숨기면 실패 건수가 줄어 보이고, 원본과 대조할 때 신뢰를 잃는다."""
    out = handover.build(result(turn("unclassified")))
    assert out["분류"] == []
    assert out["대상"]["실패로 판정"] == 0
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
    out = handover.build(result(turn("D1", tags=["D:출처미상", "복합질문"], evidence={
        "sufficiency": {"missing": "없던 것", "evidence": []}, "observation": {}})))
    dumped = json.dumps(out, ensure_ascii=False)
    for internal in ("verdict=", "insufficient", "complaint_target", "unmet_need",
                     "kev", "chunk_index"):
        assert internal not in dumped, internal


# ---------------------------------------------------------------------------
# 사유 - 라벨과 태그가 문장을 정한다
# ---------------------------------------------------------------------------

def test_every_label_has_a_reason_template():
    """틀이 없는 라벨이 라벨 이름으로 떨어지면 실무가 "그래서 뭐가 문제냐" 를 다시 묻는다."""
    for label_id in taxonomy.LABELS:
        reason = handover.reason_for(label_id, [], turn(label_id))
        assert reason["요약"], label_id
        assert reason["요약"] != taxonomy.label(label_id), label_id


@pytest.mark.parametrize("label_id,tags,phrase", [
    ("G5", ["G5:어긋남"], "어긋나는 주장"),
    ("G5", ["G5:안씀"], "쓰지 않았다"),
    ("G5", ["G5:지어낸인용"], "인용"),
    ("G2", ["G2:memory"], "사용자 정보(memory)"),
    ("G2", ["G2:모순"], "앞 답변과 다른"),
    ("G1", ["G1:언어"], "언어"),
    ("G1", ["G1:포맷", "G1:길이"], "분량 · 형식"),
    ("G6", ["G6:계산"], "계산"),
])
def test_the_tag_decides_the_wording(label_id, tags, phrase):
    """v3 는 '무엇을 어겼나' 가 태그에 있다. 라벨만 보고 쓰면 G5 가 전부 같은 문장이다."""
    out = handover.build(result(turn(label_id, tags=tags, evidence=SUFFICIENCY)))
    assert phrase in first_example(out)["분석"]["사유"]["요약"]


def test_another_labels_tag_does_not_bend_the_wording():
    """G5 턴에 붙은 `G1:언어` 는 함께 관찰된 것이지 G5 의 세부가 아니다."""
    reason = handover.reason_for("G5", ["G1:언어", "G5:안씀"], turn("G5"))
    assert "쓰지 않았다" in reason["요약"]
    assert not any("언어" in s for s in reason["근거"])


def test_context_loss_points_at_the_condition_it_broke():
    """G2[조건] 은 앞 질문이 핵심이다. 어느 구절인지 짚지 않으면 찾아 읽어야 한다."""
    evidence = {"observation": {"unmet_need": "국내 식비 상한",
                                "history_quote": "국내 기준으로만 알려주세요",
                                "history_quote_verified": True}}
    out = handover.build(result(turn("G2", tags=["G2:조건"], evidence=evidence)))
    reason = first_example(out)["분석"]["사유"]
    assert any("국내 기준으로만" in step for step in reason["근거"])


def test_a_flag_on_the_turn_is_said_in_the_reason():
    """C1 이 선 턴은 맥락 판정을 안 했다. 그걸 모르면 "왜 G2 가 아니냐" 를 묻는다."""
    out = handover.build(result(turn("G5", tags=["G5:안씀"], flags=["C1"], evidence=SUFFICIENCY)))
    assert any(step.startswith("기록 주의") for step in first_example(out)["분석"]["사유"]["근거"])


def test_code_checks_replace_the_confidence_grade():
    """등급을 뺀 대가로 코드가 확인한 것을 싣는다. 등급보다 뜻이 분명하다."""
    evidence = {"checks": [
        {"name": "arithmetic", "verdict": "violated", "detail": "3,000 + 2,000 = 6,000 (실제 5,000)"},
        {"name": "language", "verdict": "ok", "detail": ""}]}
    out = handover.build(result(turn("G6", tags=["G6:계산", "arithmetic"], evidence=evidence)))
    steps = first_example(out)["분석"]["사유"]["근거"]
    assert "코드 확인 — arithmetic: 3,000 + 2,000 = 6,000 (실제 5,000)" in steps
    assert not any("language" in s for s in steps)


# ---------------------------------------------------------------------------
# 묶는 축 - 묶음 → 라벨 → 태그 → 사례
# ---------------------------------------------------------------------------

def test_groups_are_owner_first_and_ordered_by_count():
    """처음 보는 것은 '어디가 제일 많이 터지나' 고, 묶음은 고치는 사람이다."""
    out = handover.build(result(
        turn("D1", evidence=MISSING),
        turn("G1", tags=["G1:포맷"]),
        turn("G1", tags=["G1:포맷"]),
        turn("G1", tags=["G1:언어"]),
    ))
    assert [g["type"] for g in out["분류"]] == ["G", "D"]
    assert out["분류"][0]["건수"] == 3
    assert out["분류"][0]["이름"] == "생성"
    assert out["분류"][0]["고칠_곳"] == taxonomy.GROUPS["G"].owner
    assert out["분류"][0]["세부"][0]["case"] == "G1"


def test_labels_inside_a_group_keep_taxonomy_order():
    """표에서 본 라벨을 찾을 수 있어야 한다. 건수 순으로 섞지 않는다."""
    out = handover.build(result(turn("G5", tags=["G5:안씀"], evidence=SUFFICIENCY),
                                turn("G5", tags=["G5:안씀"], evidence=SUFFICIENCY),
                                turn("G1", tags=["G1:언어"])))
    assert [c["case"] for c in out["분류"][0]["세부"]] == ["G1", "G5"]


def test_tags_are_counted_inside_the_label():
    """G1 이 열 건이면 그중 언어가 몇, 형식이 몇인지가 고칠 순서를 정한다."""
    out = handover.build(result(
        turn("G1", tags=["G1:언어"]),
        turn("G1", tags=["G1:언어", "복합질문"]),
        turn("G1", tags=["G1:포맷", "format"]),
    ))
    g1 = out["분류"][0]["세부"][0]
    assert g1["태그별"] == {"G1:언어": 2, "복합질문": 1, "G1:포맷": 1, "format": 1}
    # 뜻은 등록된 태그에만 있다. 검증기 이름(format)은 뜻 없이 센다.
    assert g1["태그_뜻"] == {"G1:언어": taxonomy.TAGS["G1:언어"],
                            "복합질문": taxonomy.TAGS["복합질문"],
                            "G1:포맷": taxonomy.TAGS["G1:포맷"]}
    assert list(g1).index("태그별") < list(g1).index("사례")


def test_a_label_without_tags_still_has_the_tag_slot():
    """받아 쓰는 쪽이 늘 같은 모양을 기대할 수 있어야 한다."""
    out = handover.build(result(turn("S1")))
    assert out["분류"][0]["세부"][0]["태그별"] == {}
    assert "태그_뜻" not in out["분류"][0]["세부"][0]


def test_secondary_cases_ride_along_without_taking_over():
    """한 턴이 근거 미활용이면서 요구 불이행일 수 있다. 주 라벨은 하나다."""
    out = handover.build(result(turn(
        "G5", tags=["G5:안씀", "G1:언어"], evidence=SUFFICIENCY,
        secondary=[taxonomy.describe("G1")])))
    meta = first_example(out)["분석"]["meta_data"]
    assert meta["함께_관찰됨"] == [{"case": "G1", "이름": "명시 요구 불이행"}]
    assert meta["태그"] == ["G5:안씀", "G1:언어"]


def test_broken_turns_are_skipped_not_counted():
    """판정이 깨진 턴은 분류가 없다. 실패 건수에 섞이면 통계가 틀어진다."""
    broken = {"turn": 1, "classification": {"error": "JudgeError: 형식 검증 실패"}}
    out = handover.build(result(broken, turn("G5", tags=["G5:안씀"], evidence=SUFFICIENCY)))
    assert out["대상"]["분석한 턴"] == 1


# ---------------------------------------------------------------------------
# 분모 밖 - 플래그 · 이벤트 · 못 보는 실패
# ---------------------------------------------------------------------------

def test_flags_and_events_are_counted_apart_from_failures():
    """C · U2 는 챗봇이 틀린 것이 아니다. 사례에 섞으면 실패 건수가 부푼다."""
    out = handover.build(result(
        turn("G5", tags=["G5:안씀"], flags=["C1"], evidence=SUFFICIENCY),
        turn("N0", events=["U2"]),           # 정상 턴에서도 이벤트는 센다
        turn("D1", flags=["C1", "C2"], evidence=MISSING),
    ))
    assert out["대상"]["실패로 판정"] == 2
    section = out["무결성_이벤트"]
    assert section["설명"]
    assert [(i["id"], i["건수"]) for i in section["항목"]] == [("U2", 1), ("C1", 2), ("C2", 1)]
    c1 = section["항목"][1]
    assert c1["이름"] == "앞 턴 누락" and c1["뜻"] == taxonomy.desc("C1")
    assert c1["턴"] == [{"대화": "C-1", "턴": 3}, {"대화": "C-1", "턴": 3}]
    # 사례 묶음에는 섞이지 않는다.
    assert all(c["case"] not in ("C1", "C2", "U2") for g in out["분류"] for c in g["세부"])


def test_the_integrity_table_is_absent_when_nothing_happened():
    """빈 표는 "무결성이 뭔가" 만 묻게 한다."""
    out = handover.build(result(turn("G5", tags=["G5:안씀"], evidence=SUFFICIENCY)))
    assert "무결성_이벤트" not in out


def test_integrity_comes_after_failures_and_before_unclassified():
    out = handover.build(result(turn("G5", flags=["C2"], evidence=SUFFICIENCY),
                                turn("unclassified")))
    keys = list(out)
    assert keys.index("분류") < keys.index("무결성_이벤트") < keys.index("미분류")


def test_excluded_failures_are_named_up_front():
    """목록에서 조용히 지우면 "그건 안 터지나" 로 읽는다. 못 보는 문제라고 머리에 적는다."""
    out = handover.build(result(turn("G5", evidence=SUFFICIENCY)))
    keys = list(out)
    assert keys.index("대상") < keys.index("제외한_실패") < keys.index("분류")
    for word in ("지연", "잘림", "컨텍스트", "문서", "권한"):
        assert word in out["제외한_실패"], word


# ---------------------------------------------------------------------------
# 사례 하나의 모양
# ---------------------------------------------------------------------------

def test_prior_questions_travel_with_the_answered_one():
    """챗봇은 앞 질문들을 함께 받아 답했다. 마지막 질문만 보면 답변이 멀쩡해 보인다.

    "국내 기준으로만" 이 두 턴 앞에 있고 답변이 해외로 답한 경우, 마지막 질문
    ("식비는 얼마인가요")만 실으면 읽는 사람이 무엇이 잘못됐는지 알 수 없다.
    """
    out = handover.build(result(turn("G5", tags=["G5:안씀"], evidence=SUFFICIENCY)))
    example = first_example(out)
    assert example["앞_질문들"] == ["앞 질문"]
    assert example["질문"] == "국내 출장 식비 상한은?"
    # 대화가 먼저, 그다음 사유, 식별자는 맨 뒤. 읽는 순서가 곧 중요도다.
    assert list(example) == ["앞_질문들", "질문", "답변", "사용자_반응", "분석"]


def test_a_single_turn_carries_no_empty_prior_list():
    """앞 질문이 없으면 빈 배열도 두지 않는다. 절반 넘는 턴이 한 질문뿐이다."""
    single = turn("G5", tags=["G5:안씀"], evidence=SUFFICIENCY)
    single["pre_queries"] = ["하나뿐인 질문"]
    example = first_example(handover.build(result(single)))
    assert "앞_질문들" not in example
    assert example["질문"] == "하나뿐인 질문"


def test_the_entry_point_lives_next_to_the_others():
    """실행 파일은 src/ 에 모은다.

    run.py · assemble.py · dashboard.py · handover.py 넷이 실행 파일이다. tools/ 는 실행 환경에서
    호출이 실패하는 것(claude CLI · Anthropic API)을 두는 자리라, LLM 을 부르지 않는
    이 도구는 거기 있을 이유가 없다. 흩어져 있으면 "무엇을 어디서 돌리나" 를 매번
    찾아야 한다.
    """
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src"
    assert sorted(p.name for p in src.glob("*.py")) == [
        "assemble.py", "dashboard.py", "handover.py", "run.py"]


def test_it_reuses_the_venv_switch():
    """진입점마다 다르게 굴면 "저건 되는데 이건 안 된다" 가 된다."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src" / "handover.py").read_text(
        encoding="utf-8")
    assert "from run import switch_venv" in source
    assert "switch_venv(sys.argv[1:])" in source


def test_identifiers_sit_in_meta_not_above_the_conversation():
    """읽는 사람이 먼저 보는 것은 대화지 대화 번호가 아니다."""
    out = handover.build(result(turn("G5", tags=["G5:안씀"], evidence=SUFFICIENCY)))
    example = first_example(out)
    assert list(example)[-1] == "분석"
    assert example["분석"]["meta_data"]["대화"] == "C-1"
    assert example["분석"]["meta_data"]["case"] == "G5"
    # 되짚을 때만 보는 것들이 위로 올라오면 안 된다.
    for key in ("대화", "턴", "부서", "case", "태그", "meta_data", "사유", "문서"):
        assert key not in example


def test_the_reason_is_not_buried_in_meta():
    """대화를 읽고 바로 묻는 것이 '그래서 뭐가 문제냐' 다. 펼쳐야 보이면 안 된다."""
    out = handover.build(result(turn("G5", tags=["G5:안씀"], evidence=SUFFICIENCY)))
    판정 = first_example(out)["분석"]
    assert list(판정).index("사유") < list(판정).index("meta_data")


def test_missing_values_do_not_become_placeholder_lines():
    """빈 값에 자리표시자를 기본값으로 두면 그게 그대로 나간다.

    실제로 "사용자가 원한 것: 사용자가 원한 것" 이 미분류 사례에 찍혔다.
    관측이 없는 턴(판정이 앞에서 끝난 경우)에서 흔하다.
    """
    out = handover.build(result(turn("G5", tags=["G5:안씀"], evidence={"observation": {}})))
    reason = first_example(out)["분석"]["사유"]
    assert not any(step.endswith(": 사용자가 원한 것") for step in reason["근거"])
    assert all(step.strip() for step in reason["근거"])


def test_what_the_judge_read_is_kept_apart_from_what_the_user_said():
    """정리된 질문과 요구는 판정 모델이 쓴 문장이다. 대화에 섞으면 원문과 구분이 안 된다."""
    evidence = {"observation": {
        "resolved_question": "협력사 직원 출입증을 신규로 발급받는 데 며칠이 걸리나요?",
        "unmet_need": "협력사 출입증 신규 발급 소요일수"}}
    out = handover.build(result(turn("D1", evidence=evidence)))
    example = first_example(out)
    assert example["분석"]["판정자가_읽은_것"] == {
        "질문": "협력사 직원 출입증을 신규로 발급받는 데 며칠이 걸리나요?",
        "원한_것": "협력사 출입증 신규 발급 소요일수"}
    # 대화 다음, 사유 앞. 읽은 것을 확인하고 진단으로 넘어가는 순서다.
    keys = list(example["분석"])
    assert keys.index("사유") < keys.index("판정자가_읽은_것") < keys.index("meta_data")


def test_the_requirement_is_not_repeated_in_the_reason():
    """칸으로 올렸으면 근거에서는 빼야 한다. 같은 말이 두 번 나가면 읽기만 나쁘다."""
    out = handover.build(result(turn("G5", tags=["G5:안씀"], evidence=SUFFICIENCY)))
    reason = first_example(out)["분석"]["사유"]
    assert not any("국내 출장 식비 상한 금액" in step for step in reason["근거"])


def test_what_was_missing_is_not_said_twice():
    """`문서.없던_내용` 에 있는 것을 근거에 또 적으면 같은 문장이 두 번 나간다."""
    example = first_example(handover.build(result(turn("D1", evidence=MISSING))))
    assert example["분석"]["문서"]["없던_내용"] == "협력사 출입증 신규 발급 소요일"
    assert not any("협력사 출입증 신규 발급 소요일" in s for s in example["분석"]["사유"]["근거"])


def test_the_quote_list_stays_even_when_empty():
    """검색 실패면 구절이 없지만 칸은 남긴다. 받아 쓰는 쪽이 늘 배열을 기대할 수 있어야 한다."""
    evidence = {"sufficiency": {"missing": "없던 것", "evidence": []}, "observation": {}}
    document = first_example(handover.build(result(turn("T1", evidence=evidence))))["분석"]["문서"]
    assert document["구절"] == []


def test_code_only_labels_carry_no_judge_block():
    """I1 · I2 는 코드가 LLM 없이 확정한다. 관측이 없으니 칸도 없다."""
    out = handover.build(result(turn("I1", evidence={})))
    assert "판정자가_읽은_것" not in first_example(out)["분석"]
    assert "문서" not in first_example(out)["분석"]


def test_the_conversation_reads_without_opening_anything():
    """판정 쪽 이야기는 한 칸으로 묶어 접을 수 있게 한다.

    대화와 섞여 있으면 읽는 사람이 매번 건너뛰어야 한다. 접은 채로 훑으면 무슨 일이
    있었고(대화 네 칸) 무엇을 고쳐야 하는지(문서)가 남는다.
    """
    out = handover.build(result(turn("G5", tags=["G5:안씀"], evidence=SUFFICIENCY)))
    example = first_example(out)
    접었을_때 = [k for k in example if k != "분석"]
    assert 접었을_때 == ["앞_질문들", "질문", "답변", "사용자_반응"]
    assert list(example["분석"]) == ["사유", "문서", "판정자가_읽은_것", "meta_data"]


# ---------------------------------------------------------------------------
# 옛 결과 파일
# ---------------------------------------------------------------------------

def test_old_result_files_are_read_through_the_v2_table():
    """디스크의 결과 파일은 아직 case0~30 이다. 전부 미분류로 보내면 전달본이 쓸모없다.

    taxonomy.from_v2 가 옛 case → 라벨 + 태그 를 안다. 자리가 없는 옛 case(제외 ·
    태그로만 남는 것)는 미분류로 가되 어느 옛 번호였는지 `구분` 에 남긴다.
    """
    old = turn("G5", evidence=SUFFICIENCY)
    old["classification"] = {"case_id": "case22", "case_name": "근거 미활용", "type_id": "TYPE5",
                             "type_name": "검색 문제", "confidence": "high",
                             "evidence": SUFFICIENCY, "secondary_cases": [], "notes": []}
    gone = turn("G5")
    gone["classification"] = {"case_id": "case8", "case_name": "제외된 것", "type_id": "TYPE1"}
    normal = turn("N0")
    normal["classification"] = {"case_id": "case0", "case_name": "정상", "type_id": "TYPE0"}
    out = handover.build(result(old, gone, normal))
    assert out["대상"] == {"로그": "", "분석한 턴": 3, "실패로 판정": 1, "정상으로 판정": 1}
    example = first_example(out)
    assert example["분석"]["meta_data"]["case"] == "G5"
    assert example["분석"]["meta_data"]["태그"] == ["G5:안씀"]
    assert example["분석"]["문서"]["성격"] == "활용했어야_할_문서"
    assert out["분류"][0]["세부"][0]["태그별"] == {"G5:안씀": 1}
    assert out["미분류"]["사례"][0]["분석"]["meta_data"]["구분"].startswith("옛 분류 case8")
