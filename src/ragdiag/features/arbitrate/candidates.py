"""후보 생성 규칙 — TurnResult 가 들고 있는 것 전부를 읽어 (라벨, 등급, 이유, 태그) 를 낸다.

v2 의 route/table.py 는 if-체인이었다. 순서가 곧 규칙이라 라벨이 늘수록 유지가 안 됐다.
v3 는 **후보를 전부 내고** arbitrate 가 등급으로 고른다. 그래서 이 파일의 규칙들은 서로의
순서를 모른다 - 어느 규칙이든 조건이 맞으면 후보를 낸다. 전부 코드다.

등급 (docs/design/taxonomy_v3.md "후보와 중재"):
  4 코드 확정 · 3 근거 확정 · 2 확신 p ≥ kev_confident · 1 기울어짐 · 0 후보 아님

태그는 후보에 딸려 가고, 주 라벨이 무엇이든 전부 남는다. 라벨 꼴이 아닌 전역 태그
(U3 · 복합질문 · 미검증주장 · 검증기 이름)는 global_tags 가 낸다.
"""

from __future__ import annotations

import re

from ragdiag import settings
from ragdiag.results import Candidate, TurnResult
from ragdiag.schema import DOC_DOMAINS

from .._shared import grade_from_p

CONTENT = {"content_missing", "content_wrong"}

# (불만 종류, 검증기 이름, 태그)
REQUESTS = [("format", "format", "G1:포맷"),
            ("language", "language", "G1:언어"),
            ("length", "length", "G1:길이")]


def _p(turn: TurnResult, qid: str, option: str | None = None) -> float:
    """문항의 확률. option 이 있으면 그 선택지의 확률, 없으면 noul 의 P(yes)."""
    entry = turn.probabilities.get(qid) or {}
    if option is not None:
        return float((entry.get("probabilities") or {}).get(option, 0.0))
    return float(entry.get("p", 0.0))


def _check(turn: TurnResult, name: str):
    return turn.checks.get(name)


def _violated(turn: TurnResult, name: str) -> bool:
    c = _check(turn, name)
    return c is not None and c.violated


def _has_search_source(turn: TurnResult) -> bool:
    return bool(turn.case.search_sources)


def _only_business_tools(turn: TurnResult) -> bool:
    """출처가 전부 업무 도구인가 (검색 도구 이름 목록이 있을 때만 의미가 있다)."""
    sources = turn.case.chunk_sources
    if not sources or not settings.SEARCH_TOOL_NAMES:
        return False
    names = set(settings.SEARCH_TOOL_NAMES)
    for s in sources:
        if s in ("retrieved", "history_retrieved"):
            return False
        if ":" in s and s.split(":", 1)[1] in names:
            return False
        if s in ("tool", "history_tool"):          # 이름 없는 도구 결과 - 못 가른다
            return False
    return True


