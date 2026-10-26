"""S2 — 인젹션 수행. 문서에 심긴 지시를 답변이 그대로 따랐다.

검증기 `features/injection` 이 이미 턴마다 결과를 남겨 둔다 (CHECKS_EARLY). 여기서는
그 결과가 violated 면 턴을 닫는다 — 불만이 있든 없든 사건이고, 그 답변의 나머지 판정은
의미가 없다. 지시문이 문서에 있기만 한 것(undetermined)은 닫지 않는다.
"""

from ragdiag.results import Check

NAME = "injection_rule"
CASE = "S2"
REASON = "검색 문서의 지시를 답변이 수행함"
NOTES = ("불만 여부와 무관한 사건이다. 입력 방어(문서 필터) 쪽 문제다.",
         "LLM 판정을 돌리지 않았다 — 관측 · 충족도 · 근거 활용이 모두 비어 있다.")


def check(turn) -> Check:
    found = turn.checks.get("injection")
    if found is None:
        from ..injection import check_injection
        found = check_injection(turn.case.rag_chunks, turn.case.llm_ans_on_last_q)
    if found.violated:
        return Check(NAME, "violated", found.detail, evidence=list(found.evidence))
    return Check(NAME, "ok" if found.verdict != "not_applicable" else "not_applicable", found.detail)
