"""판정자가 적은 요구(언어 · 형식 · 길이)가 이전 질문들에 실제로 있는지 대조한다.

요구는 비판받은 답변이 **따를 수 있었던 것**이어야 한다 - 그 답변을 부른 질문과 그 앞의
질문들에 적힌 것만이다. 후속 발화에서 처음 나온 요구("표로 정리해 주세요")를 요구로
세면, 답할 때는 없던 요구를 어긴 것이 되어 case10 · case12 가 high 신뢰도로 잘못 나간다.
골든셋에서 Opus 도 Haiku 도 그렇게 적었다.

판정자에게 요구가 적힌 구절을 이전 질문들에서 글자 그대로 따오게 하고 여기서 대조한다.
대조에 실패하면 요구를 없던 것으로 되돌린다. 뒤의 language · format · length 검증기는
되돌린 값을 읽는다 - 그래서 이 기능은 그 셋보다 앞에 있어야 한다.
"""

from ragdiag.verify import verify_request_quote

from .._shared import each_turn

NAME = "request_quote"

NO_REQUEST = dict(requested_language="", requested_format="none",
                  requested_length_kind="none", requested_length_value=0)


def asked(obs) -> bool:
    return (bool(obs.requested_language) or obs.requested_format != "none"
            or obs.requested_length_kind != "none")


def corrected(obs, questions: list[str]):
    """(대조를 거친 관측, 대조 결과). 요구가 없었으면 대조 결과는 None."""
    if not asked(obs):
        return obs, None
    check = verify_request_quote(obs.requested_quote, questions)
    return (obs if check.verified else obs.model_copy(update=NO_REQUEST)), check


def process_data(ctx) -> tuple[list, list]:
    def verify(turn):
        turn.observation, turn.request = corrected(turn.observation, turn.case.pre_queries)

    each_turn(ctx, NAME, verify, where=lambda t: asked(t.observation))
    return [], []
