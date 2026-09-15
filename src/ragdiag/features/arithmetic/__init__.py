"""산술 — case26. 답변에 적힌 등식이 실제로 맞는가."""

from __future__ import annotations

import re

from ragdiag.results import Check

from .._shared import run_check

NAME = "arithmetic"


# 답변 안의 "A + B = C" 꼴을 찾아 직접 계산해 본다. 자연어 계산까지는 못 잡지만,
# 식을 써 놓고 답을 틀린 경우는 확실히 잡힌다. 그게 case26 에서 코드로 검증
# 가능한 유일한 부분이다.
_EQUATION = re.compile(
    r"(?<![\w.])(\d[\d,]*(?:\.\d+)?(?:\s*[-+*/×÷]\s*\d[\d,]*(?:\.\d+)?)+)"
    r"\s*=\s*(\d[\d,]*(?:\.\d+)?)(?![\d.])"
)
_ALLOWED = set("0123456789.+-*/() ")


def _to_number(text: str) -> float:
    return float(text.replace(",", ""))


def check_arithmetic(answer: str, tolerance: float = 0.01) -> Check:
    """답변에 적힌 등식이 실제로 맞는지 계산해 본다.

    한계: "5영업일 뒤면 3월 13일" 같은 자연어 계산은 못 잡는다. 식을 명시한
    경우만 검증하므로, not_applicable 이 나왔다고 계산이 맞다는 뜻은 아니다.
    """
    equations = _EQUATION.findall(answer)
    if not equations:
        return Check("arithmetic", "not_applicable", "검증 가능한 등식이 없음")

    wrong = []
    for expression, claimed in equations:
        normalized = expression.replace(",", "").replace("×", "*").replace("÷", "/")
        if not set(normalized) <= _ALLOWED:
            continue
        try:
            actual = eval(normalized, {"__builtins__": {}}, {})   # 숫자·연산자만 통과
        except (SyntaxError, ZeroDivisionError, TypeError):
            continue
        if abs(actual - _to_number(claimed)) > tolerance:
            wrong.append(f"{expression} = {claimed} (실제 {actual:g})")

    if not wrong:
        return Check("arithmetic", "ok", f"등식 {len(equations)}개 확인")
    return Check("arithmetic", "violated",
                 f"등식 {len(equations)}개 중 {len(wrong)}개 오류", evidence=wrong[:5])


def process_data(ctx) -> tuple[list, list]:
    return run_check(ctx, NAME, lambda t: check_arithmetic(t.case.llm_ans_on_last_q))
