"""라우팅 — 관측과 검증 결과를 taxonomy case 로 바꾼다. LLM 없음.

case 를 LLM 에게 직접 고르게 하지 않는 이유가 셋 있다.

1. 30지선다는 어떤 모델이든 정확도가 안 나온다. 관측을 8개의 좁은 질문으로 쪼개면
   각각은 쉬운 질문이 된다.
2. 한 호출로 case 까지 물으면 모델이 결론을 먼저 직감하고 관측값을 거기 맞춘다.
3. taxonomy 를 고쳐도 관측값은 그대로 재사용된다. 이 파일만 다시 돌리면 된다.

category 는 case 에서 계산되므로 따로 분류하지 않는다.
"""

from __future__ import annotations

from typing import Optional

from ragdiag import taxonomy
from ragdiag.results import Check, Classification
from ragdiag.schema import GroundingCheck, Observation, SufficiencyJudgment
from ragdiag.verify import CitationCheck, QuoteCheck, final_verdict


def _check(checks: dict[str, Check], name: str) -> Optional[Check]:
    return checks.get(name)


# (불만 라벨, 검증기 이름, case). 요구를 어긴 것은 불만이 그쪽을 가리키면 주
# 라벨이 되고, 아니면 secondary 로 남는다.
REQUEST_CASES = [
    ("format", "format", "case12"),
    ("language", "language", "case10"),
    ("length", "length", "case11"),
]


def _request_verdict(checks: dict[str, Check], name: str) -> str:
    """요구 검증기가 무엇을 말했나. 네 값을 그대로 돌려준다.

    **not_applicable 과 undetermined 를 뭉치면 안 된다.** 전에는 둘 다 None 이었고,
    라우팅이 그 None 에서 case 를 유지했다. 뜻이 전혀 다르다:

      not_applicable  요구가 아예 없었다. 답변이 어길 것이 없었다
      undetermined    요구는 있었는데 코드가 잴 수 없다 (길이는 언제나 여기다)

    길이 검증기가 요구가 있을 때 늘 undetermined 를 내기 때문에 "None 이면 case 유지"
    규칙이 길이에는 옳았고, 그 규칙이 포맷 · 언어에까지 같이 걸리면서 **요구가 없었던
    턴까지 case10 · case12 로 내보냈다.** 약한 모델에서 상시로 터진다 - Qwen3.5-9B 는
    인용 대조 통과율이 0% 라 요구가 거의 언제나 지워지고, 그때마다 이 갈래로 온다.
    """
    check = _check(checks, name)
    return check.verdict if check is not None else "not_applicable"


def _requested_but_broken(checks: dict[str, Check], name: str) -> Optional[bool]:
    """어겼나. 어겼을 때만 True - 부가 케이스는 그것만 보면 된다."""
    verdict = _request_verdict(checks, name)
    if verdict == "violated":
        return True
    if verdict == "ok":
        return False
    return None      # not_applicable · undetermined


