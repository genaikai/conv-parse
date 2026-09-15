"""파이썬 문법 — case27. 답변의 파이썬 코드 블록이 파싱되는가."""

from __future__ import annotations

import ast

from ragdiag.results import Check

from .._shared import run_check
from .._text import extract_code_blocks

NAME = "python_syntax"


def check_python_syntax(answer: str) -> Check:
    """case25의 일부 — 파이썬 코드 블록이 문법적으로 파싱되는가.

    문법이 맞다고 정답인 건 아니다. 틀린 문법은 확실히 실행 불가라는 것만 말한다.
    실행 검증은 샌드박스가 있어야 하므로 여기서는 하지 않는다.
    """
    blocks = [body for lang, body in extract_code_blocks(answer)
              if lang.lower() in ("python", "py", "")]
    if not blocks:
        return Check("python_syntax", "not_applicable", "파이썬 코드 블록 없음")

    broken = []
    for body in blocks:
        try:
            ast.parse(body)
        except SyntaxError as e:
            broken.append(f"line {e.lineno}: {e.msg}")
    if not broken:
        return Check("python_syntax", "ok", f"코드 블록 {len(blocks)}개 파싱 성공")
    return Check(
        "python_syntax", "violated",
        f"코드 블록 {len(blocks)}개 중 {len(broken)}개 문법 오류",
        evidence=broken[:5],
    )


def process_data(ctx) -> tuple[list, list]:
    return run_check(ctx, NAME, lambda t: check_python_syntax(t.case.llm_ans_on_last_q))
