"""코드 확정 — kev 를 부르기 전에 코드가 턴을 닫는다 (docs/design/decision_tree_v4.md).

판정할 답이 없는 턴이다 — 자원 부족 문구 · 빈 답변 · 붕괴. kev 에 넣으면 판정자가 문구를
거절로 읽어 엉뚱한 묶음으로 보낸다. 셋 다 답변 문자열만 보고, 걸리면 확실하다. 다른 점은
놓치는 양이고, 붕괴가 못 잡는 토큰 잡탕 · 템플릿 토큰은 불만 판정의 "읽을 수 없는 글" 이 받는다.

규칙 하나가 파일 하나다: `NAME` 과 `check(answer) -> (걸렸나, 설명)`. 아래 RULES 가 순서다.
"""

from ragdiag import taxonomy
from ragdiag.results import StepResult

from .._shared import each_turn
from . import degenerate, empty_answer, service_error

NAME = "code_rules"

# 순서 = 우선순위. 처음 걸린 규칙이 닫고, 그 뒤 규칙은 보지 않는다.
RULES = (service_error, empty_answer, degenerate)

HIT, MISS, UNSEEN = "예", "아니오", "보지 않음"


def _apply(turn) -> None:
    answer = turn.case.llm_ans_on_last_q
    rules: dict[str, str] = {}
    hit = None
    for rule in RULES:
        if hit:
            rules[rule.NAME] = UNSEEN        # "봤는데 아니었다" 와 "안 봤다" 를 가른다
            continue
        caught, _detail = rule.check(answer)
        rules[rule.NAME] = HIT if caught else MISS
        if caught:
            hit = rule.NAME
    turn.steps.append(StepResult(step=taxonomy.STEP_CODE, rules=rules))
    if hit:
        turn.close("system", taxonomy.STEP_CODE, taxonomy.BECAUSE[f"{taxonomy.STEP_CODE}:{hit}"])


def process_data(ctx) -> tuple[list, list]:
    each_turn(ctx, NAME, _apply)
    return [], []
