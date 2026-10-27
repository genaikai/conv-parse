"""분류 결과를 pre_data_format 형태로 낸다.

원본 포맷에 분류 결과를 덧붙인 모양이다. 기존 필드는 이름과 의미를 그대로 두고,
새로 붙는 것은 전부 `classification` 아래에 모은다 — 섞어 놓으면 나중에
"이 필드가 원본인가 우리가 붙인 건가"를 매번 확인해야 한다.

pre_queries / llm_ans_on_last_q / current_query / chunk_data 는 turn N+1(불만)과
turn N(비판받은 답변)을 짝지은 결과다. 원본 conv_eval 의 한 턴이 아니라는 점에 주의.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from typing import Optional

from ragdiag import settings
from ragdiag.results import TurnResult
if TYPE_CHECKING:                      # 런타임 의존을 만들지 않는다.
    # 쓰는 것은 .user 와 .chat_id 두 개뿐이다. 실행 환경에서는 그쪽
    # 파서가 만든 객체가 들어올 수 있으므로 런타임에 conv 를 붙들지 않는다.
    from ragdiag.conv import Conversation


def _check_payload(result: TurnResult) -> list[dict]:
    """코드 검증 결과. 위반과 미해당을 구분해서 싣는다."""
    return [
        {"name": check.name, "verdict": check.verdict, "detail": check.detail,
         **({"evidence": check.evidence} if check.evidence else {})}
        for check in result.checks.values()
        if check.verdict != "not_applicable"      # 요구가 없던 항목은 싣지 않는다
    ]


def grounding_of(result: TurnResult) -> str:
    """④ 주장 판정을 v2 의 한 칸(used · ignored · contradicted)으로 요약한다. 대시보드 호환."""
    verdicts = {v.verdict for v in result.claim_verdicts}
    if "contradicted" in verdicts or "tool_mismatch" in verdicts:
        return "contradicted"
    if "supported" in verdicts or "tool_ok" in verdicts:
        return "used"
    if result.claim_verdicts and result.overall_verdict() == "sufficient":
        return "ignored"
    return ""


def _evidence_payload(result: TurnResult) -> dict:
    """판정 근거. 왜 그 라벨이 나왔는지 사후에 추적할 수 있어야 한다."""
    payload: dict = {}
    if result.legibility_p is not None:
        payload["legibility"] = {"illegible_p": round(result.legibility_p, 3)}
    if result.observation:
        obs = result.observation
        payload["observation"] = {
            "resolved_question": obs.resolved_question,
            "unmet_need": obs.unmet_need,
            "complaint_target": obs.complaint_target,
            "question_domain": obs.question_domain,
            "question_clarity": obs.question_clarity,
            "question_multi_intent": obs.question_multi_intent,
            "answer_refused": obs.answer_refused,
            "answer_covers_all_intents": obs.answer_covers_all_intents,
            "answer_actionable": obs.answer_actionable,
            "answer_ignored_history": obs.answer_ignored_history,
            "answer_asked_back": obs.answer_asked_back,
            "requests_unsupported_output": obs.requests_unsupported_output,
            "requested_language": obs.requested_language,
            "requested_length_kind": obs.requested_length_kind,
            "requested_length_value": obs.requested_length_value,
            "requested_format": obs.requested_format,
        }
        if obs.history_quote:
            payload["observation"]["history_quote"] = obs.history_quote
            payload["observation"]["history_quote_verified"] = (
                result.history.verified if result.history else None)
        if result.request is not None:
            payload["observation"]["request_quote_verified"] = result.request.verified
    if result.probabilities:
        payload["probabilities"] = result.probabilities
    if result.sufficiency:
        overall = result.overall_verdict()
        best = result.best_sufficiency()
        evidence = []
        for key, s in result.sufficiency.items():
            for sup in s.supports:
                if sup.p >= settings.CHUNK_EVIDENCE_P:
                    evidence.append({"chunk_index": sup.chunk_index, "p": round(sup.p, 3),
                                     "source": sup.source, "scope": key})
        payload["sufficiency"] = {
            "verdict": overall,
            "final_verdict": overall,                 # 옛 결과 파일과 같은 자리
            "missing": (result.observation.unmet_need if result.observation
                        and overall != "sufficient" else ""),
            "verified": best.verified if best else None,
            "evidence": evidence,
            "scopes": {
                key: {"need": s.need, "verdict": s.verdict, "verified": s.verified,
                      "supports": [{"chunk_index": x.chunk_index, "p": round(x.p, 3),
                                    "source": x.source} for x in s.supports]}
                for key, s in result.sufficiency.items()
            },
        }
    if result.claim_verdicts:
        payload["claims"] = [
            {"text": v.text, "expected_source": v.expected_source, "verdict": v.verdict,
             "p": round(v.p, 3)} for v in result.claim_verdicts]
        payload["grounding"] = {"answer_used_rag": grounding_of(result)}
    if result.memory_use is not None:
        payload["memory"] = {"use": result.memory_use, "p": round(result.memory_p, 3)}
    if result.consistency:
        payload["consistency"] = {str(i): round(p, 3) for i, p in result.consistency.items()}
    if result.quotes:
        payload["quotes"] = result.quotes
    checks = _check_payload(result)
    if checks:
        payload["checks"] = checks
    return payload


def build_turn(result: TurnResult, source_turn_no: int) -> dict:
    case = result.case
    turn: dict = {
        "turn": case.turn,
        "pre_queries": case.pre_queries,
        "llm_ans_on_last_q": case.llm_ans_on_last_q,
        "current_query": case.current_query,
        "chunk_data": case.rag_chunks,
    }
    if result.error:
        turn["classification"] = {"error": result.error}
        return turn

    payload = result.classification.as_dict() if result.classification else {}
    payload["evidence"] = _evidence_payload(result)
    payload["llm_calls"] = result.n_calls
    payload["kev_calls"] = result.n_kev_calls
    # 답변을 만든 원본 턴. 짝짓기를 사후에 확인할 수 있어야 한다.
    payload["answered_turn"] = source_turn_no
    turn["classification"] = payload
    return turn


def build_output(pairs: list[tuple["Conversation", TurnResult]],
                 models: dict | None = None) -> dict:
    """(대화, 결과) 쌍들을 사용자 → 대화 → 턴 으로 다시 묶는다.

    models 가 있으면 `judged_by` 로 함께 남긴다 - 단계마다 모델이 다를 수 있어서
    "그 실행은 그 모델" 이 더는 성립하지 않는다. 실데이터를 가지고 나올 수 없는
    환경에서 판정의 출처가 파일에 없으면 나중에 해석할 방법이 없다.
    """
    users: dict[tuple, dict] = {}
    for conv, result in pairs:
        meta = conv.user
        # 사용자 식별자가 로그에서 없어졌다. 조직 속성 조합으로 묶는다 - 같은
        # 부서 · 직급 · 직무의 다른 사람이 한 노드로 합쳐지지만, 어차피 집계가
        # 보는 축이 그 셋이고 사례는 chat_id 로 되짚는다.
        key = (meta.dept, meta.job_grade, meta.job_name)
        user = users.setdefault(key, {
            "job_grade": meta.job_grade,
            "db_dept_name": meta.dept,
            "db_job_name": meta.job_name,
            "conversations": {},
        })
        conversation = user["conversations"].setdefault(
            conv.chat_id, {"chat_id": conv.chat_id, "turns": []}
        )
        conversation["turns"].append(build_turn(result, result.case.turn - 1))

    results = []
    for user in users.values():
        conversations = list(user.pop("conversations").values())
        for conversation in conversations:
            conversation["turns"].sort(key=lambda t: t["turn"])
        results.append({**user, "conversations": conversations})
    payload = {"analysis_results": results}
    if models:
        payload["judged_by"] = dict(models)
    return payload


def summarize(pairs: list[tuple["Conversation", TurnResult]]) -> str:
    """분류 분포. 어디를 고쳐야 하는지 보이게 하는 게 목적이다."""
    from collections import Counter

    from ragdiag import taxonomy
    from ragdiag.textfmt import pad, text_width

    ok = [r for _, r in pairs if r.classification]
    errors = [r for _, r in pairs if r.error]
    if not ok:
        return f"분류된 턴이 없습니다. (실패 {len(errors)}건)"

    failures = [r for r in ok if r.classification.primary_case != "N0"]
    lines = [
        "=" * 78,
        f"분류 결과  |  성공 {len(ok)}건 / 실패 {len(errors)}건  |  실패 라벨 {len(failures)}건 (N0 제외)",
        "=" * 78,
        "",
        "[1] 묶음 분포 (고칠 곳)",
    ]
    groups = Counter(taxonomy.describe(r.classification.primary_case)["type_id"] or "?" for r in ok)
    for gid, count in sorted(groups.items(), key=lambda kv: taxonomy.sort_key(kv[0] + "0")):
        g = taxonomy.GROUPS.get(gid)
        name = f"{gid}({g.word}) {g.name} — {g.owner}" if g else "(미분류)"
        lines.append(f"  {pad(name, 48)}{count:>5}  {count / len(ok):>5.1%}")

    lines += ["", "[2] 라벨 분포"]
    counts = Counter(r.classification.primary_case for r in ok)
    width = max(text_width(c) for c in counts) + 2
    for label_id in taxonomy.ordered(counts):
        count = counts[label_id]
        meta = taxonomy.describe(label_id)
        lines.append(f"  {pad(label_id, width)}{pad(meta['case_name'], 26)}"
                     f"{count:>5}  {count / len(ok):>5.1%}")

    lines += ["", "[3] 증거 등급 (신뢰도)"]
    grades = Counter(r.classification.grade for r in ok)
    names = {4: "4 코드 확정", 3: "3 근거 확정", 2: "2 확신", 1: "1 기울어짐", 0: "0 불일치"}
    for g in (4, 3, 2, 1, 0):
        if grades[g]:
            lines.append(f"  {pad(names[g], 14)}{grades[g]:>5}  {grades[g] / len(ok):>5.1%}")
    if grades[1] or grades[0]:
        lines.append("  └ 등급 1 · 0 은 표본 검토 대상이다. 다른 등급과 같은 무게로 집계하지 말 것.")

    tags = Counter(t for r in ok for t in r.classification.tags)
    if tags:
        lines += ["", "[4] 태그 (주 라벨과 별개로 남는 것)"]
        for tag, count in tags.most_common(15):
            lines.append(f"  {pad(tag, 18)}{pad(taxonomy.TAGS.get(tag, ''), 40)}{count:>5}")

    flags = Counter(f for r in ok for f in r.classification.flags)
    events = Counter(e for r in ok for e in r.classification.events)
    if flags or events:
        lines += ["", "[5] 무결성 플래그 · 이벤트 (실패율 분모 밖)"]
        for key, count in [*flags.items(), *events.items()]:
            lines.append(f"  {pad(key, 6)}{pad(taxonomy.describe(key)['case_name'], 24)}{count:>5}")
        if flags.get("C1"):
            lines.append("  └ C1 이 선 턴은 G2(맥락) 를 판정하지 않았다. 많으면 G2 집계를 보류할 것.")

    if errors:
        lines += ["", f"[!] 실패 {len(errors)}건"]
        for result in errors[:5]:
            lines.append(f"  {result.case.case_id}: {result.error}")

    calls = sum(r.n_calls for _, r in pairs)
    kev = sum(r.n_kev_calls for _, r in pairs)
    tokens_in = sum(r.usage.input_tokens for _, r in pairs)
    tokens_out = sum(r.usage.output_tokens for _, r in pairs)
    lines += ["", f"LLM 호출 {calls}회 · 결정(kev) 호출 {kev}회 | 입력 {tokens_in:,} | 출력 {tokens_out:,}"]
    return "\n".join(lines)
