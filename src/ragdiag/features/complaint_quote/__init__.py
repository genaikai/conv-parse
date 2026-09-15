"""판정자가 "불만이 아니다"라고 할 때 든 근거가 후속 발화에 실제로 있는지 대조한다.

"문제 없음"은 판정자가 낼 수 있는 가장 쉬운 답이다. 근거로 든 구절을 원문과 대조하지
않으면 애매한 턴이 전부 그리로 새고, 모든 집계가 조용히 줄어든다. 근거를 못 대면
route 가 case0 으로 통과시키지 않는다 - citation 이 "문서에 답이 있다"는 주장에 하는
일과 같다.
"""

from ragdiag.verify import verify_complaint_quote

from .._shared import each_turn

NAME = "complaint_quote"


def process_data(ctx) -> tuple[list, list]:
    def verify(turn):
        turn.complaint = verify_complaint_quote(turn.observation.complaint_quote,
                                                turn.case.current_query)

    each_turn(ctx, NAME, verify, where=lambda t: t.observation.complaint_target == "none")
    return [], []
