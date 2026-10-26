"""① 읽을 수 있는 글인가 — 답변만 보고 결정 백엔드(kev) 가 한 번 답한다. 아니면 I2 로 끝.

코드 규칙(short_circuit/degenerate)은 5555… 나 !!!!… 처럼 오탐이 없는 모양만 잡는다.
토큰 잡탕, 앞은 멀쩡하고 중간부터 깨진 것, 문단이 조금씩 바뀌며 되풀이되는 것은 규칙으로
열거할 수 없다. 그래서 여기서는 **답변만 주고** "읽을 수 없는가" 하나를 묻는다.

질문 · 불만 · 문서를 주지 않는 이유: 주면 "질문에 맞는 답인가" 를 재기 시작하고, 그러면
부실한 답변까지 붕괴로 세어 D1 · G5 가 통째로 사라진다.

v2 는 판정자에게 깨진 구절을 인용하게 하고 코드가 대조했다. v3 는 kev 의 보정된 확률이
그 자리다 — p ≥ kev_confident 면 등급 2 로 닫고, 그 아래면 닫지 않고 p 만 남긴다
(기울어진 p 는 중재에서 등급 1 후보가 된다). 채팅 템플릿 토큰이 답변에 있으면 kev 를 묻지
않고 코드 확정(등급 4)이다 — 정상 답변에는 절대 없는 토큰이다.
"""

import re

from ragdiag import questions, settings

from .._shared import call_kev, each_turn, grade_from_p

NAME = "legibility"

_TEMPLATE = re.compile(r"<\|im_start\|>|<\|endoftext\|>|<\|im_end\|>|<think>|\{\{\s*\w+\s*\}\}")


def process_data(ctx) -> tuple[list, list]:
    if not settings.LEGIBILITY:
        return [], []

    def judge(turn):
        from ..arbitrate import close

        answer = turn.case.llm_ans_on_last_q
        if not answer.strip():
            return                                   # 빈 답변은 읽기의 문제가 아니다
        if _TEMPLATE.search(answer):
            turn.legibility_p = 1.0
            close(turn, "I2", 4, "채팅 템플릿 토큰이 답변에 그대로 있음",
                  notes=["정상 답변에는 절대 없는 토큰이다. 모델 · 서빙 쪽 문제다."])
            return
        answers = call_kev(turn, ctx, "legibility", {"답변": answer}, questions.LEGIBILITY)
        p = answers["illegible"].p
        turn.legibility_p = p
        if grade_from_p(p) >= 2:
            close(turn, "I2", 2, f"읽을 수 없는 답변 (p={p:.2f})",
                  notes=["결정 백엔드가 답변만 보고 판정했다. 관측 · 충족도 · 근거 활용은 돌지 않았다.",
                         "모델이 답을 만들다 무너졌다. 검색 · 생성 품질이 아니라 모델 · 서빙 쪽 문제다."])

    each_turn(ctx, NAME, judge, parallel=True)
    return [], []
