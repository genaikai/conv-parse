"""history_input — 모델에 실제로 들어간 입력을 받는다.

2026-10 로그가 `history_input` 을 주기 시작했다. 그전까지 우리는 `pre_queries` 를
턴 순서로 **재구성**했고 끌려온 턴의 문서는 안 넘어온다고 적어 뒀는데, 둘 다
틀렸거나 추정이었다.

여기서 못박는 것은 세 갈래다.

    1. tool_output 두 모양      턴 레벨은 통문자열, history 쪽은 구조체 배열
    2. pre_queries 3단 폴백     history_chat → prev_question → 턴 순서
    3. 청크 풀 중복 금지         history_input 이 있으면 끌려온 턴을 다시 안 돈다

셋 다 조용히 틀리는 종류다. 1번이 틀리면 청크가 0개가 되고, 2번이 틀리면 비판받은
답변을 부른 질문이 빠지고, 3번이 틀리면 같은 청크가 두 번 들어간다. 어느 쪽도
에러를 안 낸다.
"""

import pytest

from ragdiag.conv import (
    HistoryInput,
    chunk_pool,
    memory_pool,
    parse_conversations,
    parse_history_input,
    parse_tool_output,
    pre_queries,
    to_case,
)

STRUCTURED = [{
    "turn_no": 1,
    "tool_calls": [{"name": "tool_1", "arguments": '{"part": "photo"}'},
                   {"name": "tool_2", "arguments": '{"query": "S3 WSPED01"}'}],
    "outputs": ['{"pattern": "WSP", "count": 0}', '{"hit": 1}'],
}]


# ---------------------------------------------------------------------------
# 1. tool_output 의 두 모양
# ---------------------------------------------------------------------------

def test_structured_tool_output_yields_outputs():
    """구조체 배열에서 outputs 만 청크가 된다.

    전에는 리스트 안의 dict 에서 text·content·chunk 만 찾았다. 실제 모양에는 셋 다
    없어서 **청크 0개**가 조용히 나왔다 - tool_output 을 아예 안 받는 것과 같다.
    """
    assert parse_tool_output(STRUCTURED) == ['{"pattern": "WSP", "count": 0}', '{"hit": 1}']


def test_tool_calls_do_not_become_chunks():
    """무엇을 물었는지는 충족도 대조의 대상이 아니다.

    outputs 와 인덱스로 짝이 맞는지도 확인되지 않았다. 짝을 가정해 붙이면 틀린
    짝이 근거로 인용된다.
    """
    chunks = parse_tool_output(STRUCTURED)
    assert not any("tool_1" in c or "part" in c for c in chunks)


def test_turn_no_is_not_prefixed_onto_the_chunk():
    """청크 본문에 머리말을 끼우면 인용 대조가 로그에 없던 문자열을 보게 된다."""
    assert all(not c.startswith("[") for c in parse_tool_output(STRUCTURED))


@pytest.mark.parametrize("value,expected", [
    ("도구 결과 한 덩어리", ["도구 결과 한 덩어리"]),
    ('["a", "b"]', ["a", "b"]),
    ("a\n\nb", ["a", "b"]),
    ([], []),
    (None, []),
    ("", []),
])
def test_plain_tool_output_keeps_working(value, expected):
    """턴 레벨은 통문자열이다. 옛 경로가 그대로 돌아야 한다."""
    assert parse_tool_output(value) == expected


# ---------------------------------------------------------------------------
# 2. history_input 파싱
# ---------------------------------------------------------------------------

def test_only_user_messages_become_queries():
    """assistant 쪽은 버린다 - Case 는 앞 턴의 답변을 아예 안 싣는다."""
    got = parse_history_input({"history_chat": [
        {"role": "user", "content": "첫 질문"},
        {"role": "assistant", "content": "첫 답변"},
        {"role": "user", "content": "둘째 질문"},
    ]})
    assert got.queries == ["첫 질문", "둘째 질문"]


def test_missing_history_input_is_not_present():
    """'키가 없다' 와 '있는데 비었다' 는 다른 사실이다."""
    assert parse_history_input(None).present is False
    assert parse_history_input({}).present is True


