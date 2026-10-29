"""플래그 열 — 트리 밖. 판정에 안 끼어들고 멈추지 않는다 (docs/design/decision_tree_v4.md "플래그").

앞 턴 누락: 대화에 앞 턴이 있는데 history_chat 에 없다. 모델이 못 본 것인지 로그가 떨어뜨린
것인지 못 가르니 라벨이 아니라 열이다. 많이 서는 사이클은 사용자 행 집계를 보류한다.
history 재구성 턴 수: history_chat 이 비어 턴 순서로 되살린 턴 수 (conv.reconstruct_history).
질문에 개인정보: 사용자가 질문에 개인정보를 넣었다 — 답변의 성패와 독립인 사건.
"""

from __future__ import annotations

from .._shared import each_turn
from ..pii import find_pii

NAME = "integrity"

MISSING = "앞 턴 누락"
RECONSTRUCTED = "history 재구성 턴 수"
PII = "질문에 개인정보"
OLD_LOG = "옛 로그 — 판정 안 함"


def missing_prior_turns(case):
    """비판받은 턴 N 의 history_input 은 ~N-1 까지라, 대화에 N 보다 앞선 턴이 k 개면 history_chat
    의 user 메시지도 k 개여야 한다 (prior_turn_nos 에는 N 자신이 들어 있어 하나 뺀다). history_input
    이 없는 옛 로그는 판정하지 않는다 — 없음과 비었음은 다르다."""
    if not case.history_present:
        return OLD_LOG
    expected = max(len(case.prior_turn_nos) - 1, 0)
    return case.history_turn_count < expected


def _apply(turn) -> None:
    case = turn.case
    turn.flags = {
        MISSING: missing_prior_turns(case),
        RECONSTRUCTED: case.history_reconstructed,
        PII: bool(find_pii(case.last_query)),
    }


def process_data(ctx) -> tuple[list, list]:
    each_turn(ctx, NAME, _apply)
    return [], []
