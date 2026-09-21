"""LLM 을 부르기 전에 case 가 확정되는 턴을 닫는다.

판정할 답변이 아예 없는 턴이 있다. 서비스가 자원을 확보하지 못해 내보낸 안내
문구가 그렇다 - 모델이 만든 답이 아니라서, 관측을 돌리면 판정자가 이걸 거절로 읽어
case28(보안 정책)로 보낸다. 서버 자원 문제를 보안 정책 문제로 세면 고칠 곳을 정반대로
가리킨다. 그래서 코드로 먼저 걸러 LLM 호출 0회로 끝낸다.

그런 규칙은 더 생길 수 있다. 규칙 하나가 파일 하나다:

    cp src/<pkg>/features/short_circuit/_template.py src/<pkg>/features/short_circuit/<규칙>.py
    # 아래 RULES 에 한 줄 더한다

규칙은 **코드만 쓴다.** observe 보다 앞이라 LLM 결과는 아직 없다.
"""

from ragdiag import taxonomy
from ragdiag.results import Check, Classification

from .._shared import each_turn
from . import degenerate, service_error

NAME = "short_circuit"

# 순서 = 우선순위. 처음 걸린 규칙이 case 를 정하고, 그 뒤 규칙은 보지 않는다.
RULES = (
    service_error,
    degenerate,
)


def decide(rule, check: Check) -> Classification:
    """걸린 규칙의 case 로 분류를 만든다. 신뢰도는 taxonomy 의 값이다.

    다른 case 와 달리 LLM 판정이 하나도 섞이지 않은 분류다. 규칙의 NOTES 에 그 사실과
    집계할 때의 주의를 적어 둔다 - case9 가 쌓이면 "챗봇 품질이 나쁘다"가 아니라 "그
    시간대에 자원이 모자랐다"이고, 같은 표에서 나란히 읽으면 품질 지표가 흔들린다.
    """
    meta = taxonomy.get(rule.CASE)
    return Classification(
        primary_case=rule.CASE,
        confidence=meta.confidence if meta else "high",
        reason=f"{rule.REASON} — {check.detail}",
        secondary_cases=[],
        notes=list(rule.NOTES),
    )


def _apply(turn) -> None:
    for rule in RULES:
        check = rule.check(turn)
        # 걸리지 않은 규칙의 결과도 남긴다. 출력의 checks 에 실려 "봤는데 아니었다"가 보인다.
        turn.checks[rule.NAME] = check
        if check.violated:
            turn.classification = decide(rule, check)
            return


def process_data(ctx) -> tuple[list, list]:
    each_turn(ctx, NAME, _apply)
    return [], []