def test_history_input_carries_its_own_chunks():
    got = parse_history_input({
        "retrieved_data": '["앞 턴 문서"]',
        "tool_output": STRUCTURED,
    })
    assert got.retrieved == ["앞 턴 문서"]
    assert got.tool_output == ['{"pattern": "WSP", "count": 0}', '{"hit": 1}']


# ---------------------------------------------------------------------------
# 3. pre_queries 3단 폴백
# ---------------------------------------------------------------------------

def _raw_turn(no, question, **extra):
    turn = {
        "turn": no, "user_question": question, "llm_response": f"답변 {no}",
        "retrieved_data": "[]", "trace_matched": "True",
    }
    turn.update(extra)
    return turn


def _conv(*turns):
    return parse_conversations({"users": [{
        "db_dept_name": "부서", "db_job_name": "직무", "job_grade": "직급",
        "conversations": [{"chat_id": "c1", "turns": list(turns)}],
    }]})[0]


def test_history_chat_replaces_reconstruction():
    conv = _conv(
        _raw_turn(1, "질문 1"),
        _raw_turn(2, "질문 2", history_input={"history_chat": [
            {"role": "user", "content": "질문 1"}]}),
        _raw_turn(3, "불만", llm_eval_result="명시적 부정 피드백"),
    )
    case = to_case(conv, 3)
    assert case.pre_queries == ["질문 1", "질문 2"]


def test_the_criticized_question_is_appended():
    """history_chat 은 ~N-1 이라 비판받은 답변을 부른 질문이 들어 있지 않다.

    그냥 갈아끼우면 **제일 중요한 질문 하나가 빠진다.** pre_queries[-1] 을 보는
    pii 검증기도 거기서 무너진다.
    """
    conv = _conv(
        _raw_turn(1, "질문 1"),
        _raw_turn(2, "질문 2"),
        _raw_turn(3, "질문 3", history_input={"history_chat": [
            {"role": "user", "content": "질문 1"},
            {"role": "user", "content": "질문 2"}]}),
        _raw_turn(4, "불만", llm_eval_result="명시적 부정 피드백"),
    )
    case = to_case(conv, 4)
    assert case.pre_queries[-1] == "질문 3"


@pytest.mark.parametrize("value,expected", [
    (["앞 1", "앞 2"], ["앞 1", "앞 2", "질문 2"]),
    ("앞 1", ["앞 1", "질문 2"]),
])
def test_prev_question_is_the_second_tier(value, expected):
    """history_chat 이 없으면 prev_question. str 로도 list 로도 온다."""
    conv = _conv(
        _raw_turn(1, "질문 1"),
        _raw_turn(2, "질문 2", prev_question=value),
        _raw_turn(3, "불만", llm_eval_result="명시적 부정 피드백"),
    )
    assert to_case(conv, 3).pre_queries == expected


def test_turn_order_remains_the_third_tier():
    """골든셋 픽스처에는 두 필드가 다 없다. 2단으로 끊으면 골든셋이 회귀한다."""
    conv = _conv(
        _raw_turn(1, "질문 1"),
        _raw_turn(2, "질문 2"),
        _raw_turn(3, "불만", llm_eval_result="명시적 부정 피드백"),
    )
    assert to_case(conv, 3).pre_queries == ["질문 1", "질문 2"]


def test_facts_are_not_capped_by_history_turns():
    """상한은 추정이 넓게 틀리는 것을 막으려고 둔 것이다.

    history_chat 은 추정이 아니라 챗봇이 실제로 본 것이라, 자르면 못 본 턴 대신
    **본 턴**을 지우게 된다.
    """
    chat = [{"role": "user", "content": f"질문 {i}"} for i in range(1, 9)]
    conv = _conv(
        _raw_turn(1, "질문 1"),
        _raw_turn(2, "질문 2", history_input={"history_chat": chat}),
        _raw_turn(3, "불만", llm_eval_result="명시적 부정 피드백"),
    )
    case = to_case(conv, 3, history_turns=2)
    assert len(case.pre_queries) == 9