def candidates_for(turn: TurnResult) -> list[Candidate]:
    out: list[Candidate] = []
    obs = turn.observation
    case = turn.case
    add = lambda *a, **k: out.append(Candidate(*a, **k))   # noqa: E731

    # --- 코드 확정 사건. 보통 short_circuit 이 먼저 닫지만, 닫히지 않은 턴에서도 사실이다 ----
    if _violated(turn, "service_error"):
        add("I1", 4, "서비스 자원 부족 안내 문구")
    if _violated(turn, "degenerate"):
        add("I2", 4, "답변이 같은 글자 · 기호의 반복뿐")
    if _violated(turn, "injection") or _violated(turn, "injection_rule"):
        add("S2", 4, "검색 문서의 지시를 답변이 수행함")
    if _violated(turn, "leak"):
        add("S3", 4, "질문에 없던 개인정보가 답변에 있음")
    if turn.legibility_p is not None:
        g = grade_from_p(turn.legibility_p)
        if g:
            add("I2", g, f"읽을 수 없는 답변일 수 있음 (p={turn.legibility_p:.2f})")

    if obs is None:
        return out

    complaint = obs.complaint_target
    content = complaint in CONTENT
    doc = obs.question_domain in DOC_DOMAINS

    # --- N0 ---------------------------------------------------------------------
    if complaint == "none":
        p = _p(turn, "complaint_target", "none")
        g = grade_from_p(p)
        if g:
            add("N0", g, f"후속 발화가 앞 답변을 문제 삼지 않음 (p={p:.2f})",
                notes=["실패율 분모에서 뺄 것.", "쌓이면 챗봇이 아니라 필터를 좁힐 신호다."])

    # --- S1 ---------------------------------------------------------------------
    if obs.answer_refused and complaint != "none":
        p = _p(turn, "answer_refused")
        g = 3 if p >= settings.KEV_CONFIDENT else (2 if p >= settings.KEV_LEAN else 0)
        if g:
            add("S1", g, f"정책 · 권한을 이유로 거절했고 사용자가 불만 (p={p:.2f})",
                notes=["권한 부족으로 인한 거절이 섞여 있을 수 있음 — 권한 조회 결과 필요"])

    # --- U1 ---------------------------------------------------------------------
    # 낼 수 없는 형태를 요구했으면 근거 · 생성을 탓할 수 없다. 확신이면 T · D · G5 · G3 는
    # 후보로 올리지 않는다 - 등급으로 다투게 두면 D1(근거 확정 3)이 U1(확신 2)을 늘 이겨서,
    # "링크를 못 준 것" 이 "문서에 답이 없었다" 로 집계된다. 코드 확정(G1 · G6 · S)은 그대로다.
    blame_answer = True
    if obs.requests_unsupported_output:
        p = _p(turn, "requests_unsupported_output")
        g = grade_from_p(p)
        if g:
            add("U1", g, f"챗봇이 낼 수 없는 형태를 요구함 (p={p:.2f})")
        if g >= 2:
            blame_answer = False

    # --- T 묶음 -------------------------------------------------------------------
    no_calls = not case.tool_calls
    fetched = case.n_fetched if case.n_fetched is not None else len(case.rag_chunks)
    tool_check = _check(turn, "tool_numbers")
    if blame_answer and doc and content and no_calls and fetched == 0:
        add("T1", 4, "업무 질문인데 도구(검색 포함)를 하나도 부르지 않고 답함",
            notes=["서비스가 '검색 없이 답할 수 있다'고 판단했을 수 있다. 그 판단이 틀린 것이라면 "
                   "고칠 곳은 검색 트리거 · 라우터다."])
    if blame_answer and case.tool_calls and tool_check is not None and tool_check.violated \
            and tool_check.detail.startswith("빈결과"):
        add("T3", 4, f"도구 결과가 비었는데 답변이 수치를 단정함 — {tool_check.detail}",
            tags=["tool_numbers"])

    # --- D1 / T2 ---------------------------------------------------------------------
    overall = turn.overall_verdict()
    best = turn.best_sufficiency()
    if blame_answer and doc and content and case.rag_chunks and overall in ("partial", "insufficient"):
        verified = best.verified if best else None
        g = 3 if verified else 2
        tags = [] if verified is not False else ["2차불일치"]
        if _only_business_tools(turn):
            add("T2", g, f"업무 도구 결과가 질문에 답하지 못함 (verdict={overall})", tags=tags)
        else:
            if not _has_search_source(turn) and not settings.SEARCH_TOOL_NAMES \
                    and any(s.startswith(("tool", "history_tool")) for s in case.chunk_sources):
                tags = tags + ["D:출처미상"]
            add("D1", g, f"검색 근거에 요구에 답하는 내용이 없음 (verdict={overall})", tags=tags,
                notes=["검색 실패와 코퍼스 부재는 구분 불가 — 부서 편중으로만 추정"])

    # --- G1 ------------------------------------------------------------------------
    for target, name, tag in REQUESTS:
        c = _check(turn, name)
        if c is None:
            continue
        if c.violated:
            add("G1", 4, f"{target} 요구 위반 확인 — {c.detail}", tags=[tag])
        elif c.verdict == "undetermined" and complaint == target:
            add("G1", 2, f"{target} 요구는 있으나 코드가 판정할 수 없음 — 불만이 그것을 가리킴",
                tags=[tag], notes=["코드 검증이 판정 불가 — 관측에만 의존"])
    if complaint == "tone":
        p = _p(turn, "complaint_target", "tone")
        g = grade_from_p(p)
        if g:
            add("G1", g, f"말투 · 어조 · 용어에 대한 불만 (p={p:.2f})", tags=["G1:어조"])

    # --- G5 ------------------------------------------------------------------------
    if blame_answer and doc and case.rag_chunks:
        contradicted = [v for v in turn.claim_verdicts if v.verdict == "contradicted"]
        supported = [v for v in turn.claim_verdicts if v.verdict == "supported"]
        doc_claims = [v for v in turn.claim_verdicts if v.expected_source == "doc"]
        tool_bad = [v for v in turn.claim_verdicts if v.verdict == "tool_mismatch"]
        carried_only = _carried_only(turn)
        if contradicted:
            add("G5", 3, f"답변의 주장 {len(contradicted)}건이 근거와 어긋남",
                tags=["G5:어긋남"] + (["G5:과거근거"] if carried_only else []))
        elif overall == "sufficient" and doc_claims and not supported and content:
            add("G5", 2, "근거에 답이 있는데 답변의 주장이 그것을 쓰지 않음",
                tags=["G5:안씀"] + (["G5:과거근거"] if carried_only else []))
        if tool_bad:
            add("G5", 3, f"도구 결과와 다른 수치 · 식별자 {len(tool_bad)}건",
                tags=["G5:어긋남", "tool_numbers"])
    if _violated(turn, "quoted_spans"):
        if content:
            add("G5", 3, "답변이 인용부호로 제시한 문장이 근거에 없음", tags=["G5:지어낸인용"])
    if _violated(turn, "tool_numbers") and not (tool_check and tool_check.detail.startswith("빈결과")):
        if content and doc:
            add("G5", 3, f"답변의 수치가 도구 결과에 없음 — {tool_check.detail}",
                tags=["G5:어긋남", "tool_numbers"])

    # --- G6 ------------------------------------------------------------------------
    calc_broken = _violated(turn, "arithmetic") or _violated(turn, "dates")
    code_broken = _violated(turn, "python_syntax") or _violated(turn, "sql_shape")
    if not doc:
        if calc_broken:
            add("G6", 4, "등식 · 날짜 계산 오류 확인", tags=["G6:계산"])
        if code_broken:
            add("G6", 4, "코드 문법 오류 확인", tags=["G6:코드"])
        if content and obs.question_domain in ("general_knowledge", "calculation", "code", "tool_usage") \
                and not (calc_broken or code_broken):
            add("G6", 1, f"{obs.question_domain} 질문의 내용 불만 — 코드로 확인되지 않음",
                tags=["G6:일반"], notes=["판정자의 사전지식에 의존 — 표본 검토 필요"])

    # --- G4 ------------------------------------------------------------------------
    if obs.question_multi_intent and not obs.answer_covers_all_intents:
        p = min(_p(turn, "question_multi_intent"), 1.0 - _p(turn, "answer_covers_all_intents"))
        g = grade_from_p(p)
        if g:
            add("G4", g, f"복합 질문의 일부만 답함 (p={p:.2f})")

    # --- G2 ------------------------------------------------------------------------
    if "C1" not in turn.flags:
        if obs.answer_ignored_history:
            p = _p(turn, "answer_ignored_history")
            if turn.history is not None and turn.history.verified:
                add("G2", 3, "앞 질문에서 정한 조건을 어김 — 조건 구절을 원문에서 확인", tags=["G2:조건"])
            else:
                g = grade_from_p(p)
                if g:
                    add("G2", g, f"앞 질문에서 정한 조건을 어김 (p={p:.2f}, 구절 미확인)", tags=["G2:조건"])
        if "C2" not in turn.flags and turn.memory_use in ("ignored", "contradicted"):
            g = grade_from_p(turn.memory_p)
            if _quote_verified(turn, "G2:memory"):
                g = 3
            if g:
                add("G2", g, f"memory 의 사용자 정보를 {turn.memory_use} (p={turn.memory_p:.2f})",
                    tags=["G2:memory"])
        if turn.consistency:
            p = max(turn.consistency.values())
            g = grade_from_p(p)
            if _quote_verified(turn, "G2:모순"):
                g = 3
            if g:
                add("G2", g, f"앞 답변과 다른 사실을 말함 (p={p:.2f})", tags=["G2:모순"])

    # --- G3 잔여 -------------------------------------------------------------------
    specific = {"T1", "T2", "T3", "D1", "G1", "G2", "G4", "G5", "G6", "U1", "S1", "N0"}
    if blame_answer and complaint != "none" and not any(c.label in specific for c in out):
        p = _p(turn, "complaint_target", complaint)
        tags = []
        if obs.question_clarity != "clear" and not obs.answer_asked_back:
            tags.append("되묻기없음")
        reason = "물은 것과 다른 것을 답함 — 더 구체적인 원인을 찾지 못함"
        if complaint in ("format", "language", "length") and not content:
            reason = f"{complaint} 불만이나 이전 질문들에 그런 요구가 없었거나 지켰음 — 기대와 다른 답"
        if complaint == "no_answer":
            reason = "답이 없거나 끊겼다는 불만 — 잘림 여부는 로그로 판정 불가"
        if complaint == "inconsistency" and not turn.consistency:
            reason = "앞 답변과 다르다는 불만 — 앞 답변 기록이 없어 대조 불가"
        # 불만 종류의 확신이 기울어짐(kev_lean) 아래면 후보가 아니다 - 그러면 unclassified 다.
        # "other" 라도 마찬가지다. 확신 없는 잔여를 라벨로 세면 G3 가 쓰레기통이 된다.
        if p >= settings.KEV_LEAN:
            add("G3", 1, reason, tags=tags)
    return out


