"""⑥ 답변 일관성 — 이 답변이 앞 답변들과 같은 것에 대해 다른 사실을 말하나.

"앞 답변과 모순" 은 두 답변을 나란히 봐야 보인다. 관측 ② 는 앞 답변을 받지 않으므로
(받으면 관측이 끌려간다) 여기서 따로, 앞 답변마다 이 답변과 짝지어 묻는다. 불만 · 문서는
주지 않는다.

history_chat 의 assistant 메시지가 있을 때만 돈다. 결과는 앞 답변 인덱스 → P(모순) 이고,
최대 p 가 kev_confident 를 넘으면 G2[모순] 후보가 된다.
"""

from ragdiag import questions

from .._shared import call_kev, each_turn

NAME = "consistency"


def applies(turn) -> bool:
    return bool(turn.case.prior_answers)


def process_data(ctx) -> tuple[list, list]:
    def judge(turn):
        for i, prior in enumerate(turn.case.prior_answers):
            if not prior.strip():
                continue
            answers = call_kev(turn, ctx, "consistency",
                               {"앞 답변": prior, "이 답변": turn.case.llm_ans_on_last_q},
                               questions.CONSISTENCY)
            turn.consistency[i] = answers["contradicts"].p

    each_turn(ctx, NAME, judge, where=applies, parallel=True)
    return [], []
