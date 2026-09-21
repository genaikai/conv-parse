"""④′ 읽기 — 답변이 사람이 읽을 수 있는 글인가. 아니면 case30(생성 붕괴)으로 끝낸다.

코드 규칙(short_circuit/degenerate)은 5555… 나 !!!!… 처럼 오탐이 없는 모양만 잡는다.
토큰 잡탕, 앞은 멀쩡하고 중간부터 깨진 것, 문단이 조금씩 바뀌며 되풀이되는 것,
시스템 프롬프트가 새어 나온 것은 규칙으로 열거할 수 없다 - 예외를 쌓을수록 정상
답변(표 · 코드 · 영문)이 걸리기 시작한다. 그래서 여기서는 LLM 에 **답변만 주고**
"읽을 수 있는 글인가" 하나만 묻는다.

질문 · 불만 · 문서를 주지 않는 이유: 주면 "질문에 맞는 답인가" 를 재기 시작하고,
그러면 부실한 답변까지 붕괴로 세어 case20 · 22 가 통째로 사라진다. 유용한지는
Step 1 · 2 가 본다.

오탐 방어는 인용이다. 읽을 수 없다면 깨진 구절을 답변에서 따오게 하고 코드가 원문과
대조한다 - 못 대면 판정을 무효로 하고 아래 단계로 흘려보낸다 (⑧ 인용 대조와 같은
원리). 이 판정이 틀리면 그 턴의 진짜 원인은 아무 단계에서도 판정받지 못하므로,
확신이 없으면 legible 이라고 프롬프트에 못 박았다.

코드가 잡은 case30 은 신뢰도 high, 여기서 잡은 것은 medium 이다. 대시보드에서 색으로
갈린다.
"""

from ragdiag import settings
from ragdiag.results import Classification
from ragdiag.verify import verify_complaint_quote

from .._shared import call_llm, each_turn

NAME = "legibility"


def process_data(ctx) -> tuple[list, list]:
    if not settings.LEGIBILITY:
        return [], []

    def judge(turn):
        answer = turn.case.llm_ans_on_last_q
        if not answer.strip():
            return                                   # 빈 답변은 읽기의 문제가 아니다
        check = call_llm(turn, ctx.judge.check_legibility(turn.case))
        turn.legibility = check
        if check.legible:
            return
        # 답변 안의 구절인지 대조한다. 짧은 발화용 규칙이지만 여기서도 맞는 기준이다 -
        # 답변 전체를 따왔으면 받고, 조각이면 4자 이상이어야 하고, 말을 바꾸면 안 받는다.
        turn.legibility_quote = verify_complaint_quote(check.quote, answer)
        if not turn.legibility_quote.verified:
            return                               # 무효 - 결과 파일의 legibility 에 남는다
        turn.classification = Classification(
            primary_case="case30",
            confidence="medium",                     # 코드가 잡은 것(high)과 갈라 둔다
            reason=f"읽을 수 없는 답변 — {check.reasoning}",
            secondary_cases=[],
            notes=["LLM 이 답변만 보고 판정했다. 관측·충족도·근거 활용은 돌지 않았다.",
                   "모델이 답을 만들다 무너졌다. 검색·생성 품질이 아니라 모델·서빙 쪽 문제다."])

    each_turn(ctx, NAME, judge, parallel=True)
    return [], []
