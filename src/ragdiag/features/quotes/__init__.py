"""조건부 인용 — 어긋남 · 모순으로 판정된 쌍에서 두 구절을 글자 그대로 받아 둔다. 전달본용.

kev 는 문장을 못 만든다. 실무가 "어디가 어긋나나" 를 보려면 구절이 필요하므로, 판정이 끝난
자리(④b contradicted · ⑤ contradicted · ⑥ 모순)에만 일반 LLM 을 한 번 불러 인용 쌍을 받고
코드가 원문 대조한다. 대조에 떨어진 인용은 verified=False 로 남기되 **판정은 바꾸지 않는다.**
"""

from ragdiag import settings
from ragdiag.verify import verify_quote_in

from .._shared import call_llm, each_turn

NAME = "quotes"

MAX_PER_TURN = 3


def _targets(turn) -> list[tuple[str, str, str]]:
    """(종류, 근거 원문, 무엇이 어긋나나)."""
    case = turn.case
    out = []
    for v in turn.claim_verdicts:
        if v.verdict == "contradicted":
            source = "\n\n".join(case.rag_chunks[i] for i in v.chunk_indices) or "\n\n".join(case.rag_chunks)
            out.append(("G5:어긋남", source, f"주장: {v.text}"))
    if turn.memory_use == "contradicted":
        out.append(("G2:memory", case.memory, "답변이 사용자 정보와 어긋나는 전제로 답했다"))
    for i, p in turn.consistency.items():
        if p >= settings.KEV_CONFIDENT and i < len(case.prior_answers):
            out.append(("G2:모순", case.prior_answers[i], "앞 답변과 다른 사실을 말한다"))
    return out[:MAX_PER_TURN]


def applies(turn) -> bool:
    return bool(_targets(turn))


def process_data(ctx) -> tuple[list, list]:
    def fetch(turn):
        answer = turn.case.llm_ans_on_last_q
        for kind, source, what in _targets(turn):
            pair = call_llm(turn, ctx.judge.quote_pair(answer, source, what))
            a_ok = verify_quote_in(pair.answer_quote, [answer], settings.UTTERANCE_MIN_QUOTE_CHARS)
            s_ok = verify_quote_in(pair.source_quote, [source], settings.UTTERANCE_MIN_QUOTE_CHARS)
            turn.quotes.append({"kind": kind, "answer_quote": pair.answer_quote,
                                "source_quote": pair.source_quote,
                                "verified": bool(a_ok.verified and s_ok.verified)})

    each_turn(ctx, NAME, fetch, where=applies, parallel=True)
    return [], []