def test_turn_order_tier_still_respects_the_cap():
    conv = _conv(
        *[_raw_turn(n, f"질문 {n}") for n in range(1, 6)],
        _raw_turn(6, "불만", llm_eval_result="명시적 부정 피드백"),
    )
    assert to_case(conv, 6, history_turns=2).pre_queries == ["질문 4", "질문 5"]


# ---------------------------------------------------------------------------
# 4. 청크 풀
# ---------------------------------------------------------------------------

def test_history_chunks_join_the_pool():
    """끌려온 턴의 retrieved_data 가 들어온다 - 2026-10 의 전제가 뒤집혔다.

    이 집합이 넓어지면 case20(문서에 없었다)이 case22(있었는데 안 썼다)로 옮겨
    간다. 고칠 곳이 문서팀에서 생성 쪽으로 바뀐다.
    """
    conv = _conv(
        _raw_turn(1, "질문 1"),
        _raw_turn(2, "질문 2",
                  retrieved_data='["이번 턴 문서"]',
                  tool_output="이번 턴 도구",
                  history_input={"retrieved_data": '["앞 턴 문서"]',
                                 "tool_output": STRUCTURED}),
        _raw_turn(3, "불만", llm_eval_result="명시적 부정 피드백"),
    )
    pool = to_case(conv, 3).rag_chunks
    assert pool[:2] == ["이번 턴 문서", "이번 턴 도구"], "턴 N 것이 먼저다"
    assert "앞 턴 문서" in pool
    assert '{"hit": 1}' in pool


def test_carried_turns_are_not_walked_twice():
    """history_input 이 ~N-1 을 통째로 들고 있다. 턴을 또 돌면 중복이 생기고,
    중복 청크는 인용 대조에서 index_corrected 를 양산한다."""
    conv = _conv(
        _raw_turn(1, "질문 1", tool_output="앞 턴 도구"),
        _raw_turn(2, "질문 2", carried_turn_nos=[1],
                  history_input={"tool_output": [
                      {"turn_no": 1, "outputs": ["앞 턴 도구"]}]}),
        _raw_turn(3, "불만", llm_eval_result="명시적 부정 피드백"),
    )
    pool = to_case(conv, 3).rag_chunks
    assert pool.count("앞 턴 도구") == 1


def test_old_logs_keep_walking_carried_turns():
    """history_input 이 없으면 옛 경로다. 골든셋이 여기로 간다."""
    conv = _conv(
        _raw_turn(1, "질문 1", tool_output="앞 턴 도구"),
        _raw_turn(2, "질문 2", carried_turn_nos=[1]),
        _raw_turn(3, "불만", llm_eval_result="명시적 부정 피드백"),
    )
    assert "앞 턴 도구" in to_case(conv, 3).rag_chunks


def test_empty_history_input_does_not_fall_back():
    """있는데 비었으면 서비스가 정말 아무것도 안 넣은 것이다. 추정하면 안 된다."""
    conv = _conv(
        _raw_turn(1, "질문 1", tool_output="앞 턴 도구"),
        _raw_turn(2, "질문 2", carried_turn_nos=[1], history_input={}),
        _raw_turn(3, "불만", llm_eval_result="명시적 부정 피드백"),
    )
    assert to_case(conv, 3).rag_chunks == []


# ---------------------------------------------------------------------------
# 5. memory · 라우팅 필드
# ---------------------------------------------------------------------------

def test_memory_merges_both_sources():
    turn = _conv(_raw_turn(1, "질문", memory="턴 요약",
                           history_input={"memory": "앞 요약"})).turns[0]
    merged = memory_pool(turn)
    assert "턴 요약" in merged and "앞 요약" in merged


def test_memory_does_not_duplicate_a_contained_summary():
    turn = _conv(_raw_turn(1, "질문", memory="앞 요약 + 더",
                           history_input={"memory": "앞 요약"})).turns[0]
    assert memory_pool(turn) == "앞 요약 + 더"


