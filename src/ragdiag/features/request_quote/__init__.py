"""판정자가 적은 요구(언어 · 형식 · 길이)가 이전 질문들에 실제로 있는지 확인한다.

요구는 비판받은 답변이 **따를 수 있었던 것**이어야 한다 - 그 답변을 부른 질문과 그 앞의
질문들에 적힌 것만이다. 후속 발화에서 처음 나온 요구("표로 정리해 주세요")를 요구로
세면, 답할 때는 없던 요구를 어긴 것이 되어 case10 · case12 가 high 신뢰도로 잘못 나간다.
골든셋에서 Opus 도 Haiku 도 그렇게 적었다.

**확인 방법을 바꿨다 (2026-09).** 전에는 판정자에게 근거 구절을 베껴 적게 하고 원문과
대조했다. 강한 모델에서는 돌았지만 약한 모델에서 뒤집혔다:

  Qwen3.5-9B 실측 (골든셋 145건)
    requested_format 을 맞게 읽고도 requested_quote 를 비운 경우   27건 중 27건
    → 대조가 전부 떨어져 **맞는 요구가 지워졌다** (fmt01 · fmt02 · req04 …)

대조 규칙은 "인용을 못 대면 요구가 없었다" 를 전제한다. 약한 모델은 베끼는 일 자체를
안 하므로 그 전제가 깨지고, 규칙이 지어낸 요구가 아니라 맞는 요구를 지운다.

이제 `ragdiag.requests` 가 코드로 확인한다 - 판정자에게 증거를 요구하지 않는다.
막으려던 병은 그대로 막힌다: 후속 발화에서 처음 나온 요구는 이전 질문에 그 어휘가 없다.

인용은 여전히 받아 기록한다(`request_quote_verified`). 판정에는 안 쓰지만, 실데이터에서
어느 모델이 인용을 얼마나 적는지가 다음 판단의 근거가 된다.

**셋을 따로 지운다.** 전에는 인용 하나가 떨어지면 언어 · 형식 · 길이를 한꺼번에
지웠다. 서로 독립된 요구라 하나가 틀렸다고 나머지까지 없앨 이유가 없다.
"""

from ragdiag.requests import (
    format_is_supported,
    language_was_requested,
    length_was_requested,
)
from ragdiag.verify import verify_request_quote

from .._shared import each_turn

NAME = "request_quote"


def asked(obs) -> bool:
    return (bool(obs.requested_language) or obs.requested_format != "none"
            or obs.requested_length_kind != "none")


def unsupported(obs, questions: list[str]) -> dict:
    """이전 질문들이 받쳐 주지 않는 요구를 되돌릴 값. 받쳐 주면 빈 dict."""
    wipe: dict = {}
    if obs.requested_format != "none" and not format_is_supported(
            obs.requested_format, questions):
        wipe["requested_format"] = "none"
    if obs.requested_language and not language_was_requested(questions):
        wipe["requested_language"] = ""
    if obs.requested_length_kind != "none" and not length_was_requested(questions):
        wipe["requested_length_kind"] = "none"
        wipe["requested_length_value"] = 0
    return wipe


def corrected(obs, questions: list[str]):
    """(확인을 거친 관측, 인용 대조 결과). 요구가 없었으면 대조 결과는 None.

    인용 대조 결과는 기록용이다 - 판정은 위 `unsupported` 가 한다.
    """
    if not asked(obs):
        return obs, None
    check = verify_request_quote(obs.requested_quote, questions)
    wipe = unsupported(obs, questions)
    return (obs.model_copy(update=wipe) if wipe else obs), check


def process_data(ctx) -> tuple[list, list]:
    def verify(turn):
        turn.observation, turn.request = corrected(turn.observation, turn.case.pre_queries)

    each_turn(ctx, NAME, verify, where=lambda t: asked(t.observation))
    return [], []
