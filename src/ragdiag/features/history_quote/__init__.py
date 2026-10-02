"""판정자가 "이전 턴의 조건을 어겼다"(ignored) 고 할 때, 그 조건이 앞 질문들에 실제로 있는지.

ignored 는 case14(이전 턴 맥락 상실) 로 간다. 그런데 약한 모델은 답변이 부실하기만 해도
"조건을 어겼다" 로 읽는다 - 골든셋 halo02 에서 Haiku 가 실행마다 흔들렸다. 한 인상이 여러
칸을 켜는 전형이다. 어긴 조건이 적힌 앞 질문을 글자 그대로 대게 하고 여기서 대조한다.
request_quote 가 요구에 하는 일과 같다.

대조에 실패하면 주장을 false 로 되돌린다.

**요약 맥락(memory)도 대조 대상이다.** 서비스가 앞 턴을 원문으로 끌고 오지 않고 요약만
들고 있는 경우가 있는데, 그래도 챗봇은 그 조건을 본 것이다. 요약에만 남은 조건을 어긴
답변을 "조건이 없었다" 로 되돌리면 case14 를 놓친다. 요약은 판정 LLM 에는 안 넘기고
여기 코드 대조에만 쓴다 - 다른 LLM 이 쓴 해석이라 넘기면 우리 관측이 끌려간다.
"""

from ragdiag.verify import verify_history_quote

from .._shared import each_turn

NAME = "history_quote"


def claimed(obs) -> bool:
    return obs.answer_ignored_history


def corrected(obs, questions: list[str], memory: str = ""):
    """(대조를 거친 관측, 대조 결과). ignored 주장이 없었으면 대조 결과는 None."""
    if not claimed(obs):
        return obs, None
    # 마지막 질문은 뺀다 - 거기 적힌 조건을 어긴 것은 히스토리 문제가 아니다.
    # 요약 맥락은 턴이 아니라 대화 전체의 것이라 그 자름과 무관하게 더한다.
    sources = questions[:-1] + ([memory] if memory else [])
    check = verify_history_quote(obs.history_quote, sources)
    if check.verified:
        return obs, check
    return obs.model_copy(update=dict(answer_ignored_history=False)), check


def process_data(ctx) -> tuple[list, list]:
    def verify(turn):
        turn.observation, turn.history = corrected(
            turn.observation, turn.case.pre_queries, turn.case.memory)

    each_turn(ctx, NAME, verify, where=lambda t: claimed(t.observation))
    return [], []
