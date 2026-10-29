"""시나리오 판정자 — case_id 의 경로 이름대로 답하는 Judge. LLM 도 kev 도 부르지 않는다.

    make_case("generation-all")       → 근거 판정에서 전부 → 생성
    make_case("review-complaint3")    → 불만 판정 거절 문항에서 모름 → 검토   (뒤의 숫자는 구분용)

파이프라인 **배관**을 재는 테스트(스냅숏 · 실행 방식 · 출력 모양 · 체크포인트)가 쓴다. 판정
내용은 의미가 없다 — 어느 단계가 돌고, 무엇을 넘겨받고, 무엇이 남는지를 본다.

어느 턴의 호출인지는 features._shared.current_turn() 으로 안다. 결정 백엔드의 state 에는
case_id 가 없기 때문이다.
"""

from __future__ import annotations

import hashlib
import json
import re

from ragdiag import settings
from ragdiag.decide import ScriptedBackend
from ragdiag.features._shared import current_turn
from ragdiag.judge import Judge
from ragdiag.schema import Case

CHUNK = "[출장규정 제3조] 국내 출장 식비는 1일 3만원을 상한으로 한다."

# 경로 이름 → (Case 재료, 단계별 kev 답). 열한 경로가 트리의 출구 전부다.
PATHS: dict[str, dict] = {
    "normal":            dict(complaint={"complains": False}),
    "system-code":       dict(answer=settings.SERVICE_ERROR_TEMPLATES[0]),
    "system-refusal":    dict(complaint={"complains": True, "refusal": True}),
    "generation-lang":   dict(complaint={"complains": True, "language": True}),
    "user-emotion":      dict(complaint={"complains": True, "emotion_only": True}),
    "evidence-empty":    dict(complaint={"complains": True}, chunks=[]),
    "evidence-none":     dict(complaint={"complains": True},
                              evidence={"in_retrieved": False, "any": "none"}),
    "generation-all":    dict(complaint={"complains": True},
                              evidence={"in_retrieved": True, "any": "all"}),
    "partial-yes":       dict(complaint={"complains": True},
                              evidence={"in_retrieved": True, "any": "partial"}, targeted=True),
    "partial-no":        dict(complaint={"complains": True},
                              evidence={"in_retrieved": True, "any": "partial"}, targeted=False),
    "review-complaint":  dict(complaint={"complains": True, "refusal": 0.55}),
}

_PATH = re.compile(r"^(?P<path>[a-z]+-?[a-z]*)\d*$")


def path_of(case_id: str) -> str:
    name = case_id.split(":", 1)[-1]
    m = _PATH.match(name)
    if not m or m.group("path") not in PATHS:
        raise KeyError(f"모르는 경로: {case_id}")
    return m.group("path")


def make_case(name: str, chat_id: str = "chat") -> Case:
    fx = PATHS[path_of(name)]
    chunks = fx.get("chunks", [CHUNK])
    return Case(
        case_id=f"{chat_id}:{name}", dept="부서", job_grade="직급", job_name="직무",
        chat_id=chat_id, turn=2,
        pre_queries=["국내 출장 식비 상한이 얼마인가요?"],
        llm_ans_on_last_q=fx.get("answer", "출장 식비는 회사 규정에 따라 지급됩니다."),
        current_query="부서별로 다르다는 게 아니라 규정상 정해진 금액이 있을 텐데요.",
        rag_chunks=chunks, chunk_sources=["retrieved"] * len(chunks), n_fetched=len(chunks),
        event_time="2026-10-21 09:02:00", target_event_time="2026-10-21 09:01:00",
        answered_by="rag", ask_on="web", history_present=True, prior_turn_nos=[1],
    )


def _script(state, questions) -> dict:
    fx = PATHS[path_of(current_turn().case.case_id)]
    if "complains" in questions:
        return fx.get("complaint", {})
    if "any" in questions:
        return fx.get("evidence", {})
    if "targeted" in questions:
        return {"targeted": fx.get("targeted", False)}
    return {}


class ScriptedJudge(Judge):
    def __init__(self):
        super().__init__(backend=None, cache_dir=None, decision=ScriptedBackend(_script))


def digest(payload: dict) -> str:
    """결과 한 턴의 verdict 를 비교용 해시로."""
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True)
                          .encode("utf-8")).hexdigest()[:16]


def scenarios() -> list[str]:
    return list(PATHS)
