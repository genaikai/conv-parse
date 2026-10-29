"""불만 판정 — 사용자가 무엇을 불평했나. kev 8문항을 한 요청에 묻고 코드가 순서로 읽는다.

입력은 넷뿐이다: history(앞 대화) · question · answer · followup. 문서 · 도구 결과 · memory 는
주지 않는다 — 주면 kev 가 "답이 맞았나" 를 재기 시작하고 그건 근거 판정의 일이다.

kev 는 여덟을 각각 독립으로 채점한다. 순서(문제 삼지 않으면 나머지가 뭐라 했든 정상)는 코드가
읽는다. 모름은 그 문항에서 멈춰 검토로 — 다음 문항으로 흘리면 "어디서 막혔나" 가 안 보인다.
여덟 답은 멈춘 뒤의 것까지 전부 남긴다. kev 가 한 번에 준 것이고 검토할 때 "뒤는 뭐라 했나"
가 보여야 한다. (docs/design/decision_tree_v4.md "불만 판정")
"""

from __future__ import annotations

from ragdiag import questions, taxonomy
from ragdiag.results import NO, UNSURE, YES, StepResult, answer_payload, read_noul

from .._shared import call_kev, each_turn

NAME = "complaint"


def state_of(case) -> dict:
    return {
        "history": list(case.history_messages),
        "question": case.last_query,
        "answer": case.llm_ans_on_last_q,
        "followup": case.current_query,
    }


def read(answers: dict) -> tuple[str | None, str | None, float | None]:
    """순서대로 읽어 처음 걸리는 데서 멈춘다.

    돌려주는 것: (묶음 id, because 키, None) 로 닫힘 · (None, None, None) 으로 다음 단계 ·
    ("review", 문항 id, p) 로 검토.
    """
    for qid in questions.COMPLAINT:
        verdict = read_noul(answers[qid])
        if verdict == UNSURE:
            return taxonomy.REVIEW, qid, answers[qid].p
        on_yes, on_no = questions.COMPLAINT_ROUTE[qid]
        bucket = on_yes if verdict == YES else on_no
        if bucket:
            return bucket, f"{qid}:{'yes' if verdict == YES else 'no'}", None
    return None, None, None


def _apply(turn, ctx) -> None:
    answers = call_kev(turn, ctx, "complaint", state_of(turn.case), questions.COMPLAINT)
    turn.steps.append(StepResult(step=taxonomy.STEP_COMPLAINT,
                                 answers={qid: answer_payload(answers[qid])
                                          for qid in questions.COMPLAINT}))
    bucket, key, p = read(answers)
    if bucket == taxonomy.REVIEW:
        turn.review(taxonomy.STEP_COMPLAINT, key, p)
    elif bucket:
        turn.close(bucket, taxonomy.STEP_COMPLAINT,
                   taxonomy.BECAUSE[f"{taxonomy.STEP_COMPLAINT}:{key}"])


def process_data(ctx) -> tuple[list, list]:
    each_turn(ctx, NAME, lambda t: _apply(t, ctx), parallel=True)
    return [], []
