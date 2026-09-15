"""판정자가 "문서에 답이 있다"며 댄 인용이 정말 그 문서에 있는지 대조한다.

사전지식 오염을 여기서 막는다. 판정자가 업무 규정을 "아는" 것처럼 답하면 인용할
원문이 없어 걸러지고, 살아남은 인용이 없으면 verdict 가 insufficient 로 강등된다
(verify.final_verdict). 프롬프트로 "지어내지 마라"라고 부탁하는 대신 구조로 막는
장치라, 판정 모델이 바뀌어도 무너지지 않는다.
"""

from ragdiag.verify import verify_evidence

from .._shared import each_turn

NAME = "citation"


def process_data(ctx) -> tuple[list, list]:
    def verify(turn):
        turn.citation = verify_evidence(turn.judgment.evidence, turn.case.rag_chunks)

    each_turn(ctx, NAME, verify, where=lambda t: t.judgment is not None)
    return [], []
