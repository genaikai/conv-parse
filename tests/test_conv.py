"""conv_eval 포맷 로더 테스트.

이 포맷의 함정은 두 가지다. retrieved_data 가 JSON을 담은 **문자열**이라는 것과,
불만이 그 턴이 아니라 **다음 턴**에 있다는 것. 둘 다 조용히 틀리는 종류라 테스트로 못박는다.
"""

import json

import pytest

from ragdiag.conv import (
    parse_conversations,
    parse_retrieved,
    to_case,
)

RAW = {
    "metadata": {"generated_at": "2026-07-14T18:08:10", "total_users": 1, "total_turns": 3},
    "users": [{
        "job_grade": "Staff Engineer",
        "db_dept_name": "해외영업팀",
        "db_job_name": "해외영업",
        "conversations": [
            {
                "conversation_id": "asbdsa",
                "turns": [{
                    "turn": 1, "request_time": "2026-03-06 10:49:08.298",
                    "prev_question": None, "retrieved_data": "[]",
                    "llm_response": "answer on aaaa", "user_question": "aaaa",
                    "trace_matched": "False",
                    "llm_eval_result": None, "llm_eval_score": None,
                    "llm_eval_score_top1": None, "llm_eval_alternatives": [],
                    "llm_emotion_result": None, "llm_emotion_score": None,
                    "llm_emotion_score_top1": None, "llm_emotion_alternatives": [],
                }],
            },
            {
                # conversation_id 가 없는 대화가 실제로 있다
                "turns": [
                    {
                        "turn": 1, "request_time": "2026-03-07 11:29:04.218",
                        "prev_question": None,
                        "retrieved_data": json.dumps(["미주 숙박비 250달러", "정산 절차"]),
                        "llm_response": "숙박비는 실비 정산입니다.", "user_question": "숙박비 정산은?",
                        "trace_matched": "True",
                        "llm_eval_result": None, "llm_eval_score": None,
                        "llm_eval_score_top1": None, "llm_eval_alternatives": [],
                        "llm_emotion_result": None, "llm_emotion_score": None,
                        "llm_emotion_score_top1": None, "llm_emotion_alternatives": [],
                    },
                    {
                        "turn": 2, "request_time": "2026-03-07 11:31:04.218",
                        "prev_question": "숙박비 정산은?",
                        "retrieved_data": json.dumps(["다른 문서 A", "다른 문서 B"]),
                        "llm_response": "지역별로 다릅니다.", "user_question": "상한 금액을 물었는데요",
                        "trace_matched": "True",
                        "llm_eval_result": "질의 폭스", "llm_eval_score": 45.57,
                        "llm_eval_score_top1": 45,
                        "llm_eval_alternatives": [
                            {"label": "F", "name": "질의 폭스", " probability": 0.9},
                            {"label": "B", "name": "맥락 추가", "probability": 0.095},
                        ],
                        "llm_emotion_result": "감정 델타", "llm_emotion_score": 61.69,
                        "llm_emotion_score_top1": 62.5,
                        "llm_emotion_alternatives": [
                            {"lable": "D", "name": "감정 델타", "probability": 0.931},
                            {"label": "E", "name": "감정 에코", "probability": 0.067},
                        ],
                    },
                ],
            },
        ],
    }],
}


def _convs():
    return parse_conversations(RAW)


# ---------------------------------------------------------------------------
# retrieved_data — JSON을 담은 문자열
# ---------------------------------------------------------------------------

def test_json_string_becomes_a_list():
    assert parse_retrieved('["aaaaa", "bbbbb"]') == ["aaaaa", "bbbbb"]


def test_empty_array_string_is_empty():
    assert parse_retrieved("[]") == []
    assert parse_retrieved("") == []
    assert parse_retrieved(None) == []


def test_actual_list_also_works():
    assert parse_retrieved(["a", "b"]) == ["a", "b"]


def test_dict_items_are_unwrapped():
    assert parse_retrieved('[{"text": "a"}, {"content": "b"}]') == ["a", "b"]


def test_broken_json_falls_back_to_chunk_splitting():
    # 이스케이프가 깨진 채 오는 경우. 버리지 말고 경계 복원을 시도한다.
    assert parse_retrieved("청크 A 내용\n\n청크 B 내용") == ["청크 A 내용", "청크 B 내용"]


def test_blank_items_are_dropped():
    assert parse_retrieved('["a", "   ", "b"]') == ["a", "b"]


# ---------------------------------------------------------------------------
# 구조 파싱
# ---------------------------------------------------------------------------

def test_users_and_conversations_are_flattened():
    convs = _convs()
    assert len(convs) == 2
    assert all(c.user.dept == "해외영업팀" for c in convs)


