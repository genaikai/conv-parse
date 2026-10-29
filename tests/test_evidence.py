"""근거 판정 — 칸별은 어디, 전체가 있었나."""

from ragdiag.decide import ScriptedBackend
from ragdiag.features import evidence
from ragdiag.judge import Judge

from helpers import case, ctx, turn

SLOT_NAMES = ["이번 턴 검색 청크", "이번 턴 도구 결과", "앞 턴 근거", "메모리"]


def _case(slots: dict) -> "Case":
    chunks, sources = [], []
    for slot, src in (("retrieved", "retrieved"), ("tool", "tool:x"), ("history", "history_retrieved")):
        for c in slots.get(slot, []):
            chunks.append(c)
            sources.append(src)
    memory = "\n".join(slots.get("memory", []))
    return case(rag_chunks=chunks, chunk_sources=sources, memory=memory, n_fetched=len(chunks))


def _run(slots: dict, script: dict, capture: list | None = None):
    backend = ScriptedBackend(lambda state, questions: script)
    judge = Judge(backend=None, cache_dir=None, decision=backend)
    c = ctx(turn(case=_case(slots)), judge=judge)
    evidence.process_data(c)
    if capture is not None:
        capture.extend(backend.calls)
    return c.turns[0]


def test_all_slots_empty_closes_without_kev():
    t = _run(slots={}, script={})
    assert t.n_kev_calls == 0 and t.verdict.bucket == "evidence"
    assert t.verdict.where == SLOT_NAMES
    assert t.verdict.because == "청크도 도구 결과도 앞 턴 근거도 메모리도 없었다"
    assert t.steps[-1].answers["any"] == "비어 있어 묻지 않음"
    assert set(t.steps[-1].answers) == {"in_retrieved", "in_tool", "in_history", "in_memory", "any"}


def test_empty_slots_are_not_asked_and_state_names_slots_in_korean():
    calls = []
    _run(slots={"retrieved": ["청크"]}, script={"any": "all", "in_retrieved": True}, capture=calls)
    [(state, qids)] = calls
    assert set(qids) == {"in_retrieved", "any"}
    assert set(state) == {"question", "이번 턴 검색 청크"}
    assert state["이번 턴 검색 청크"] == ["청크"]


def test_all_means_generation_with_where():
    t = _run(slots={"retrieved": ["c"], "history": ["h"]},
             script={"in_retrieved": True, "in_history": False, "any": "all"})
    assert t.verdict.bucket == "generation" and t.verdict.where == ["이번 턴 검색 청크"]
    assert t.verdict.because == "근거에 답이 전부 있었는데 답변이 살리지 못했다"


def test_none_means_evidence_with_where():
    t = _run(slots={"retrieved": ["c"]}, script={"in_retrieved": False, "any": "none"})
    assert t.verdict.bucket == "evidence" and t.verdict.where == SLOT_NAMES


def test_partial_stays_open_even_if_every_slot_said_no():
    t = _run(slots={"retrieved": ["c"], "tool": ["t"]},
             script={"in_retrieved": False, "in_tool": False, "any": "partial"})
    assert t.is_open and t.steps[-1].answers["any"] == {"answer": "일부", "p": 0.95}


def test_slot_unsure_does_not_matter_when_any_is_confident():
    t = _run(slots={"retrieved": ["c"]}, script={"in_retrieved": 0.5, "any": "all"})
    assert t.verdict.bucket == "generation" and t.verdict.where == []


def test_any_unsure_is_review():
    t = _run(slots={"retrieved": ["c"]},
             script={"in_retrieved": True, "any": {"all": 0.5, "partial": 0.4, "none": 0.1}})
    assert t.verdict.bucket == "review"
    assert t.verdict.stopped_at == "근거 판정 · 근거 전체에 답이 있다"


def test_state_has_no_answer_and_no_followup():
    calls = []
    _run(slots={"retrieved": ["c"]}, script={"any": "none"}, capture=calls)
    [(state, _)] = calls
    assert "answer" not in state and "followup" not in state and state["question"] == "q"


def test_one_kev_call_when_anything_is_there():
    t = _run(slots={"memory": ["사용자는 WSPED01 담당"]}, script={"in_memory": True, "any": "all"})
    assert t.n_kev_calls == 1 and t.verdict.where == ["메모리"]
