"""⑦ 중재 — 후보 전부에서 주 라벨 하나를 증거 등급으로 고른다. LLM 없음.

등급이 높은 후보가 이기고, 같으면 taxonomy.ORDER 의 앞이 이긴다. 나머지 후보는 태그로
내려간다. 신뢰도는 주 라벨의 등급이다 — taxonomy 표의 고정값이 아니다.

G3(의도와 다른 답)은 등급 1 하나뿐이라 구조적으로 아무것도 삼키지 못한다. 후보가 하나도
없으면 unclassified(등급 0) 다 — "문제 없음" 이 아니라 수동 검토 대상이다.

short_circuit · legibility 가 턴을 일찍 닫을 때도 같은 close() 를 쓴다. 그래야 플래그 ·
이벤트 · 그때까지 돈 검증기 태그가 같은 모양으로 실린다.
"""

from __future__ import annotations

from typing import Optional

from ragdiag import taxonomy
from ragdiag.results import Candidate, Classification, TurnResult

from .._shared import each_turn
from .candidates import candidates_for, global_tags

__all__ = ["NAME", "process_data", "arbitrate", "close", "candidates_for"]

NAME = "arbitrate"


def pick(candidates: list[Candidate]) -> Optional[Candidate]:
    if not candidates:
        return None
    return min(candidates, key=lambda c: (-c.grade, c.order))


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def classify(turn: TurnResult, candidates: list[Candidate]) -> Classification:
    primary = pick(candidates)
    tags = global_tags(turn)
    for c in candidates:
        tags += c.tags
    if primary is None:
        notes = ["어느 후보도 확신이 없다 — 표본 검토 대상"]
        if turn.observation is not None:
            notes.append(f"complaint={turn.observation.complaint_target}, "
                         f"domain={turn.observation.question_domain}")
        return Classification(
            primary_case=taxonomy.UNCLASSIFIED, confidence="low", grade=0,
            reason="판별 실패 — 후보 없음", tags=_dedupe(tags), notes=notes,
            flags=list(turn.flags), events=list(turn.events), candidates=list(candidates))
    secondary = _dedupe([c.label for c in candidates if c.label != primary.label])
    notes = list(primary.notes)
    for c in candidates:
        if c is not primary and c.grade >= primary.grade and c.label != primary.label:
            notes.append(f"{c.label} 도 같은 등급으로 성립 ({c.reason}) — 순서로 {primary.label} 을 택함")
    return Classification(
        primary_case=primary.label,
        confidence=taxonomy.confidence_of(primary.grade),
        grade=primary.grade,
        reason=primary.reason,
        secondary_cases=secondary,
        tags=_dedupe(tags),
        notes=notes,
        flags=list(turn.flags),
        events=list(turn.events),
        candidates=list(candidates),
    )


def arbitrate(turn: TurnResult) -> Classification:
    turn.candidates = candidates_for(turn)
    turn.classification = classify(turn, turn.candidates)
    return turn.classification


def close(turn: TurnResult, label: str, grade: int, reason: str,
          tags: Optional[list[str]] = None, notes: Optional[list[str]] = None) -> Classification:
    """일찍 닫는다 (short_circuit · legibility). 후보는 그 하나다."""
    turn.candidates = [Candidate(label, grade, reason, list(tags or []), list(notes or []))]
    turn.classification = classify(turn, turn.candidates)
    return turn.classification


def process_data(ctx) -> tuple[list, list]:
    each_turn(ctx, NAME, arbitrate)
    return [], []