def test_missing_conversation_id_is_synthesized_and_unique():
    convs = _convs()
    ids = [c.conversation_id for c in convs]
    assert ids[0] == "asbdsa"
    assert ids[1] and ids[1] != "asbdsa"
    assert len(set(ids)) == len(ids)


def test_user_identifiers_are_not_carried():
    """로그에서 없어진 식별자를 UserMeta 가 되살려 두면 안 된다 (2026-10).

    남겨 두면 늘 빈 값인 칸이 출력에 실리고, 받는 쪽은 "이 사용자는 식별자가
    없다" 로 읽는다. 없는 것은 칸도 없어야 한다.
    """
    conv = _convs()[0]
    assert not hasattr(conv.user, "user_id")
    assert not hasattr(conv.user, "raw_user_id")
    assert not hasattr(conv.user, "position_name")


def test_trace_matched_string_becomes_bool():
    convs = _convs()
    assert convs[0].turns[0].trace_matched is False
    assert convs[1].turns[0].trace_matched is True


def test_turns_are_sorted_by_number():
    turns = _convs()[1].turns
    assert [t.turn for t in turns] == [1, 2]


def test_null_eval_fields_become_empty_not_none():
    first = _convs()[1].turns[0]
    assert first.eval_result == ""
    assert first.eval_score is None
    assert first.is_followup is False


def test_followup_turn_carries_eval_labels():
    second = _convs()[1].turns[1]
    assert second.is_followup is True
    assert second.eval_result == "질의 폭스"
    assert second.eval_score == pytest.approx(45.57)
    assert second.emotion_result == "감정 델타"


# ---------------------------------------------------------------------------
# 대안 목록 키 오타
# ---------------------------------------------------------------------------

def test_leading_space_in_probability_key_is_fixed():
    """실데이터에 " probability"(앞 공백)가 있다.

    그대로 두면 확률 기반 필터가 조용히 0을 읽는다 — 에러가 안 나서 더 위험하다.
    """
    alts = _convs()[1].turns[1].eval_alternatives
    assert alts[0]["probability"] == pytest.approx(0.9)


def test_lable_typo_is_fixed():
    alts = _convs()[1].turns[1].emotion_alternatives
    assert alts[0]["label"] == "D"
    assert alts[0]["name"] == "감정 델타"


def test_alternatives_always_have_the_three_keys():
    for alt in _convs()[1].turns[1].eval_alternatives:
        assert set(alt) == {"label", "name", "probability"}


# ---------------------------------------------------------------------------
# 케이스 변환 — 짝짓기가 핵심
# ---------------------------------------------------------------------------

def test_case_pairs_the_followup_with_the_previous_turn():
    conv = _convs()[1]
    case = to_case(conv, followup_turn=2)
    # 불만은 turn 2의 질문
    assert case.current_query == "상한 금액을 물었는데요"
    # 비판받은 답변은 turn 1의 응답
    assert case.llm_ans_on_last_q == "숙박비는 실비 정산입니다."


def test_case_uses_the_documents_behind_the_criticized_answer():
    """rag_data 는 turn N의 것이어야 한다.

    turn N+1의 검색 결과를 쓰면 "다음 질문으로 찾은 문서가 충분했나"를 묻게 되어
    질문 자체가 달라진다. 이걸 틀리면 판정이 통째로 무의미해진다.
    """
    case = to_case(_convs()[1], followup_turn=2)
    assert case.rag_chunks == ["미주 숙박비 250달러", "정산 절차"]
    assert "다른 문서 A" not in case.rag_chunks


def test_history_includes_every_prior_question():
    case = to_case(_convs()[1], followup_turn=2)
    assert case.pre_queries == ["숙박비 정산은?"]
    assert case.last_query == "숙박비 정산은?"


def test_first_turn_cannot_be_a_complaint():
    # 직전 턴이 없으면 비판할 답변도 없다.
    assert to_case(_convs()[1], followup_turn=1) is None


def test_unknown_turn_number_returns_none():
    assert to_case(_convs()[1], followup_turn=99) is None


def test_case_id_is_conversation_and_turn():
    """대화 id 가 전역 유일하다는 전제 위에 서 있다 (2026-10 확인)."""
    conv = _convs()[1]
    case = to_case(conv, followup_turn=2)
    assert case.case_id == f"{conv.conversation_id}:2"


def test_case_carries_user_metadata_for_crosstabs():
    case = to_case(_convs()[1], followup_turn=2)
    assert case.dept == "해외영업팀"
    assert case.job_grade == "Staff Engineer"


def test_missing_optional_fields_do_not_crash():
    raw = {"users": [{"conversations": [
        {"turns": [{"turn": 1}, {"turn": 2}]}]}]}
    conv = parse_conversations(raw)[0]
    assert conv.turns[0].user_question == ""
    assert conv.turns[0].retrieved == []
    assert to_case(conv, 2) is not None


