"""끌려온 맥락 지표 — 우리 추정이 챗봇과 얼마나 어긋났나.

이 지표의 쓸모는 하나다. **그전 판정을 얼마나 믿을 수 있나**를 첫 실행에서
숫자로 말해 주는 것. 그래서 세는 방향(넓게 / 좁게)이 틀리면 안 된다 - 둘은
서로 다른 결함으로 이어진다.
"""

import json

from ragdiag.conv import parse_conversations
from ragdiag.features import carried


def _conv(carried_by_turn, tool_turns=(), n=5):
    turns = [{
        "turn": i,
        "user_question": f"q{i}",
        "llm_response": f"a{i}",
        "retrieved_data": "[]",
        "tool_output": json.dumps(["도구"]) if i in tool_turns else "[]",
        "carried_turn_nos": carried_by_turn.get(i, []),
    } for i in range(1, n + 1)]
    return parse_conversations({"users": [{
        "db_dept_name": "-", "job_grade": "-", "db_job_name": "-",
        "conversations": [{"conversation_id": "C", "turns": turns}],
    }]})


def test_matching_estimate_counts_as_same():
    """턴 5에서 최근 3개는 2·3·4 다. 그대로 끌려왔으면 어긋남이 아니다."""
    stat = carried.measure(_conv({5: [2, 3, 4]}))
    assert (stat["same"], stat["wider"], stat["narrower"]) == (1, 0, 0)


def test_we_saw_more_than_the_chatbot_is_the_dangerous_direction():
    """챗봇은 4번만 봤는데 우리는 2·3·4 를 봤다.

    우리만 본 질문에서 "앞에서 정한 조건" 을 찾으면 챗봇이 어길 수 없던 것을
    어겼다고 하게 된다 - case14 오탐이다.
    """
    stat = carried.measure(_conv({5: [4]}))
    assert stat["wider"] == 1 and stat["narrower"] == 0
    assert any("넓게" in line for _, line in carried.render(stat))


def test_we_saw_less_than_the_chatbot_is_the_missing_direction():
    """챗봇은 1번까지 봤는데 우리 창은 2·3·4 다. 1번의 조건을 놓친다."""
    stat = carried.measure(_conv({5: [1, 2, 3, 4]}))
    assert stat["narrower"] == 1 and stat["wider"] == 0


def test_a_log_without_the_field_says_so_instead_of_zero_percent():
    """필드가 없는 로그에서 '어긋남 0%' 로 보이면 안 된다.

    0% 는 "추정이 완벽했다" 로 읽힌다. 사실은 잴 수가 없었던 것이다.
    """
    stat = carried.measure(_conv({}))
    assert stat["seen"] == 0
    assert any("없음" in line for _, line in carried.render(stat))


def test_tool_output_share_is_reported():
    """이 비율이 크면 청크 풀이 통째로 달라졌다는 뜻이다 - case20 과 case22 가
    옮겨 다니므로 고칠 곳이 바뀐다."""
    stat = carried.measure(_conv({5: [4]}, tool_turns=(2, 4)))
    assert stat["with_tool"] == 2
    assert any("tool_output" in line for _, line in carried.render(stat))


def test_empty_input_renders_nothing():
    assert carried.render(carried.measure([])) == []
