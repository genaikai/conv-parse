"""근거 판정 — turn N 이 볼 수 있었던 근거에 질문의 답이 있었나. kev 5문항 한 요청.

**답변과 후속 발화는 안 준다.** 근거 유무는 답변과 무관하고, 주면 kev 가 답의 옳고 그름을
잰다. 무엇을 불평했는지는 불만 판정이 이미 걸렀다.

칸 넷(이번 턴 검색 청크 · 이번 턴 도구 결과 · 앞 턴 근거 · 메모리)은 "어디에 있었나" 를 적을
뿐이고, 묶음은 **전체 문항 하나**(전부 · 일부 · 없음)가 정한다. 칸마다 따로 물으면 답이 두 칸에
반씩 걸친 복합 질문을 칸별 전부 아니오로 놓친다 — 전체 문항이 그 구멍을 막는다. 칸별이 모름이어도
묶음에 안 끼어든다. 네 칸이 전부 비면 kev 를 안 부르고 근거(빈 묶음)로 닫는다.
(docs/design/decision_tree_v4.md "근거 판정")
"""

from __future__ import annotations

from ragdiag import questions, taxonomy
from ragdiag.results import NO, UNSURE, YES, StepResult, answer_payload, read_choice, read_noul

from .._shared import call_kev, each_turn

NAME = "evidence"

ALL, PARTIAL, NONE = "all", "partial", "none"


def slots_of(case) -> dict[str, list[str]]:
    """칸 id → 내용. questions.SLOTS 의 순서."""
    return {
        "retrieved": list(case.retrieved_chunks),
        "tool": list(case.tool_chunks),
        "history": list(case.history_chunks),
        "memory": [case.memory] if case.memory.strip() else [],
    }


def state_of(case, slots: dict[str, list[str]]) -> dict:
    """question + 비어 있지 않은 칸만, 칸 이름은 한국어."""
    state = {"question": case.last_query}
    for slot, korean in questions.SLOTS:
        if slots[slot]:
            state[korean] = slots[slot]
    return state


def questions_for(slots: dict[str, list[str]]) -> dict[str, dict]:
    asked = {f"in_{slot}": questions.EVIDENCE_SLOT[f"in_{slot}"]
             for slot, _ in questions.SLOTS if slots[slot]}
    asked.update(questions.EVIDENCE_ANY)
    return asked


def _apply(turn, ctx) -> None:
    case = turn.case
    slots = slots_of(case)
    names = dict(questions.SLOTS)
    if not any(slots.values()):
        turn.steps.append(StepResult(step=taxonomy.STEP_EVIDENCE,
                                     answers={qid: questions.SKIPPED for qid in
                                              (*questions.EVIDENCE_SLOT, "any")}))
        turn.close("evidence", taxonomy.STEP_EVIDENCE,
                   taxonomy.BECAUSE[f"{taxonomy.STEP_EVIDENCE}:empty"],
                   where=[names[s] for s, _ in questions.SLOTS])
        return

    answers = call_kev(turn, ctx, "evidence", state_of(case, slots), questions_for(slots))
    payload = {qid: (answer_payload(answers[qid]) if qid in answers else questions.SKIPPED)
               for qid in (*questions.EVIDENCE_SLOT, "any")}
    turn.steps.append(StepResult(step=taxonomy.STEP_EVIDENCE, answers=payload))

    overall = read_choice(answers["any"])
    if overall == UNSURE:
        turn.review(taxonomy.STEP_EVIDENCE, "any", answers["any"].p)
        return
    present = [names[s] for s, _ in questions.SLOTS
               if f"in_{s}" in answers and read_noul(answers[f"in_{s}"]) == YES]
    absent = [names[s] for s, _ in questions.SLOTS
              if f"in_{s}" not in answers or read_noul(answers[f"in_{s}"]) == NO]
    if overall == ALL:
        turn.close("generation", taxonomy.STEP_EVIDENCE,
                   taxonomy.BECAUSE[f"{taxonomy.STEP_EVIDENCE}:any:all"], where=present)
    elif overall == NONE:
        turn.close("evidence", taxonomy.STEP_EVIDENCE,
                   taxonomy.BECAUSE[f"{taxonomy.STEP_EVIDENCE}:any:none"], where=absent)
    # PARTIAL: 열어 둔다. 불만 부분 근거 판정이 받는다.


def process_data(ctx) -> tuple[list, list]:
    each_turn(ctx, NAME, lambda t: _apply(t, ctx), parallel=True)
    return [], []
