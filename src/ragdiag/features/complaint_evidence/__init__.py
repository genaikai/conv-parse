"""불만 부분 근거 판정 — 근거가 **일부**일 때만 돈다. kev 1문항.

질문이 둘을 묻고 근거가 하나만 덮었을 때, 사용자가 **빠진 쪽**을 불평했으면 근거, **있던 쪽**을
틀렸다고 불평했으면 생성이다. 근거 판정은 후속 발화를 안 봐서 이 둘을 못 가른다.

근거 판정의 여섯째 문항으로 넣지 않고 따로 요청하는 이유: 같은 요청에 넣으면 state 에 후속
발화가 들어가 근거 판정 다섯 문항 전부가 불만을 본 채로 채점된다. 답변은 여기서도 안 준다 —
"1.5 가 아닌데요" 가 질문의 어느 부분인지는 질문과 후속으로 잡힌다.
(docs/design/decision_tree_v4.md "불만 부분 근거 판정")

여기 오는 턴은 근거 판정이 "일부" 로 열어 둔 것뿐이다 — 등록부 순서가 보장한다.
"""

from __future__ import annotations

from ragdiag import questions, second, taxonomy
from ragdiag.results import NO, UNSURE, YES, StepResult, answer_payload, read_noul

from .._shared import call_kev, each_turn
from ..evidence import slots_of, state_of

NAME = "complaint_evidence"


def _apply(turn, ctx) -> None:
    case = turn.case
    state = {**state_of(case, slots_of(case)), "followup": case.current_query}
    answers = call_kev(turn, ctx, "complaint_evidence", state, questions.COMPLAINT_EVIDENCE)
    turn.steps.append(StepResult(step=taxonomy.STEP_COMPLAINT_EVIDENCE,
                                 answers={"targeted": answer_payload(answers["targeted"])}))
    verdict = read_noul(answers["targeted"])
    if verdict == UNSURE:
        verdict = second.ask(turn, ctx, taxonomy.STEP_COMPLAINT_EVIDENCE, "targeted",
                             questions.COMPLAINT_EVIDENCE["targeted"], state, answers["targeted"]) or UNSURE
    if verdict == UNSURE:
        turn.review(taxonomy.STEP_COMPLAINT_EVIDENCE, "targeted", answers["targeted"].p)
        return
    key = "targeted:yes" if verdict == YES else "targeted:no"
    turn.close("generation" if verdict == YES else "evidence", taxonomy.STEP_COMPLAINT_EVIDENCE,
               taxonomy.BECAUSE[f"{taxonomy.STEP_COMPLAINT_EVIDENCE}:{key}"],
               where=_where(turn, present=verdict == YES))


def _where(turn, present: bool) -> list[str]:
    """근거 판정이 남긴 칸별 답에서 — 생성이면 답이 있던 칸, 근거면 비었거나 없던 칸."""
    step = next((s for s in turn.steps if s.step == taxonomy.STEP_EVIDENCE), None)
    answers = step.answers if step and step.answers else {}
    out = []
    for slot, korean in questions.SLOTS:
        a = answers.get(f"in_{slot}")
        said = a["answer"] if isinstance(a, dict) else None     # 문자열이면 비어 있어 묻지 않음
        if present and said == YES:
            out.append(korean)
        if not present and (said is None or said == NO):
            out.append(korean)
    return out


def process_data(ctx) -> tuple[list, list]:
    each_turn(ctx, NAME, lambda t: _apply(t, ctx), parallel=True)
    return [], []