# ---------------------------------------------------------------------------
# 히스토리 상한 — 대명사 해소에 필요한 것은 직전 2~3턴이다
# ---------------------------------------------------------------------------

def _long_conv(n=8):
    turns = [{"turn": i, "user_question": f"질문{i}", "llm_response": f"답변{i}",
              "retrieved_data": json.dumps([f"청크{i}"]),
              "llm_eval_result": None if i == 1 else "질의 폭스"}
             for i in range(1, n + 1)]
    return parse_conversations({"users": [{"user_id": "u", "conversations": [
        {"conversation_id": "c", "turns": turns}]}]})[0]


def test_history_is_capped_to_the_most_recent_turns():
    case = to_case(_long_conv(), followup_turn=8, history_turns=3)
    assert case.pre_queries == ["질문5", "질문6", "질문7"]


def test_the_question_that_produced_the_answer_always_survives():
    """잘라내더라도 비판받은 답변을 부른 질문은 남아야 한다.

    이게 없으면 Step 1 이 무엇에 대한 답변인지 모른 채 불만을 읽는다.
    """
    for cap in (1, 2, 3, 5):
        case = to_case(_long_conv(), followup_turn=8, history_turns=cap)
        assert len(case.pre_queries) == cap
        assert case.last_query == "질문7"
        assert case.llm_ans_on_last_q == "답변7"


def test_zero_means_no_limit():
    case = to_case(_long_conv(), followup_turn=8, history_turns=0)
    assert len(case.pre_queries) == 7


def test_short_conversation_is_unaffected():
    case = to_case(_long_conv(n=3), followup_turn=3, history_turns=3)
    assert case.pre_queries == ["질문1", "질문2"]


def test_default_cap_is_three():
    from ragdiag.conv import MAX_HISTORY_TURNS

    assert MAX_HISTORY_TURNS == 3
    assert len(to_case(_long_conv(), followup_turn=8).pre_queries) == 3


# ---------------------------------------------------------------------------
# 청크 경계 복원 — 실데이터는 청크를 \n\n 또는 \n 으로 이어붙인 통문자열로 온다
# ---------------------------------------------------------------------------

def test_concatenated_string_is_split_on_blank_lines():
    from ragdiag.conv import split_concatenated

    assert split_concatenated("첫 청크입니다.\n\n둘째 청크입니다.\n\n셋째입니다.") == [
        "첫 청크입니다.", "둘째 청크입니다.", "셋째입니다."]


def test_blank_line_split_wins_over_single_newline():
    # 청크 내부에도 개행이 있을 수 있다. 단일 개행부터 쪼개면 한 청크가 찢어진다.
    from ragdiag.conv import split_concatenated

    text = "제1조 목적\n이 규정은 출장비를 정한다.\n\n제2조 범위\n전 임직원에 적용한다."
    assert split_concatenated(text) == [
        "제1조 목적\n이 규정은 출장비를 정한다.", "제2조 범위\n전 임직원에 적용한다."]


def test_falls_back_to_single_newline_when_no_blank_lines():
    from ragdiag.conv import split_concatenated

    assert split_concatenated("청크 하나\n청크 둘\n청크 셋") == ["청크 하나", "청크 둘", "청크 셋"]


def test_single_chunk_string_stays_one_chunk():
    from ragdiag.conv import split_concatenated

    assert split_concatenated("경계가 없는 한 덩어리 문장.") == ["경계가 없는 한 덩어리 문장."]
    assert split_concatenated("   ") == []


def test_concatenated_retrieved_data_is_split_by_the_parser():
    from ragdiag.conv import parse_retrieved

    assert parse_retrieved("청크 A 내용\n\n청크 B 내용") == ["청크 A 내용", "청크 B 내용"]


# ---------------------------------------------------------------------------
# 맥락의 경계 — carried_turn_nos
#
# 전에는 턴 순서로 최근 3개를 우리가 추정했다. 서비스가 실제로 넣은 턴 목록이
# 로그에 생겨서(2026-10) 그걸 쓴다. 추정과 사실이 어긋나면 판정이 조용히 틀린다.
# ---------------------------------------------------------------------------

