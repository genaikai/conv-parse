"""Step 1 — 관측. 사용자가 무엇을 원했고 무엇을 못 받았는지를 사실로만 적는다.

case 를 고르지 않는다. 좁은 질문 여러 개로 나눠 묻고, 조합은 route 가 코드로 한다 -
한 번에 case 까지 물으면 판정자가 결론을 먼저 정하고 관측을 끼워 맞춘다.

문서(rag_chunks)는 주지 않는다. 문서를 먼저 보면 판정자가 "문서로 답할 수 있었나"를
기준으로 요구를 재구성해 충족도가 저절로 후해진다. 무엇을 주고 무엇을 감추는지는
prompts.observe_user_message 에 있다.
"""

from .._shared import call_llm, each_turn

NAME = "observe"


def process_data(ctx) -> tuple[list, list]:
    def observe(turn):
        turn.observation = call_llm(turn, ctx.judge.observe(turn.case))

    each_turn(ctx, NAME, observe, parallel=True)
    return [], []
