"""③ 무결성 플래그와 이벤트 — 멈추지 않는다.

C(context) 플래그는 "이 턴의 기록을 믿을 수 없다" 다. 모델이 못 본 것인지 로그/적재가
떨어뜨린 것인지 로그만으로 못 가르므로 실패 라벨이 아니라 플래그다 — 실패율 분모 밖이고,
받는 쪽은 로그 · 적재 · 맥락 관리다. 효과는 하나다: C1 은 G2 전체를, C2 는 G2[memory] 만
후보에서 뺀다 (features/arbitrate/candidates.py). 맥락을 봤는지 모르는 모델에게 맥락
불이행을 물을 수 없다.

U2(질문에 개인정보)는 이벤트다. 사용자가 개인정보를 넣은 것과 답변이 나빴던 것은 독립
사건이라 멈추지 않고 그 턴의 답변을 끝까지 판정한다. 받는 쪽은 입력 마스킹(UI).
"""

from __future__ import annotations

import re

from ragdiag.results import Check

from .._shared import each_turn
from ..pii import find_pii

NAME = "integrity"

# memory 와 대화의 어휘 겹침. memory 는 **요약**이라 표현이 다르기 마련이다 - "신입" 처럼
# 대화에 안 나온 사실도 담는다. 그래서 비율이 아니라 "겹치는 내용어가 하나도 없는가" 로만 본다.
# 하나라도 겹치면 이 대화의 memory 다. 보수적으로 두는 이유: 오탐이면 그 턴의 G2[memory] 가
# 통째로 안 나온다.
MEMORY_MIN_WORDS = 3
_WORD = re.compile(r"[0-9A-Za-z가-힣]{2,}")


def _stems(text: str) -> set[str]:
    """내용어의 앞 두 글자. 조사 · 어미가 붙어도 같은 말로 본다 ("연차를" ↔ "연차")."""
    return {w[:2] for w in _WORD.findall(text or "")}


def check_missing_turns(case) -> Check:
    """C1 — history_chat 에 앞 턴이 빠졌나.

    비판받은 턴 N 의 history_input 은 ~N-1 까지라, 대화에 N 보다 앞선 턴이 k 개면
    history_chat 의 user 메시지도 k 개여야 한다. (prior_turn_nos 에는 N 자신이 들어 있어
    하나 뺀다.) history_input 이 없는 옛 로그는 판정하지 않는다 — 없음과 비었음은 다르다.
    """
    if not case.history_present:
        return Check("C1", "not_applicable", "history_input 없음 (옛 로그)")
    expected = max(len(case.prior_turn_nos) - 1, 0)
    got = case.history_turn_count
    if got < expected:
        return Check("C1", "violated",
                     f"앞 턴 {expected}개 중 history_chat 에 {got}개만 있음",
                     evidence=[f"prior_turn_nos={case.prior_turn_nos}"])
    return Check("C1", "ok", f"앞 턴 {expected}개 전부 history_chat 에 있음")


def memory_overlap(memory: str, dialogue: list[str]) -> float:
    words = _stems(memory)
    if not words:
        return 1.0
    pool: set[str] = set()
    for text in dialogue:
        pool |= _stems(text)
    if not pool:
        return 0.0
    return len(words & pool) / len(words)


def check_memory(case) -> Check:
    """C2 — memory 가 이 대화의 것이 맞나. 어휘 겹침으로 본다.

    memory 는 서비스가 들고 있던 사용자 정보다. 그 안의 낱말이 대화(앞 질문 · 앞 답변 ·
    이번 질문)에 거의 없으면 다른 대화의 memory 가 붙었거나 적재가 어긋난 것이다.
    대조할 대화가 아직 없으면(첫 턴) 판정하지 않는다.
    """
    if not case.memory.strip():
        return Check("C2", "not_applicable", "memory 없음")
    dialogue = [*case.pre_queries, *case.prior_answers, case.current_query]
    if not any(d.strip() for d in dialogue):
        return Check("C2", "not_applicable", "대조할 대화가 없음")
    if len(_stems(case.memory)) < MEMORY_MIN_WORDS:
        return Check("C2", "not_applicable", "memory 가 너무 짧아 대조하지 않음")
    ratio = memory_overlap(case.memory, dialogue)
    if ratio == 0.0:
        return Check("C2", "violated", "memory 의 내용어가 대화에 하나도 없음")
    return Check("C2", "ok", f"memory 어휘의 {ratio:.0%} 가 대화에 있음")


def check_question_pii(case) -> Check:
    hits = find_pii(case.last_query)
    if not hits:
        return Check("U2", "ok", "질문에 개인정보 없음")
    kinds = sorted({h["kind"] for h in hits})
    return Check("U2", "violated", f"질문에 {', '.join(kinds)} {len(hits)}건")


def process_data(ctx) -> tuple[list, list]:
    def apply(turn):
        for check in (check_missing_turns(turn.case), check_memory(turn.case)):
            turn.checks[check.name] = check
            if check.violated:
                turn.flags.append(check.name)
        pii = check_question_pii(turn.case)
        turn.checks["U2"] = pii
        if pii.violated:
            turn.events.append("U2")

    each_turn(ctx, NAME, apply)
    return [], []