def test_routing_fields_are_parsed_but_unused():
    """받아만 둔다. 값의 모양을 한 사이클 회수한 뒤에 쓸지 정한다."""
    turn = _conv(_raw_turn(1, "질문", ask_on="platform_a", answered_by="platform_b",
                           route_intent="search", fallback="true")).turns[0]
    assert (turn.ask_on, turn.answered_by) == ("platform_a", "platform_b")
    assert (turn.route_intent, turn.fallback) == ("search", "true")


def test_pre_queries_is_empty_when_there_is_nothing_to_say():
    assert pre_queries(_conv(_raw_turn(1, "")).turns[0], []) == []


def test_history_input_defaults_are_not_shared():
    """default_factory 를 안 쓰면 턴들이 같은 리스트를 공유한다."""
    a, b = HistoryInput(), HistoryInput()
    a.queries.append("x")
    assert b.queries == []


# ---------------------------------------------------------------------------
# 6. 드라이런 계측 — LLM 을 켜기 전에 풀 크기가 보여야 한다
# ---------------------------------------------------------------------------

def test_dry_run_prints_the_pool_size(tmp_path, capsys):
    """에어갭에서 풀이 터지면 ⑦ 가 깨지면서 알게 되고, 그때 GPU 시간은 이미 썼다.

    드라이런 숫자는 LLM 을 안 켜고 나온다. 상한을 걸지 말지를 이걸 보고 정한다.
    """
    import json
    from ragdiag.__main__ import main

    raw = {"users": [{
        "db_dept_name": "부서", "db_job_name": "직무", "job_grade": "직급",
        "conversations": [{"chat_id": "c1", "turns": [
            _raw_turn(1, "질문 1", retrieved_data='["문서 하나"]'),
            _raw_turn(2, "질문 2", retrieved_data='["문서 둘", "문서 셋"]',
                      history_input={"retrieved_data": '["앞 턴 문서"]'}),
            _raw_turn(3, "불만", llm_eval_result="명시적 부정 피드백"),
        ]}],
    }]}
    log = tmp_path / "log.json"
    log.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    assert main(["--conv-data", str(log), "--dry-run",
                 "--output-dir", str(tmp_path / "out")]) == 0
    err = capsys.readouterr().err
    assert "청크 풀 (LLM 호출 없음)" in err
    assert "청크 개수" in err and "문자 수" in err
    # 앞 턴 문서가 풀에 들어왔는지까지 본다 - 숫자가 찍히기만 하고 history_input
    # 쪽이 빠지면 "안 커졌다" 는 틀린 결론이 나온다.
    assert "최대 3.0" in err  # 턴 N 문서 2개 + history_input 1개
    # RUN SUMMARY 의 chunks 줄은 atexit 로 나가서 capsys 에 안 잡힌다.
    # 그쪽은 test_survey.py 의 chunk_metric 단위 테스트가 본다.


# ---------------------------------------------------------------------------
# 7. Case.n_fetched — 이 턴이 가져온 것만 센다
# ---------------------------------------------------------------------------

def test_n_fetched_excludes_history_input():
    conv = _conv(
        _raw_turn(1, "질문 1"),
        _raw_turn(2, "질문 2",
                  retrieved_data="[]",              # 이번 턴 검색 0건
                  history_input={"retrieved_data": '["과거 문서"]'}),
        _raw_turn(3, "불만", llm_eval_result="명시적 부정 피드백"),
    )
    case = to_case(conv, 3)
    assert len(case.rag_chunks) == 1, "풀에는 과거 문서가 들어간다"
    assert case.n_fetched == 0, "이 턴이 가져온 것은 0 이다 - case21 은 이걸 본다"


def test_n_fetched_counts_this_turn_docs_and_tools():
    conv = _conv(
        _raw_turn(1, "질문 1"),
        _raw_turn(2, "질문 2", retrieved_data='["a", "b"]', tool_output="c"),
        _raw_turn(3, "불만", llm_eval_result="명시적 부정 피드백"),
    )
    assert to_case(conv, 3).n_fetched == 3