def _carried_only(turn: TurnResult) -> bool:
    """근거가 과거(carried) 쪽에만 있나."""
    own = [s for k, s in turn.sufficiency.items() if k.startswith("own")]
    carried = [s for k, s in turn.sufficiency.items() if k.startswith("carried")]
    return (bool(carried) and any(s.evidence for s in carried)
            and not any(s.evidence for s in own))


def _quote_verified(turn: TurnResult, kind: str) -> bool:
    return any(q["kind"] == kind and q["verified"] for q in turn.quotes)


_IDENT = re.compile(r"\b(?=[A-Za-z0-9_-]*[A-Za-z])(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{3,}\b")


def global_tags(turn: TurnResult) -> list[str]:
    """주 라벨과 무관하게 붙는 태그."""
    tags: list[str] = []
    obs = turn.observation
    if obs is not None:
        if obs.question_clarity != "clear" and _p(turn, "question_clarity", obs.question_clarity) >= settings.KEV_LEAN:
            tags.append("U3")
        if obs.question_multi_intent:
            tags.append("복합질문")
    if any(v.verdict == "unverified" and v.expected_source == "general" for v in turn.claim_verdicts):
        tags.append("미검증주장")
    if turn.case.tool_calls and obs is not None:
        idents = {m.lower() for m in _IDENT.findall(obs.resolved_question or "")}
        args = " ".join(c.get("arguments", "") for c in turn.case.tool_calls).lower()
        if idents and not any(i in args for i in idents):
            tags.append("T:인자불일치")
    for name, c in sorted(turn.checks.items()):
        if c.violated and name not in ("C1", "C2", "U2"):
            tags.append(name)
    return tags