def _conv_with_carried(carried, *, tool=None, memory="", n=5):
    """턴 n 개짜리 대화 하나. 마지막 턴이 불만, 그 앞이 비판받은 답변이다."""
    turns = []
    for i in range(1, n + 1):
        turns.append({
            "turn": i,
            "user_question": f"질문{i}",
            "llm_response": f"답변{i}",
            "retrieved_data": json.dumps([f"문서{i}"]),
            "tool_output": json.dumps((tool or {}).get(i, [])),
            # carried 는 비판받은 턴(n-1)에만 의미가 있다. 나머지는 비워 둔다.
            "carried_turn_nos": carried if i == n - 1 else [],
            "memory": memory if i == n - 1 else "",
            "llm_eval_result": "후속" if i > 1 else None,
        })
    return parse_conversations({"users": [{
        "db_dept_name": "-", "job_grade": "-", "db_job_name": "-",
        "conversations": [{"conversation_id": "C", "turns": turns}],
    }]})[0]


def test_carried_turns_decide_the_history_window():
    """서비스가 1번만 끌고 갔으면 2·3번은 챗봇이 못 본 것이다.

    턴 순서로 최근 3개를 자르면 질문2·3·4 가 가는데, 챗봇은 질문1 과 질문4 만
    봤다. 못 본 질문에서 "앞에서 정한 조건" 을 찾으면 case14 오탐이 된다.
    """
    case = to_case(_conv_with_carried([1]), followup_turn=5)
    assert case.pre_queries == ["질문1", "질문4"]


def test_the_answered_question_is_always_in_even_if_not_carried():
    """끌려온 목록에 없어도 비판받은 답변을 부른 질문은 들어간다.

    그 질문이 없으면 무엇에 대한 답인지 자체를 알 수 없고, pre_queries[-1] 을
    보는 pii 검증기와 '마지막이 답을 받은 질문' 이라는 전제가 함께 무너진다.
    """
    case = to_case(_conv_with_carried([2]), followup_turn=5)
    assert case.pre_queries == ["질문2", "질문4"]
    assert case.last_query == "질문4"


def test_without_carried_the_old_turn_order_cut_still_works():
    """옛 로그와 골든셋에는 이 필드가 없다. 없으면 전처럼 돌아야 회귀가 안 난다."""
    case = to_case(_conv_with_carried([]), followup_turn=5)
    assert case.pre_queries == ["질문2", "질문3", "질문4"]


def test_tool_output_joins_the_chunk_pool():
    """도구 결과는 문서 검색 결과와 같은 성격이고 답변 생성에 들어간다.

    빼고 보면 도구 결과를 제대로 쓴 답변이 case22(생성 실패) 로, 그 인용이
    case24(지어낸 인용) 로 집계된다. 둘 다 조용히 틀린다.
    """
    case = to_case(_conv_with_carried([1], tool={1: ["끌려온 도구"], 4: ["그 턴 도구"]}),
                   followup_turn=5)
    assert case.rag_chunks == ["문서4", "그 턴 도구", "끌려온 도구"]


def test_carried_turns_contribute_tool_output_but_not_their_documents():
    """끌려온 턴의 retrieved_data 는 서비스가 넘기지 않는다. 그러면 챗봇이
    못 본 문서로 '있었는데 안 썼다'(case22) 를 판정하게 된다."""
    case = to_case(_conv_with_carried([1], tool={1: ["끌려온 도구"]}), followup_turn=5)
    assert "문서1" not in case.rag_chunks


def test_the_answered_turn_documents_come_first():
    """비판받은 답변의 문서가 풀의 앞이다.

    충족도 판정의 본령이 그 문서이고 끌려온 턴 쪽은 보조다. 상한을 두지 않기로
    했으므로(실데이터에서 풀이 실제로 커지는지를 아직 모른다) 지금 순서가 하는
    일은 하나다 - 나중에 상한을 넣을 때 자를 자리가 뒤라는 것.
    """
    from ragdiag.conv import chunk_pool

    conv = _conv_with_carried([1, 2, 3], tool={1: ["끌1"], 2: ["끌2"], 3: ["끌3"]})
    answered = conv.turn_at(4)
    pool = chunk_pool(answered, conv.turns[:4])
    assert pool == ["문서4", "끌1", "끌2", "끌3"]


def test_carried_turn_nos_as_a_string_is_absorbed():
    """이 로그의 retrieved_data 가 이미 문자열로 온 전례가 있다."""
    from ragdiag.conv import _as_turn_nos

    assert _as_turn_nos("[1, 2]") == [1, 2]
    assert _as_turn_nos([1, "2", None]) == [1, 2]
    assert _as_turn_nos("쓰레기") == []
    assert _as_turn_nos(None) == []


def test_memory_reaches_the_case_but_not_the_queries():
    """요약 맥락은 코드 대조에만 쓴다. 판정 LLM 에 넘기면 다른 LLM 이 쓴
    해석이 우리 관측에 섞인다."""
    case = to_case(_conv_with_carried([1], memory="앞에서 국내 기준으로 정함"),
                   followup_turn=5)
    assert case.memory == "앞에서 국내 기준으로 정함"
    assert all("국내 기준" not in q for q in case.pre_queries)
