"""골든셋 · 합성 로그 픽스처.

픽스처는 **실행 로그의 현재 모양**을 들고 있어야 한다. 옛 모양을 들고 있으면 거기서만
통과하는 코드가 생긴다 - 2026-10 에 user_id 가 빠졌을 때 그 단언을 넣었고, 같은 달에
history_input 이 들어왔을 때 같은 이유로 여기를 고쳤다.
"""


def context_fields(prior: list[dict], *, ask_on: str = "portal") -> dict:
    """2026-10 포맷의 맥락 필드 한 벌. `prior` 는 이 턴 **앞의** 턴들이다 (로그 dict).

    history_input 을 앞 턴들에서 만든다 - 질문·답변이 history_chat 으로, 그 턴들의
    retrieved_data 가 안쪽 retrieved_data 로. 골든셋의 앞 턴은 문서가 없어 보통 비지만,
    비는 것과 없는 것은 다른 사실이라 키는 언제나 둔다. 첫 턴(prior 가 없음)은 null -
    실제 로그가 그렇다.

    **창을 두지 않는다.** history_chat 은 서비스가 모델에 넣은 것 전부이고, 파이프라인은
    그 길이만큼 받는다. 최근 3턴으로 자르는 것은 history_input 이 **없을 때의** 폴백이다
    (settings.MAX_HISTORY_TURNS). 그래서 긴 대화 골든셋(hq03 · deep01)은 옛 창 밖의
    조건도 판정자에게 보이고, 기대값도 그렇게 매겨져 있다.

    라우팅 넷은 판정에 안 들어가므로 고정값이다.
    """
    import json

    nos = [t["turn"] for t in prior]
    chat = [m for t in prior
            for m in ({"role": "user", "content": t["user_question"]},
                      {"role": "assistant", "content": t["llm_response"]})]
    docs = []
    for t in prior:
        raw = t.get("retrieved_data")
        if isinstance(raw, str) and raw.strip() and raw.strip() != "[]":
            try:
                docs += json.loads(raw)
            except json.JSONDecodeError:
                docs.append(raw)
        elif isinstance(raw, list):
            docs += raw
    return {
        "tool_output": "",
        "memory": "",
        "carried_turn_nos": nos,
        "carried_turn_count": len(nos),
        "history_input": None if not prior else {
            "history_chat": chat,
            "memory": "",
            "retrieved_data": json.dumps(docs, ensure_ascii=False) if docs else "",
            "tool_output": [],
        },
        "prev_question": [t["user_question"] for t in prior] or None,
        "ask_on": ask_on,
        "answered_by": ask_on,
        "route_intent": "doc_search",
        "fallback": "false",
    }
