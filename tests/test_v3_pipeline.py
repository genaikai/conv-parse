"""v3 테스트셋을 파이프라인 끝까지 돌린다 — 라벨 · 태그 · 등급 · 플래그 · 이벤트가 설계대로 나오나.

사례마다 kev 가 낼 답과 LLM 이 낼 텍스트가 적혀 있다 (fixtures/v3_cases.py). 여기서 재는 것은
모델 품질이 아니라 **코드의 논리**다: 모델이 설계대로 답했을 때 코드가 설계대로 라벨을 내는가.
"""

from __future__ import annotations

import pytest

from ragdiag import settings, taxonomy
from ragdiag.backends import Usage
from ragdiag.decide import ScriptedBackend
from ragdiag.features._shared import current_turn
from ragdiag.fixtures import v3_cases
from ragdiag.judge import Judge
from ragdiag.pipeline import judge_cases
from ragdiag.schema import Case, Claim, Claims, ObservationText, QuotePair

FIXTURES = v3_cases.by_id()


def make_case(fx: dict) -> Case:
    chunks = list(fx.get("chunks") or [])
    return Case(case_id=fx["id"], dept="FAB1", job_grade="책임", job_name="공정",
                conversation_id=fx["id"], turn=len(fx["pre_queries"]) + 1,
                pre_queries=list(fx["pre_queries"]), llm_ans_on_last_q=fx["answer"],
                current_query=fx["complaint"], rag_chunks=chunks,
                chunk_sources=list(fx.get("sources") or ["retrieved"] * len(chunks)),
                n_fetched=len([s for s in (fx.get("sources") or ["retrieved"] * len(chunks))
                               if not s.startswith("history")]),
                prior_answers=list(fx.get("prior_answers") or []),
                memory=fx.get("memory", ""),
                tool_calls=list(fx.get("tool_calls") or []),
                tool_outputs=list(fx.get("tool_outputs") or []),
                history_present=fx.get("history_present", False),
                history_turn_count=fx.get("history_turn_count", 0),
                prior_turn_nos=list(fx.get("prior_turn_nos") or list(range(1, len(fx["pre_queries"]) + 1))))


def _fx() -> dict:
    return FIXTURES[current_turn().case.case_id]


def _script(state, questions) -> dict:
    fx = _fx()
    if "illegible" in questions:
        return {"illegible": bool(fx.get("illegible"))}
    if "complaint_target" in questions:
        return {**v3_cases.BASE, **(fx.get("kev") or {})}
    if "answers" in questions:
        p = fx.get("sufficiency", 0.05)
        if isinstance(p, list):
            chunk = state["청크"]
            idx = fx["chunks"].index(chunk)
            return {"answers": p[idx]}
        return {"answers": p}
    if "present" in questions:
        return {"present": fx.get("verify", True)}
    if "absent" in questions:
        return {"absent": fx.get("verify", True)}
    if "support" in questions:
        return {"support": fx.get("claim", "supported")}
    if "memory_use" in questions:
        return {"memory_use": fx.get("memory_use", "reflected")}
    if "contradicts" in questions:
        return {"contradicts": bool(fx.get("contradicts"))}
    return {}


class FixtureJudge(Judge):
    def __init__(self):
        super().__init__(backend=None, cache_dir=None, decision=ScriptedBackend(_script))

    def observe_text(self, case):
        fx = FIXTURES[case.case_id]
        text = fx.get("text") or {}
        return ObservationText(
            reasoning="r",
            resolved_question=text.get("resolved_question", case.pre_queries[-1]),
            unmet_need=text.get("unmet_need", "정확한 답"),
            requested_language=text.get("requested_language", ""),
            requested_length_value=text.get("requested_length_value", 0),
            history_quote=text.get("history_quote", "")), Usage(10, 5)

    def extract_claims(self, case):
        fx = FIXTURES[case.case_id]
        claims = [Claim(text=t, expected_source=s) for t, s in fx.get("claims", [])]
        return Claims(reasoning="r", claims=claims), Usage(10, 5)

    def quote_pair(self, answer, source, what):
        return QuotePair(answer_quote=answer[:10], source_quote=source[:10]), Usage(10, 5)


def run(fx: dict):
    saved = settings.SEARCH_TOOL_NAMES
    settings.SEARCH_TOOL_NAMES = tuple(fx.get("search_names") or ())
    try:
        [result] = judge_cases([make_case(fx)], FixtureJudge(), workers=1, progress=False)
    finally:
        settings.SEARCH_TOOL_NAMES = saved
    return result


@pytest.mark.parametrize("fx", v3_cases.CASES, ids=[c["id"] for c in v3_cases.CASES])
def test_each_case_lands_on_its_label(fx):
    result = run(fx)
    assert result.error is None, result.error
    c = result.classification
    detail = (f"{fx['id']}: {c.primary_case}({c.grade}) tags={c.tags} flags={c.flags} "
              f"events={c.events} candidates={[(x.label, x.grade) for x in c.candidates]} — {c.reason}")
    assert c.primary_case == fx["expect"], detail
    if "grade" in fx:
        assert c.grade == fx["grade"], detail
    assert set(fx.get("tags", ())) <= set(c.tags), detail
    assert c.flags == list(fx.get("flags", [])), detail
    assert c.events == list(fx.get("events", [])), detail


def test_the_set_covers_every_failure_label_flag_and_event():
    targeted = {c["expect"] for c in v3_cases.CASES}
    targeted |= {f for c in v3_cases.CASES for f in c.get("flags", [])}
    targeted |= {e for c in v3_cases.CASES for e in c.get("events", [])}
    missing = [l for l in taxonomy.LABELS if l not in targeted]
    assert not missing, missing


def test_fixture_ids_are_unique_and_notes_are_present():
    ids = [c["id"] for c in v3_cases.CASES]
    assert len(ids) == len(set(ids))
    assert all(c.get("note") for c in v3_cases.CASES)


def test_early_closed_turns_do_not_call_any_model():
    for fid in ("i1-service", "i2-repeat", "i2-template", "s2-injection", "s3-leak"):
        result = run(FIXTURES[fid])
        assert result.n_calls == 0 and result.n_kev_calls == 0, (fid, result.n_calls, result.n_kev_calls)