def secondary_from(obs: Observation, checks: dict[str, Check]) -> list[str]:
    """주 라벨과 독립적으로 성립하는 케이스들.

    한 턴이 case4(모호한 질문)이면서 동시에 case20(검색 실패)일 수 있다. 억지로
    하나만 고르면 정보가 사라지고 tie-break 가 자의적이 된다.
    """
    extra = []
    if obs.question_clarity == "unresolved_reference":
        extra.append("case4")          # 앞 질문들로도 지시 대상이 안 풀린 질문
    if obs.question_multi_intent:
        extra.append("case3")          # 복합 질문
    pii = _check(checks, "pii")
    if pii is not None and pii.violated:
        extra.append("case6")          # 질문에 개인정보
    quoted = _check(checks, "quoted_spans")
    if quoted is not None and quoted.violated:
        extra.append("case24")         # 인용 표기 오류
    # 실제 질문은 도메인과 계산이 겹치는 경우가 흔하다("5영업일 뒤가 언제냐").
    # question_domain 은 하나만 고를 수 있으므로, 등식 오류는 부가로 따로 잡는다.
    for name in ("arithmetic", "dates"):
        wrong = _check(checks, name)
        if wrong is not None and wrong.violated and "case26" not in extra:
            extra.append("case26")     # 계산 오류 — 날짜도 계산이다
    if obs.answer_ignored_history:
        extra.append("case14")         # 이전 턴 맥락 상실
    # 복합 질문인데 일부만 답한 것은 다른 원인과 함께 성립한다.
    if obs.question_multi_intent and not obs.answer_covers_all_intents:
        extra.append("case15")         # 복합 질문 일부만 답변

    # 표로 달라고 했는데 줄글로 왔고 사용자는 **내용**을 불평한 경우.
    # 전에는 complaint_target 이 그쪽을 가리킬 때만 봐서, 어긴 사실이 통째로
    # 사라졌다. 물어야 할 것은 "불만이 포맷에 관한 것인가"가 아니라
    # "포맷 요구가 있었고 어겼는가"다 - 앞은 판단이고 뒤는 사실이다.
    for target, check_name, case_id in REQUEST_CASES:
        if obs.complaint_target == target:
            continue               # 주 라벨로 간다. 두 번 세지 않는다
        if _requested_but_broken(checks, check_name) is True:
            extra.append(case_id)

    # 코드가 파싱되지 않는 것도 답변에 대한 사실이다. question_domain 이 code 로
    # 읽혔을 때만 보면, 도메인 질문에 딸려 온 SQL 이 깨져 있어도 잡히지 않는다.
    if obs.question_domain not in ("code", "tool_usage"):
        for name, case_id in (("python_syntax", "case27"), ("sql_shape", "case27")):
            broken = _check(checks, name)
            if broken is not None and broken.violated and case_id not in extra:
                extra.append(case_id)
    return extra



