"""진리표 — 관측과 검증을 조합해 case 를 정한다. LLM 없음.

판정 순서와 그 이유는 table.py 에 있다. 이 파일은 열린 턴마다 그 표를 적용하기만 한다.

진리표를 기능 여럿으로 흩지 않는 이유: 순서가 곧 규칙이다. 답변이 나쁘면 여러 관측이
동시에 켜지므로 무엇을 먼저 묻느냐가 결과를 정한다 - 약한 증거(LLM 의 인상)가 강한
증거(인용으로 검증된 문서)를 가로챈 결함이 실제로 여러 번 났고, 전부 순서 문제였다.
"""

from .._shared import each_turn
from .table import route, secondary_from

__all__ = ["NAME", "process_data", "route", "secondary_from"]

NAME = "route"


def process_data(ctx) -> tuple[list, list]:
    def decide(turn):
        turn.classification = route(turn.observation, turn.checks, turn.judgment,
                                    turn.citation, turn.grounding,
                                    complaint=turn.complaint)

    each_turn(ctx, NAME, decide)
    return [], []
