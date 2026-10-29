"""v4 결정 트리 — 출구마다 하나씩, 파싱부터 결과까지 끝까지 돈다.

fixtures/v4_cases.py 의 사례를 conv_eval 모양의 대화로 접어 파서 · 짝짓기 · 플래그 · 네 단계를
전부 지나게 한다. kev 답은 사례에 적힌 대로 ScriptedBackend 가 낸다. 2차 판정의 LLM 답도 사례의
`second` 대로 — 안 적은 문항은 모름이라 kev 모름 사례는 전처럼 검토로 간다.
"""

from __future__ import annotations

import json

import pytest

from ragdiag import taxonomy
from ragdiag.backends import Usage
from ragdiag.conv import parse_conversations, to_case
from ragdiag.decide import ScriptedBackend
from ragdiag.features._shared import current_turn
from ragdiag.fixtures import v4_cases
from ragdiag.judge import Judge
from ragdiag.pipeline import judge_cases
from ragdiag.schema import Case

FIXTURES = {c["id"]: c for c in v4_cases.CASES}
ORG = {"db_dept_name": "공정기술팀", "db_job_name": "공정", "job_grade": "책임"}


def _raw_turn(no, question, answer, **extra):
    return {"turn": no, "event_time": f"2026-10-21 09:{no:02d}:00", "user_question": question,
            "llm_response": answer, "retrieved_data": json.dumps([]), "trace_matched": "True", **extra}


def make_case(fx: dict) -> Case:
    turns = [_raw_turn(i + 1, q, a) for i, (q, a) in enumerate(fx.get("prior", []))]
    n = len(turns) + 1
    answer_turn = _raw_turn(
        n, fx["question"], fx["answer"],
        retrieved_data=json.dumps(fx.get("retrieved", []), ensure_ascii=False),
        tool_output=fx.get("tool") or None, memory=fx.get("memory", ""),
        answered_by="rag", ask_on="web")
    if fx.get("history_chat") is not None:
        answer_turn["history_input"] = {
            "history_chat": [{"role": r, "content": c} for r, c in fx["history_chat"]],
            "retrieved_data": fx.get("history_retrieved", []), "tool_output": [],
            "memory": fx.get("memory", "")}
    turns += [answer_turn, _raw_turn(n + 1, fx["followup"], "", llm_emotion_result="불만")]
    [conv] = parse_conversations({"users": [{**ORG, "conversations": [
        {"chat_id": fx["id"], "turns": turns}]}]})
    return to_case(conv, n + 1)


def _script(state, questions) -> dict:
    fx = FIXTURES[current_turn().case.chat_id]
    if "complains" in questions:
        return fx.get("complaint", {})
    if "any" in questions:
        return fx.get("evidence", {})
    if "targeted" in questions:
        return {"targeted": fx.get("targeted", False)}
    return {}


class _LLM:
    """2차 판정용 일반 LLM. 사례의 second={문항 id: 답} 을 낸다. 없으면 모름."""

    model = "llm-scripted"

    def complete(self, system, user, out_model, hint=""):
        fx = FIXTURES[current_turn().case.chat_id]
        answers = fx.get("second", {})
        qid = next((q for q in answers if f"[{q}]" in user), None)
        return out_model(reasoning=f"사례 {fx['id']} 의 각본", answer=answers.get(qid, "모름")), Usage(1, 1)


def run(fx: dict):
    judge = Judge(backend=_LLM(), cache_dir=None, decision=ScriptedBackend(_script))
    [result] = judge_cases([make_case(fx)], judge, workers=1, progress=False)
    return result


@pytest.mark.parametrize("fx", v4_cases.CASES, ids=[c["id"] for c in v4_cases.CASES])
def test_each_case_lands_where_the_design_says(fx):
    r = run(fx)
    assert r.error is None, r.error
    e, v = fx["expect"], r.verdict
    detail = f"{fx['id']}: {v.bucket} @ {v.stopped_at} — {v.because} where={v.where} steps={[s.step for s in r.steps]}"
    assert v.bucket == e["bucket"], detail
    assert v.stopped_at == e["stopped_at"], detail
    assert v.sure == e["sure"], detail
    if e["because_key"]:
        assert v.because == taxonomy.BECAUSE[e["because_key"]], detail
    if "where" in e:
        assert v.where == e["where"], detail
    assert r.n_kev_calls == e["kev_calls"], detail
    assert r.n_calls == e.get("llm_calls", 0), detail
    assert v.second_pass == e.get("second_pass", ""), detail
    if "flags" in e:
        assert r.flags == e["flags"], detail


def test_every_exit_is_covered():
    seen = {fx["expect"]["because_key"] for fx in v4_cases.CASES if fx["expect"]["because_key"]}
    assert seen == set(taxonomy.BECAUSE), sorted(set(taxonomy.BECAUSE) - seen)
    assert {fx["expect"]["bucket"] for fx in v4_cases.CASES} == set(taxonomy.BUCKETS)
    stops = {fx["expect"]["stopped_at"].split(" · ")[0] for fx in v4_cases.CASES}
    assert stops == set(taxonomy.STEPS)


def test_kev_calls_never_exceed_three():
    assert all(fx["expect"]["kev_calls"] <= 3 for fx in v4_cases.CASES)


def test_fixture_ids_are_unique_and_notes_are_present():
    ids = [c["id"] for c in v4_cases.CASES]
    assert len(ids) == len(set(ids))
    assert all(c.get("note") for c in v4_cases.CASES)
