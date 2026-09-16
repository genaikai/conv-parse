"""판정자가 "이전 턴의 조건을 어겼다"(ignored) 고 할 때, 그 조건이 앞 질문들에 실제로 있는지.

ignored 는 case14(이전 턴 맥락 상실) 로 간다. 그런데 약한 모델은 답변이 부실하기만 해도
"조건을 어겼다" 로 읽는다 - 골든셋 halo02 에서 Haiku 가 실행마다 흔들렸다. 한 인상이 여러
칸을 켜는 전형이다. 어긴 조건이 적힌 앞 질문을 글자 그대로 대게 하고 여기서 대조한다.
request_quote 가 요구에 하는 일과 같다.

대조에 실패하면 주장을 false 로 되돌린다.
"""

from ragdiag.verify import verify_history_quote

from .._shared import each_turn

NAME = "history_quote"


def claimed(obs) -> bool:
    return obs.answer_ignored_history


def corrected(obs, questions: list[str]):
    """(대조를 거친 관측, 대조 결과). ignored 주장이 없었으면 대조 결과는 None."""
    if not claimed(obs):
        return obs, None
    # 마지막 질문은 뺀다 - 거기 적힌 조건을 어긴 것은 히스토리 문제가 아니다.
    check = verify_history_quote(obs.history_quote, questions[:-1])
    if check.verified:
        return obs, check
    return obs.model_copy(update=dict(answer_ignored_history=False)), check


def process_data(ctx) -> tuple[list, list]:
    def verify(turn):
        turn.observation, turn.history = corrected(turn.observation, turn.case.pre_queries)

    each_turn(ctx, NAME, verify, where=lambda t: claimed(t.observation))
    return [], []
