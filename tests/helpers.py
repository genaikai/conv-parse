"""테스트 공용 — Case · 턴 · 실행 문맥을 손으로 만든다. LLM 도 kev 도 없다."""

from __future__ import annotations

from ragdiag.features._context import RunContext
from ragdiag.results import TurnResult
from ragdiag.schema import Case


def case(**kw) -> Case:
    base = dict(case_id="c:2", dept="d", job_grade="g", job_name="j", chat_id="c",
                turn=2, pre_queries=["q"], llm_ans_on_last_q="a", current_query="그게 아니고요",
                rag_chunks=["청크"], chunk_sources=["retrieved"], n_fetched=1,
                event_time="t2", target_event_time="t1")
    answer = kw.pop("answer", None)
    if answer is not None:
        base["llm_ans_on_last_q"] = answer
    base.update(kw)
    return Case(**base)


def turn(**kw) -> TurnResult:
    return TurnResult(case=kw.pop("case", None) or case(**kw))


def ctx(*turns: TurnResult, judge=None) -> RunContext:
    return RunContext(turns=list(turns), judge=judge, workers=1, progress=False)
