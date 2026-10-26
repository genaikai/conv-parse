"""⑤ 관측 — 범주는 kev(②a), 문장은 일반 LLM(②b). 둘을 합쳐 Observation 하나.

라벨을 고르지 않는다. 좁은 질문 여러 개로 나눠 묻고, 조합은 arbitrate 가 코드로 한다 -
한 번에 라벨까지 물으면 판정자가 결론을 먼저 정하고 관측을 끼워 맞춘다.

문서 · memory · 앞 답변은 주지 않는다. 문서를 먼저 보면 "문서로 답할 수 있었나" 를 기준으로
요구를 재구성해 충족도가 저절로 후해지고, memory 와 앞 답변은 다른 LLM 의 해석이라 관측이
그쪽으로 끌려간다. 그 둘은 따로 묻는다 (memory_check · consistency).

②a 와 ②b 는 서로를 모른다. 둘 다 같은 입력을 받되 ②a 는 12 문항의 확률을, ②b 는
resolved_question · unmet_need · 요구값 · 조건 인용을 낸다. 확률은 turn.probabilities 에
그대로 남아 중재의 등급과 출력의 근거가 된다.
"""

from ragdiag import questions
from ragdiag.schema import Observation

from .._shared import call_kev, call_llm, each_turn

NAME = "observe"


def state_of(case) -> dict:
    return {
        "이전 질문들 (시간순, 마지막이 이번 답변을 부른 질문)": list(case.pre_queries) or ["(없음)"],
        "마지막 질문에 대한 챗봇 답변": case.llm_ans_on_last_q,
        "그 답변에 대한 사용자의 후속 발화": case.current_query,
    }


def merge(answers: dict, text) -> Observation:
    """kev 답 + LLM 텍스트 → Observation. 범주는 최빈 선택지, 예/아니오는 p ≥ 0.5."""
    def pick(qid: str) -> str:
        return answers[qid].choice

    def yes(qid: str) -> bool:
        return answers[qid].yes

    return Observation(
        reasoning=text.reasoning,
        resolved_question=text.resolved_question,
        unmet_need=text.unmet_need,
        complaint_target=pick("complaint_target"),
        complaint_quote="",
        question_domain=pick("question_domain"),
        question_clarity=pick("question_clarity"),
        question_multi_intent=yes("question_multi_intent"),
        answer_refused=yes("answer_refused"),
        answer_covers_all_intents=yes("answer_covers_all_intents"),
        answer_actionable=yes("answer_actionable"),
        answer_ignored_history=yes("answer_ignored_history"),
        answer_asked_back=yes("answer_asked_back"),
        history_quote=text.history_quote,
        requests_unsupported_output=yes("requests_unsupported_output"),
        requested_language=text.requested_language,
        requested_length_kind=pick("requested_length_kind"),
        requested_length_value=text.requested_length_value,
        requested_format=pick("requested_format"),
        requested_quote="",
    )


def process_data(ctx) -> tuple[list, list]:
    def observe(turn):
        state = state_of(turn.case)
        answers = call_kev(turn, ctx, "observe", state, questions.OBSERVE)
        text = call_llm(turn, ctx.judge.observe_text(turn.case))
        turn.observation = merge(answers, text)
        turn.probabilities.update({qid: a.as_dict() for qid, a in answers.items()})

    each_turn(ctx, NAME, observe, parallel=True)
    return [], []
