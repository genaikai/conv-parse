"""Step 3 — 근거 활용. **답변이 그 문서를 썼는가**, 그것 하나만 묻는다.

문서가 충분했을 때(인용 대조까지 통과)만 의미가 있다. 문서가 부족했다면 답변이
문서를 썼는지 물을 이유가 없다.

질문과 불만은 주지 않는다. 주면 "질문에 잘 답했나"라는 다른 판단이 섞여, 충족도와
같은 방향으로 쏠린 독립적이지 않은 두 번째 표가 된다.
"""

from ragdiag.verify import final_verdict

from .._shared import call_llm, each_turn

NAME = "grounding"


def applies(turn) -> bool:
    return (turn.judgment is not None
            and final_verdict(turn.judgment, turn.citation) == "sufficient")


def process_data(ctx) -> tuple[list, list]:
    def check(turn):
        turn.grounding = call_llm(turn, ctx.judge.check_grounding(turn.case))

    each_turn(ctx, NAME, check, where=applies, parallel=True)
    return [], []
