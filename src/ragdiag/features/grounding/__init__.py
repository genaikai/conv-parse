"""Step 3 — 근거 활용. **답변이 그 문서를 썼는가**, 그것 하나만 묻는다.

문서가 충분했을 때(인용 대조까지 통과)만 의미가 있다. 문서가 부족했다면 답변이
문서를 썼는지 물을 이유가 없다.

질문(Step 1 의 resolved_question)은 주고, 불만 원문과 Step 2 의 verdict 는 주지 않는다.
질문이 없으면 "아무 청크나 썼는가" 가 되어, 요구에 답하는 청크는 두고 다른 청크를 쓴 답변을
used 로 읽는다 - case22(문서에 답이 있는데 안 씀)가 그 자리에서 사라진다. 질문은 어느 청크가
관련 있는지 보는 용도로만 쓰라고 못 박는다 (docs/design/grounding_step.md).
"""

from ragdiag.verify import final_verdict

from .._shared import call_llm, each_turn

NAME = "grounding"


def applies(turn) -> bool:
    return (turn.judgment is not None
            and final_verdict(turn.judgment, turn.citation) == "sufficient")


def process_data(ctx) -> tuple[list, list]:
    def check(turn):
        turn.grounding = call_llm(
            turn, ctx.judge.check_grounding(turn.case, turn.observation.resolved_question))

    each_turn(ctx, NAME, check, where=applies, parallel=True)
    return [], []
