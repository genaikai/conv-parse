"""SQL 모양 — case27 보강. SQL 블록에 명백한 구조 결함이 있는가."""

from __future__ import annotations

import re

from ragdiag.results import Check

from .._shared import run_check
from .._text import extract_code_blocks

NAME = "sql_shape"


_SQL_KEYWORDS = ("select", "insert", "update", "delete", "with", "create")


def check_sql_shape(answer: str) -> Check:
    """SQL 블록의 명백한 결함만 본다. 파서가 없으므로 구조적 흠집만 잡는다.

    문법이 맞다고 정답인 건 아니다. 실행 검증에는 DB 연결이 필요하다.
    """
    blocks = [body for lang, body in extract_code_blocks(answer)
              if lang.lower() in ("sql", "postgresql", "mysql")]
    if not blocks:
        return Check("sql_shape", "not_applicable", "SQL 코드 블록 없음")

    problems = []
    for body in blocks:
        text = body.strip()
        lowered = text.lower()
        if not any(lowered.startswith(k) for k in _SQL_KEYWORDS):
            problems.append("SQL 키워드로 시작하지 않음")
        if text.count("(") != text.count(")"):
            problems.append("괄호 짝이 맞지 않음")
        # GROUP BY / ORDER BY 뒤에 아무것도 없이 끝나는 경우
        if re.search(r"\b(group|order)\s+by\s*$", lowered):
            problems.append("GROUP BY / ORDER BY 뒤가 비어 있음")
        if lowered.startswith("select") and " from " not in lowered:
            problems.append("SELECT 인데 FROM 이 없음")

    if not problems:
        return Check("sql_shape", "ok", f"SQL 블록 {len(blocks)}개 이상 없음")
    return Check("sql_shape", "violated",
                 f"SQL 블록 {len(blocks)}개에서 {len(problems)}건",
                 evidence=problems[:5])


def process_data(ctx) -> tuple[list, list]:
    return run_check(ctx, NAME, lambda t: check_sql_shape(t.case.llm_ans_on_last_q))
