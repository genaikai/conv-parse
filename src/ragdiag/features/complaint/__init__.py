"""불만 판정 — 사용자가 무엇을 불평했나. kev 8문항을 한 요청에 묻고 코드가 순서로 읽는다.

입력은 넷뿐이다: history(앞 대화) · question · answer · followup. 문서 · 도구 결과 · memory 는
주지 않는다 — 주면 kev 가 "답이 맞았나" 를 재기 시작하고 그건 근거 판정의 일이다.

kev 는 여덟을 각각 독립으로 채점한다. 순서(문제 삼지 않으면 나머지가 뭐라 했든 정상)는 코드가
읽는다. 모름은 그 문항에서 멈춰 검토로 — 다음 문항으로 흘리면 "어디서 막혔나" 가 안 보인다.
단, 2~8 의 아니오는 결론이 아니라 "다음 문항" 이라 기울기만 보고 넘긴다 (results.read_gate).
1 은 아니오가 정상(결론)이라 대칭 그대로다. 기울기로 넘긴 수는 플래그 열에 남는다.
여덟 답은 멈춘 뒤의 것까지 전부 남긴다. kev 가 한 번에 준 것이고 검토할 때 "뒤는 뭐라 했나"
가 보여야 한다. (docs/design/decision_tree_v4.md "불만 판정")
"""

from __future__ import annotations

from ragdiag import questions, second, taxonomy
from ragdiag.results import LEAN_NO, UNSURE, YES, StepResult, answer_payload, read_gate, read_noul

from .._shared import call_kev, each_turn
from ..integrity import LEAN

NAME = "complaint"


def state_of(case) -> dict:
    return {
        "history": list(case.history_messages),
        "question": case.last_query,
        "answer": case.llm_ans_on_last_q,
        "followup": case.current_query,
    }


def reader_of(qid: str):
    """1 은 대칭(아니오가 정상이라는 결론), 2~8 은 아니오가 다음 문항이라 기울기 읽기."""
    return read_noul if qid == "complains" else read_gate


def read(answers: dict, overrides: dict[str, str] | None = None
         ) -> tuple[str | None, str | None, float | None, int]:
    """순서대로 읽어 처음 걸리는 데서 멈춘다.

    돌려주는 것: (묶음 id, because 키, None, 기울기 수) 로 닫힘 · (None, None, None, 기울기 수) 로
    다음 단계 · ("review", 문항 id, p, 기울기 수) 로 검토. 기울기 수는 멈추기 전에 확신 없이
    아니오로 넘긴 문항 수다. overrides 는 2차 판정이 대신 낸 답(문항 id → 예/아니오).
    """
    lean = 0
    for qid in questions.COMPLAINT:
        verdict = (overrides or {}).get(qid) or reader_of(qid)(answers[qid])
        if verdict == UNSURE:
            return taxonomy.REVIEW, qid, answers[qid].p, lean
        lean += verdict == LEAN_NO
        on_yes, on_no = questions.COMPLAINT_ROUTE[qid]
        bucket = on_yes if verdict == YES else on_no
        if bucket:
            return bucket, f"{qid}:{'yes' if verdict == YES else 'no'}", None, lean
    return None, None, None, lean


def _apply(turn, ctx) -> None:
    state = state_of(turn.case)
    answers = call_kev(turn, ctx, "complaint", state, questions.COMPLAINT)
    turn.steps.append(StepResult(step=taxonomy.STEP_COMPLAINT,
                                 answers={qid: answer_payload(answers[qid], reader_of(qid))
                                          for qid in questions.COMPLAINT}))
    overrides: dict[str, str] = {}
    while True:
        bucket, key, p, lean = read(answers, overrides)
        if bucket != taxonomy.REVIEW:
            break
        # 모름 — 그 문항 하나를 LLM 에 다시 묻는다. 답이 오면 그 답으로 이어 읽고, 모름이면 검토.
        word = second.ask(turn, ctx, taxonomy.STEP_COMPLAINT, key, questions.COMPLAINT[key], state,
                          answers[key])
        if word is None:
            break
        overrides[key] = word
    turn.flags[LEAN] = lean
    if bucket == taxonomy.REVIEW:
        turn.review(taxonomy.STEP_COMPLAINT, key, p)
    elif bucket:
        turn.close(bucket, taxonomy.STEP_COMPLAINT,
                   taxonomy.BECAUSE[f"{taxonomy.STEP_COMPLAINT}:{key}"])


def process_data(ctx) -> tuple[list, list]:
    each_turn(ctx, NAME, lambda t: _apply(t, ctx), parallel=True)
    return [], []
