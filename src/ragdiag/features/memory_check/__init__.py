"""⑤ memory 반영 — 서비스가 들고 있던 **사용자 정보**를 답변이 어떻게 다뤘나.

memory 는 사용자에 대한 정보(직무 · 상황 · 선호)이고, 모델은 답할 때 이것을 참고해야 한다.
관측 ② 에는 넣지 않는다 - 다른 LLM 이 쓴 해석이라 관측이 그쪽으로 끌려간다. 그래서 따로,
memory 와 답변만 주고(불만 · 문서 감춤) reflected / ignored / contradicted 한 칸을 묻는다.

C2 플래그(memory 가 이 대화의 것이 아님)가 선 턴에서는 묻지 않는다 — 틀린 memory 를 반영
안 한 것은 결함이 아니다.
"""

from ragdiag import questions

from .._shared import call_kev, each_turn

NAME = "memory_check"


def applies(turn) -> bool:
    return bool(turn.case.memory.strip()) and "C2" not in turn.flags


def process_data(ctx) -> tuple[list, list]:
    def judge(turn):
        answers = call_kev(turn, ctx, "memory",
                           {"사용자 정보(memory)": turn.case.memory,
                            "답변": turn.case.llm_ans_on_last_q}, questions.MEMORY)
        a = answers["memory_use"]
        turn.memory_use = a.choice
        turn.memory_p = a.p
        turn.probabilities["memory_use"] = a.as_dict()

    each_turn(ctx, NAME, judge, where=applies, parallel=True)
    return [], []
