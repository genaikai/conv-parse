"""④ 확정 사건 — LLM 을 부르기 전에 코드가 턴을 닫는다.

판정할 답변이 없거나(I1 자원 부족 문구 · I2 붕괴), 불만과 무관하게 사건이 확정인 턴(S2
인젝션 수행 · S3 정보 유출)이다. 관측에 넣으면 판정자가 문구를 거절로 읽어 S1 로 보낸다 —
서버 자원 문제가 보안 정책으로 집계되면 고칠 곳이 정반대다. 그래서 코드로 먼저 걸러
LLM 호출 0회로 끝낸다. 등급은 4(코드 확정)다.

규칙 하나가 파일 하나다:

    cp src/<pkg>/features/short_circuit/_template.py src/<pkg>/features/short_circuit/<규칙>.py
    # 아래 RULES 에 한 줄 더한다

규칙은 **코드만 쓴다.** observe 보다 앞이라 LLM 결과는 아직 없다. 앞서 돈 코드 검증기
(CHECKS_EARLY) 의 결과는 turn.checks 에 있다.
"""

from ragdiag.results import Check

from .._shared import each_turn
from . import degenerate, injection, leak, service_error

NAME = "short_circuit"

# 순서 = 우선순위. 처음 걸린 규칙이 라벨을 정하고, 그 뒤 규칙은 보지 않는다.
RULES = (
    service_error,      # I1
    degenerate,         # I2
    injection,          # S2
    leak,               # S3
)


def _apply(turn) -> None:
    from ..arbitrate import close

    for rule in RULES:
        check = rule.check(turn)
        # 걸리지 않은 규칙의 결과도 남긴다. 출력의 checks 에 실려 "봤는데 아니었다"가 보인다.
        turn.checks[rule.NAME] = check
        if check.violated:
            close(turn, rule.CASE, 4, f"{rule.REASON} — {check.detail}", notes=list(rule.NOTES))
            return


def process_data(ctx) -> tuple[list, list]:
    each_turn(ctx, NAME, _apply)
    return [], []