def route(
    obs: Observation,
    checks: dict[str, Check],
    judgment: Optional[SufficiencyJudgment] = None,
    citation: Optional[CitationCheck] = None,
    grounding: Optional[GroundingCheck] = None,
    complaint: Optional[QuoteCheck] = None,
) -> Classification:
    """관측 + 검증 → case. 값싸고 확실한 갈림길을 앞에 둔다."""
    extra = secondary_from(obs, checks)

    def done(case_id: str, reason: str, notes: Optional[list[str]] = None) -> Classification:
        meta = taxonomy.get(case_id)
        return Classification(
            primary_case=case_id,
            confidence=meta.confidence if meta else "low",
            reason=reason,
            secondary_cases=[c for c in extra if c != case_id],
            notes=notes or [],
        )

    # --- 1. 거절 -------------------------------------------------------------
    if obs.answer_refused:
        # 권한이 없어 거절한 경우와 구분할 수 없다. 권한 조회 결과가 없기 때문이다.
        # 그 케이스는 taxonomy 에서 제외됐지만 실제로는 여기 섞여 들어온다.
        return done("case28", "답변이 정책·권한을 이유로 거절함",
                    ["권한 부족으로 인한 거절이 섞여 있을 수 있음 — 권한 조회 결과 필요"])

    # --- 1a. 문서가 모델을 조종했는지 ------------------------------------------
    # 답변 내용을 따지기 전에 볼 문제다. 문서에 심긴 지시를 수행했다면
    # 그 답변의 나머지 판정은 의미가 없다.
    injection = _check(checks, "injection")
    if injection is not None and injection.violated:
        return done("case29", f"검색 문서의 지시를 답변이 수행함 — {injection.detail}")

    # --- 1c. 애초에 불만이 아니었나 --------------------------------------------
    # 필터는 재현율 쪽으로 넓게 잡는다. 그래서 그냥 다음을 묻는 턴이 섞여 들어온다.
    # 이걸 실패로 세면 case20 이 부풀고, 그 숫자가 코퍼스 보강 목록이 되어
    # 문서팀이 쓸 필요 없는 문서를 쓴다.
    #
    # 거절·인젝션보다 뒤에 두는 이유: 그 둘은 사용자가 지적했든 아니든 확인된
    # 사실이다. 반대로 질문 모호성(1b)보다는 앞이다 - 사용자가 만족했다면 그
    # 모호함은 실제로 문제가 되지 않았다는 뜻이고, 신호는 secondary(case4·case3)로
    # 남는다.
    if obs.complaint_target == "none":
        # 불만이 없다고 결함이 없는 건 아니다. 코드가 잡은 위반이 있으면
        # 사용자가 지적하지 않았을 뿐이다.
        violated = sorted(name for name, c in checks.items() if c.violated)
        if violated:
            return done(taxonomy.UNCLASSIFIED,
                        f"불만은 없으나 코드 검증이 위반을 잡음 ({', '.join(violated)})",
                        ["사용자가 지적하지 않은 결함 — 표본 검토 대상"])
        notes = ["실패율 분모에서 뺄 것.", "쌓이면 챗봇이 아니라 필터를 좁힐 신호다."]
        # 근거로 든 구절을 후속 발화에서 그대로 찾지 못했다. 판정을 버리지는 않는다 -
        # 약한 모델은 짧은 발화를 일부만 따오거나 말을 바꿔 적어서, 버리면 맞는 판정까지
        # 사라진다. 대신 신뢰도를 낮춰 "신뢰도 낮음 제외" 로 걸러 볼 수 있게 한다.
        if complaint is not None and not complaint.verified:
            result = done("case0", "후속 발화가 앞 답변을 문제 삼지 않음 — 근거는 원문에서 확인 못 함",
                          ["판정자가 댄 근거를 후속 발화에서 그대로 찾지 못했다 — 표본 검토 대상",
                           *notes])
            result.confidence = "low"
            return result
        return done("case0", "후속 발화가 앞 답변을 문제 삼지 않음", notes)

    # --- 1b. 질문 쪽 문제가 먼저다 --------------------------------------------
    # 챗봇이 낼 수 없는 형태를 요구했으면 답변을 탓할 수 없다.
    if obs.requests_unsupported_output:
        return done("case2", "챗봇이 낼 수 없는 형태를 요구함 (링크·이미지 등)")
    # 질문 자체가 답을 특정할 수 없으면 그 뒤 판정이 전부 의미를 잃는다.
    if obs.question_clarity == "vague":
        return done("case1", "앞 대화를 알아도 무엇을 묻는지 특정되지 않음")

    # --- 2. 답이 없나 ----------------------------------------------------------
    #
    # 출력 잘림(case8)은 더 이상 판정하지 않는다. 종결 부호 · 코드펜스로 잘림을
    # 짚던 검증기가 있었는데, 온전한 답변이 특수한 기호나 답변 형식 때문에 잘림으로
    # 오분류되는 일이 너무 많았다 (2026-09 실데이터). 텍스트만으로는 "끊겼다" 와
    # "그렇게 끝맺었다" 를 가를 수 없고, finish_reason 같은 필드가 로그에 생기면
    # 그때 되살린다. 그래서 "답이 없다" 는 불만은 코드가 깨진 경우 말고는 미분류다.
    if obs.complaint_target == "no_answer":
        # "쿼리가 안 돌아요" 도 '답이 없다' 로 읽힌다. 답변이 온전한데 코드가 깨져 있으면
        # 그게 답이다 - 아래 code 분기가 case27 로 보낸다 (지저분한 골든셋 code03).
        broken_code = obs.question_domain in ("code", "tool_usage") and any(
            _check(checks, n) is not None and _check(checks, n).violated
            for n in ("python_syntax", "sql_shape"))
        if not broken_code:
            return done(taxonomy.UNCLASSIFIED,
                        "답이 없거나 끊겼다는 불만 — 잘림 여부는 로그로 판정 불가",
                        ["출력 잘림(case8)일 수 있으나 텍스트로는 가릴 수 없다 — "
                         "생성의 finish_reason 이 있어야 판정된다"])

    # --- 3. 형식·언어·길이 요청 불이행 -----------------------------------------
    #
    # 불만이 그것을 가리킬 때만 본다. 요구가 있었는데 어겼고 사용자가 다른 것을
    # 불평한 경우는 secondary 로 잡는다 - 주 라벨은 사용자가 실제로 겪은 것이어야
    # 하지만, 어긴 사실 자체는 사라지면 안 된다.
    for target, check_name, case_id in REQUEST_CASES:
        if obs.complaint_target != target:
            continue
        verdict = _request_verdict(checks, check_name)
        if verdict == "violated":
            detail = _check(checks, check_name).detail
            return done(case_id, f"{target} 요구 위반 확인 — {detail}")
        if verdict == "ok":
            # 요구를 지켰는데도 불만이다. 형식 자체가 아니라 기대와 다른 것이다.
            return done("case13", f"{target} 요구는 지켰으나 사용자가 불만",
                        ["코드 검증은 통과 — 기대와 다른 답변 쪽으로 본다"])
        if verdict == "not_applicable":
            # **이전 질문들에 그런 요구가 없었다.** 후속 발화에서 처음 나온 요구는
            # 비판받은 답변이 따를 수 없었던 것이라, 어겼다고 할 수 없다. 불만 자체는
            # 진짜이므로 버리지 않고 "말하지 않은 기대와 달랐다" 로 둔다.
            return done("case13", f"{target} 불만이나 이전 질문들에 그런 요구가 없었음",
                        ["답변이 나올 때는 없던 요구다 — 어긴 것이 아니라 기대와 다른 것이다",
                         "판정자가 요구를 적었다면 인용 대조에서 지워진 것이다 "
                         "(observation.request_quote_verified 로 확인)"])
        # undetermined. 요구는 있었는데 코드가 잴 수 없다 - 길이가 언제나 여기다.
        # 불만이 그것을 가리키므로 case 는 유지하되 코드 근거가 없어 신뢰도를 낮춘다.
        result = done(case_id, f"{target} 요구는 있으나 코드가 판정할 수 없음")
        result.confidence = "medium"
        result.notes.append("코드 검증이 판정 불가 — LLM 판정에만 의존")
        return result

    # --- 3b. 말투·어조 ---------------------------------------------------------
    # 코드로 검증할 수단이 없다. 어조는 규칙으로 재기 어려워 관측에만 의존한다.
    if obs.complaint_target == "tone":
        return done("case16", "말투·어조·용어에 대한 불만")

    # --- 4. 일관성 ------------------------------------------------------------
    if obs.complaint_target == "inconsistency":
        return done(taxonomy.UNCLASSIFIED, "이전 답변과 다르다는 불만",
                    ["case19 — 교차 세션 비교가 필요해 턴 단위로는 판정 불가"])

    # --- 5. 내용 불만: 질문의 성격으로 갈린다 -----------------------------------
    if obs.question_domain == "general_knowledge":
        return done("case25", "상식 질문에 대한 불만",
                    ["판정자의 사전지식에 의존 — 표본 검토 필요"])

    if obs.question_domain == "calculation":
        for name, what in (("arithmetic", "등식"), ("dates", "날짜")):
            wrong = _check(checks, name)
            if wrong is not None and wrong.violated:
                return done("case26", f"{what} 오류 확인 — {wrong.detail}")
        result = done("case26", "계산 질문에 대한 불만")
        # 식을 명시하지 않은 계산은 코드로 검증할 수 없다. high 로 두면 안 된다.
        result.confidence = "medium"
        result.notes.append("답변에 검증 가능한 등식이 없음 — 자연어 계산은 판정 불가")
        return result

    if obs.question_domain in ("code", "tool_usage"):
        for name in ("python_syntax", "sql_shape"):
            broken = _check(checks, name)
            if broken is not None and broken.violated:
                return done("case27", f"코드 결함 확인 — {broken.detail}")
        return done("case27", "코드·도구 질문에 대한 불만",
                    ["문법은 통과 — 실행 검증 없이는 정확성을 확인할 수 없음"])

    if obs.question_domain == "domain":
        return _route_domain(obs, judgment, citation, grounding, done)

    # --- 6. 남은 것 -----------------------------------------------------------
    # case14 는 여기서만 주 라벨이 된다. 앞에 두면 case20/case22 을 가로챈다 —
    # 검색이 실패해 답변이 부실하면 모델은 그걸 "히스토리를 못 이어받았다"로도
    # 읽기 때문이다. 인용으로 검증된 문서 증거가 LLM 의 인상보다 강하다.
    if obs.answer_ignored_history:
        return done("case14", "답변이 이전 턴의 내용을 잊거나 잘못 연결함",
                    ["더 구체적인 원인을 찾지 못해 맥락 상실로 판정"])

    if obs.question_multi_intent and not obs.answer_covers_all_intents:
        return done("case15", "복합 질문의 일부만 답변함")

    if obs.complaint_target == "other":
        return done(taxonomy.OUT_OF_TAXONOMY, "불만 성격이 taxonomy 어디에도 맞지 않음")
    return done(taxonomy.UNCLASSIFIED,
                f"판별 실패 (complaint={obs.complaint_target}, "
                f"domain={obs.question_domain})")


