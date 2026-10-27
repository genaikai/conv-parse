"""③ 충족도 — **근거가 요구를 담고 있었나.** 청크마다 kev 가 yes/no 로 답한다.

v2 는 LLM 한 번에 verdict 와 인용을 받고 인용을 코드가 원문과 대조했다. v3 는 청크 하나씩
"이 청크가 질문에 답하는 내용을 담고 있나" 를 묻는다. yes 인 청크의 인덱스가 곧 근거라
인용 대조가 필요 없고, 입력이 청크 하나라 작은 모델로도 들어간다.

답변은 주지 않는다. 보여주면 판정자가 답변을 문서의 대리물로 착각한다.

세 가지를 따로 돈다.
  own / carried   이 턴이 가져온 근거와 history_input 으로 넘어온 과거 근거. 가르면 "이번
                  검색이 실패"(D1)와 "들고 있던 과거 근거에 답이 있었는데 안 씀"(G5[과거근거])
                  이 갈린다.
  질문 / 요구     1차는 resolved_question 으로 (불만 종류와 무관하게 언제나 정의된다).
                  내용 불만이면 unmet_need 로 좁혀 한 번 더 (`:need`).

**분기하지 않는다.** 형식 불만 턴에도 돈다 — 관측 하나가 틀려도 내용 결함이 태그로 남고,
관측 오류가 교차 검증된다 (정확성 우선). 문서 질문이 아니면(일상 · 계산 · 코드) 묻지 않는다 —
대조할 근거의 개념이 없다.

⑦ 2차 검증은 다른 문항으로 되묻는다. 불충분이면 "어디에도 없나", 충분이면 근거 청크마다
"이것만으로 답할 수 있나". 일치하면 D1 · G5 가 등급 3 으로 올라간다.
"""

import re

from ragdiag import questions, settings
from ragdiag.results import ChunkSupport, Sufficiency

from .._shared import call_kev, each_turn

NAME = "sufficiency"

CONTENT_COMPLAINTS = {"content_missing", "content_wrong"}

# --- v2 에서 온 헬퍼. 대시보드의 "요구" 열과 골든셋 러너가 아직 쓴다 -------------------
_ITEM_SPLIT = re.compile(r"\s*(?:,|·|/|、|\b및\b|\b그리고\b|\b또는\b)\s*")
_MULTI_QUESTION = re.compile(r"각각|,|및|그리고|(?<=[가-힣])(?:과|와)\s+[가-힣]")


def first_item(need: str) -> str:
    items = [x.strip() for x in _ITEM_SPLIT.split(need) if x.strip()]
    return items[0] if items else need


def narrow_need(unmet_need: str, multi_intent: bool) -> str:
    """질문이 한 가지를 물었으면 unmet_need 의 첫 항목만 (docs/design/sufficiency_step.md 4차)."""
    return unmet_need if multi_intent else first_item(unmet_need)


def question_looks_multi(question: str) -> bool:
    return bool(_MULTI_QUESTION.search(question))


def split_scopes(case) -> dict[str, list[int]]:
    """청크 인덱스를 own · carried 로 가른다. 출처가 history_ 로 시작하면 carried."""
    own, carried = [], []
    for i, source in enumerate(case.chunk_sources or ["retrieved"] * len(case.rag_chunks)):
        if source.startswith("history_"):
            carried.append(i)
        else:
            own.append(i)
    return {"own": own, "carried": carried}


def aggregate(scope: str, need: str, supports: list[ChunkSupport]) -> Sufficiency:
    result = Sufficiency(scope=scope, need=need, supports=supports)
    if any(s.p >= settings.CHUNK_EVIDENCE_P for s in supports):
        result.verdict = "sufficient"
    elif any(s.p >= settings.CHUNK_PARTIAL_P for s in supports):
        result.verdict = "partial"
    else:
        result.verdict = "insufficient"
    return result


def applies(turn) -> bool:
    return turn.doc_question()


def process_data(ctx) -> tuple[list, list]:
    def judge(turn):
        case, obs = turn.case, turn.observation
        if not case.rag_chunks:
            # 대조할 근거가 없다. 묻지 않고 insufficient 다 - T1 · T3 가 그 사실을 본다.
            turn.sufficiency["own"] = Sufficiency("own", obs.resolved_question, [],
                                                  "insufficient", verified=True)
            return
        scopes = split_scopes(case)
        needs = [("", obs.resolved_question)]
        if obs.complaint_target in CONTENT_COMPLAINTS and obs.unmet_need.strip() \
                and obs.unmet_need.strip() != obs.resolved_question.strip():
            needs.append((":need", obs.unmet_need))
        for scope, indices in scopes.items():
            if not indices:
                continue
            for suffix, need in needs:
                label = "질문" if suffix == "" else "요구"
                supports = []
                for i in indices:
                    answers = call_kev(turn, ctx, "sufficiency",
                                       {label: need, "청크": case.rag_chunks[i]},
                                       questions.sufficiency_question(label))
                    supports.append(ChunkSupport(i, answers["answers"].p,
                                                 case.chunk_sources[i] if case.chunk_sources else ""))
                turn.sufficiency[scope + suffix] = aggregate(scope + suffix, need, supports)
        _verify(turn, ctx)

    each_turn(ctx, NAME, judge, where=applies, parallel=True)
    return [], []


def _verify(turn, ctx) -> None:
    """⑦ 2차 검증. 종합 verdict 에 따라 다른 문항으로 되묻고 결과를 모든 scope 에 적는다."""
    case = turn.case
    overall = turn.overall_verdict()
    best = turn.best_sufficiency()
    if best is None or overall is None:
        return
    need = best.need
    if overall == "sufficient":
        evidence = sorted({i for s in turn.sufficiency.values() for i in s.evidence})
        agree = False
        for i in evidence:
            answers = call_kev(turn, ctx, "verify", {"요구": need, "청크": case.rag_chunks[i]},
                               questions.VERIFY_PRESENT)
            if answers["present"].yes:
                agree = True
                break
    else:
        answers = call_kev(turn, ctx, "verify",
                           {"요구": need, "청크들": list(case.rag_chunks)}, questions.VERIFY_ABSENT)
        agree = answers["absent"].yes
    for s in turn.sufficiency.values():
        s.verified = agree
