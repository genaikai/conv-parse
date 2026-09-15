"""[임시] 지금의 판정 순서(classify_turn)를 기능 하나로 감싼다.

다음 단계에서 short_circuit · observe · … · route 로 쪼개지고 이 폴더는 지워진다.
틀(RunContext · 등록부)을 먼저 바꾸고 판정은 그대로 둬서, 한 번에 한 가지만 바뀌게 한다.
"""

from ragdiag.classify import classify_all

NAME = "classify"


def process_data(ctx) -> tuple[list, list]:
    turns = ctx.open_turns()
    if not turns:
        return [], []
    results = classify_all([t.case for t in turns], ctx.judge,
                           max_workers=max(1, ctx.workers))
    where = {id(t): i for i, t in enumerate(ctx.turns)}
    for turn, result in zip(turns, results):
        ctx.turns[where[id(turn)]] = result
    return [], []
