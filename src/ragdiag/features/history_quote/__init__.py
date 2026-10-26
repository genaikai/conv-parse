"""②b 가 적은 "앞 질문의 조건" 구절이 앞 질문들(과 memory)에 실제로 있는지 — 코드 대조.

kev 가 answer_ignored_history 를 예라고 해도 그것은 확률이다 (등급 2). 어긴 조건이 적힌
앞 질문을 ②b 가 글자 그대로 댔고 여기서 그 구절을 원문에서 찾으면 G2[조건] 은 등급 3 으로
올라간다. 못 찾으면 등급 2 에 머문다 — v2 처럼 주장을 지우지는 않는다. 확률이 있는데
인용이 없다는 이유로 지우면 약한 텍스트 모델이 맞는 판정을 끌어내린다.

마지막 질문은 뺀다 - 거기 적힌 조건을 어긴 것은 히스토리 문제가 아니라 의도를 잘못 읽은
것이다. memory 는 더한다 - 요약에만 남은 조건도 챗봇은 본 것이다.
"""

from ragdiag.verify import verify_history_quote

from .._shared import each_turn

NAME = "history_quote"


def process_data(ctx) -> tuple[list, list]:
    def verify(turn):
        obs = turn.observation
        if not obs.history_quote:
            return
        sources = turn.case.pre_queries[:-1] + ([turn.case.memory] if turn.case.memory else [])
        turn.history = verify_history_quote(obs.history_quote, sources)

    each_turn(ctx, NAME, verify)
    return [], []
