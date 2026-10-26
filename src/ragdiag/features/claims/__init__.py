"""④ 근거 활용 — 답변의 사실 주장 하나하나가 근거와 어떤 관계인가.

v2 의 grounding 은 답변 전체에 used / ignored / contradicted 한 칸이었다. v3 는 주장 단위다.
④a 일반 LLM 이 답변에서 사실 주장을 **글자 그대로** 뽑고 기대 출처(doc · tool · general)를
붙인다. ④b 는 출처별로 다르게 검증한다.

  doc      kev 가 주장 × 근거 청크들 → supported / contradicted / not_found
  tool     코드가 수치 · 식별자를 도구 outputs 와 대조 (tool_numbers 의 함수)
  general  대조할 것이 없다 → 미검증주장 태그

문서 질문이고 근거가 있을 때만 돈다. 근거가 충분했는데 doc 주장이 하나도 supported 가 아니면
G5[안씀], contradicted 가 있으면 G5[어긋남] 이다 (arbitrate/candidates.py).
"""

from ragdiag import questions, settings
from ragdiag.results import ClaimVerdict

from .._shared import call_kev, call_llm, each_turn
from ..tool_numbers import idents_in, numbers_in

NAME = "claims"

# 주장 하나에 같이 주는 근거 청크 상한. 충족도 p 가 높은 순이다.
MAX_EVIDENCE_CHUNKS = 8


def evidence_chunks(turn) -> list[int]:
    """충족도에서 p 가 partial 선 이상인 청크. 없으면 전부 (상한까지)."""
    scored: dict[int, float] = {}
    for s in turn.sufficiency.values():
        for sup in s.supports:
            scored[sup.chunk_index] = max(scored.get(sup.chunk_index, 0.0), sup.p)
    picked = [i for i, p in sorted(scored.items(), key=lambda kv: -kv[1])
              if p >= settings.CHUNK_PARTIAL_P]
    if not picked:
        picked = list(range(len(turn.case.rag_chunks)))
    return picked[:MAX_EVIDENCE_CHUNKS]


def applies(turn) -> bool:
    return turn.doc_question() and bool(turn.case.rag_chunks)


def process_data(ctx) -> tuple[list, list]:
    def judge(turn):
        case = turn.case
        claims = call_llm(turn, ctx.judge.extract_claims(case))
        turn.claims = claims
        indices = evidence_chunks(turn)
        chunks = [case.rag_chunks[i] for i in indices]
        for claim in claims.claims:
            if claim.expected_source == "doc":
                answers = call_kev(turn, ctx, "claim", {"주장": claim.text, "근거 청크들": chunks},
                                   questions.CLAIM)
                a = answers["support"]
                turn.claim_verdicts.append(ClaimVerdict(claim.text, "doc", a.choice, a.p, indices))
            elif claim.expected_source == "tool":
                turn.claim_verdicts.append(_tool_verdict(claim.text, case))
            else:
                turn.claim_verdicts.append(ClaimVerdict(claim.text, "general", "unverified"))

    each_turn(ctx, NAME, judge, where=applies, parallel=True)
    return [], []


def _tool_verdict(text: str, case) -> ClaimVerdict:
    if not case.tool_outputs:
        return ClaimVerdict(text, "tool", "not_found", 1.0)
    haystack = " ".join(case.tool_outputs)
    want = numbers_in(text) | idents_in(text)
    if not want:
        return ClaimVerdict(text, "tool", "unverified")
    have = numbers_in(haystack) | idents_in(haystack)
    missing = want - have
    return ClaimVerdict(text, "tool", "tool_mismatch" if missing else "tool_ok", 1.0)