def _route_domain(obs, judgment, citation, grounding, done) -> Classification:
    """TYPE5 분기 — 검증된 case20/case22 판별 로직을 그대로 쓴다.

    n_chunks 가 0 이면 검색 결과가 아예 없었다는 뜻이다. 이건 판정이 아니라
    로그에 적힌 사실이라 "가져온 문서가 요구를 충족하지 못했다"와 구분해 적는다.
    고칠 곳이 다르다 - 0건은 검색을 탈지 말지 정하는 쪽이나 검색기 자체이고,
    가져왔는데 빗나간 것은 임베딩·청킹이나 문서 쪽이다.
    """
    if judgment is None:
        return done(taxonomy.UNCLASSIFIED, "도메인 질문인데 충족도 판정이 없음")

    n_chunks = citation.n_chunks if citation else None
    # 인용이 하나도 검증되지 않은 sufficient/partial 주장은 사전지식에서 나온 것으로 본다.
    # 규칙은 final_verdict 한 곳에 있다 - grounding 이 물을지 정할 때도 같은 규칙을 본다.
    verdict = final_verdict(judgment, citation)
    downgraded = verdict != judgment.verdict

    if verdict in ("insufficient", "partial"):
        note = ["인용 검증 실패로 강등됨"] if downgraded else []
        if n_chunks == 0:
            note.append("서비스가 '검색 없이 답할 수 있다'고 판단했을 수 있다. "
                        "그 판단이 틀린 것이라면 고칠 곳은 검색 트리거다.")
            return done("case21", "검색 결과가 0건 — 대조할 문서가 아예 없음", note)
        note.append("검색 실패와 코퍼스 부재는 구분 불가 — 부서 편중으로만 추정")
        return done("case20", f"가져온 문서가 요구를 충족하지 못함 (verdict={verdict})", note)

    if grounding is None:
        return done("case20", "문서는 충분하나 활용 여부를 확인하지 못함")

    if grounding.answer_used_rag == "ignored":
        return done("case22", "문서에 답이 있는데 답변이 쓰지 않음")
    if grounding.answer_used_rag == "contradicted":
        return done("case18", "답변이 문서와 어긋나는 주장을 함",
                    ["문서와 대조 가능한 할루시네이션만 해당 — 문서 밖 허구는 판정 불가"])

    # 문서도 충분하고 답변도 썼는데 불만이다. 두 갈래로 갈린다.
    if not obs.answer_actionable:
        # 물은 것은 맞게 답했으나 행동으로 이어지지 않는 경우.
        return done("case17", "문서는 충분하나 답변이 두루뭉술해 다음 행동을 알 수 없음")
    return done("case13", "문서는 충분하고 활용했으나 사용자 기대와 다름")
