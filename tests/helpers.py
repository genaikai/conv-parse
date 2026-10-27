"""테스트 공용 — 관측 · 검증기 · 턴을 손으로 만든다. LLM 없음."""

from __future__ import annotations

from ragdiag.results import Check, TurnResult
from ragdiag.schema import Case, Observation

CHECK_NAMES = ("pii", "quoted_spans", "python_syntax", "sql_shape", "arithmetic", "dates",
               "injection", "tool_numbers", "language", "format", "length")


def obs(**kw) -> Observation:
    base = dict(
        reasoning="r", resolved_question="q", unmet_need="n",
        complaint_target="content_missing", question_domain="domain",
        question_clarity="clear", question_multi_intent=False,
        answer_refused=False, requested_language="",
        requested_length_kind="none", requested_length_value=0,
        requested_format="none",
        requests_unsupported_output=False,
        answer_covers_all_intents=True, answer_actionable=True,
        answer_ignored_history=False, answer_asked_back=False,
    )
    base.update(kw)
    return Observation(**base)


def checks(**kw) -> dict[str, Check]:
    table = {name: Check(name, "not_applicable") for name in CHECK_NAMES}
    table.update(kw)
    return table


def case(**kw) -> Case:
    base = dict(case_id="c:2", dept="d", job_grade="g", job_name="j", chat_id="c",
                turn=2, pre_queries=["q"], llm_ans_on_last_q="a", current_query="그게 아니고요",
                rag_chunks=["청크"], chunk_sources=["retrieved"], n_fetched=1)
    base.update(kw)
    return Case(**base)


def probs(**kw) -> dict:
    """turn.probabilities 를 손으로. noul 은 p, choice 는 {선택지: p}."""
    out = {}
    for qid, value in kw.items():
        if isinstance(value, dict):
            best = max(value, key=value.get)
            out[qid] = {"type": "choice", "p": value[best], "choice": best, "probabilities": value}
        else:
            out[qid] = {"type": "noul", "p": float(value)}
    return out


def turn(observation=None, *, checks_=None, probabilities=None, **kw) -> TurnResult:
    t = TurnResult(case=kw.pop("case", None) or case(), observation=observation,
                   checks=checks_ if checks_ is not None else checks(), **kw)
    if probabilities:
        t.probabilities.update(probabilities)
    return t
