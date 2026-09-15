"""코드 검증기 묶음. LLM 없이 문자열만 본다.

[임시] 다음 단계에서 검증기마다 폴더 하나로 나눈다. 서비스 오류 문구는 여기가 아니라
short_circuit 의 규칙이다 - LLM 보다 먼저 봐야 해서다.
"""

from ragdiag.checks import (
    Check,
    LengthRequest,
    check_arithmetic,
    check_dates,
    check_format,
    check_injection,
    check_language,
    check_length,
    check_pii,
    check_python_syntax,
    check_quoted_spans,
    check_sql_shape,
    check_truncated,
)
from ragdiag.schema import Case, Observation

from .._shared import each_turn

NAME = "checks"


def run_checks(case: Case, obs: Observation) -> dict[str, Check]:
    """코드로 되는 검증. LLM 호출 없음.

    항상 도는 것과 관측이 요구를 찾았을 때만 도는 것을 나눈다. 요구가 없었는데
    검증하면 not_applicable 이 나오는데, 그걸 위반과 섞으면 멀쩡한 답변이
    전부 실패로 집계된다.
    """
    checks: dict[str, Check] = {
        "pii": check_pii(case.last_query),
        "truncated": check_truncated(case.llm_ans_on_last_q),
        "quoted_spans": check_quoted_spans(case.llm_ans_on_last_q, case.rag_chunks),
        "python_syntax": check_python_syntax(case.llm_ans_on_last_q),
        "sql_shape": check_sql_shape(case.llm_ans_on_last_q),
        "arithmetic": check_arithmetic(case.llm_ans_on_last_q),
        "dates": check_dates(case.llm_ans_on_last_q),
        "injection": check_injection(case.rag_chunks, case.llm_ans_on_last_q),
        "language": check_language(case.llm_ans_on_last_q, obs.requested_language or None),
        "format": check_format(
            case.llm_ans_on_last_q,
            None if obs.requested_format == "none" else obs.requested_format,
        ),
    }
    if obs.requested_length_kind == "none":
        checks["length"] = check_length(case.llm_ans_on_last_q, None)
    else:
        checks["length"] = check_length(
            case.llm_ans_on_last_q,
            LengthRequest(obs.requested_length_kind, obs.requested_length_value or None),
        )
    return checks


def process_data(ctx) -> tuple[list, list]:
    each_turn(ctx, NAME, lambda t: t.checks.update(run_checks(t.case, t.observation)))
    return [], []
