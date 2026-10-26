"""도구 수치 대조 — 답변의 숫자 · 식별자가 도구 결과에 있는가. 코드만.

도구 결과는 JSON 이라 LLM 이 읽을 필요가 없다. 답변이 "장비 12대", "WSPED01 라인" 처럼
수치와 식별자를 단정했는데 그 값이 도구 outputs 어디에도 없으면 모델이 만든 것이다.

두 모양을 잡는다.
  빈 결과에 단정   도구를 불렀는데 outputs 가 비었거나 0건인데 답변에 수치가 있다 → T3 의 근거
  값 불일치        outputs 가 있는데 답변의 수치 · 식별자가 거기 없다 → G5[어긋남] 성격의 태그

사용자가 질문에 적은 숫자(기간 · 수량)는 뺀다 — 답변이 그것을 되풀이한 것은 도구 결과가
아니어도 당연하다. 10 미만의 작은 숫자도 뺀다 — 목록 번호 · "3가지" 같은 것이 전부 걸린다.
"""

from __future__ import annotations

import json
import re

from ragdiag.results import Check

from .._shared import run_check

NAME = "tool_numbers"

# 경계를 ASCII 영숫자로만 잡는다 - \w 로 두면 "12대" 의 "대" 가 글자라 숫자를 못 잡고,
# "WSPED01" 은 영문 뒤라 식별자 쪽으로 넘어가야 한다.
_NUMBER = re.compile(r"(?<![A-Za-z0-9.])\d[\d,]*(?:\.\d+)?(?![A-Za-z0-9.])")
# 영문자와 숫자가 섞인 코드. 장비명 · 라인명 · 로트 번호가 이 꼴이다.
_IDENT = re.compile(r"\b(?=[A-Za-z0-9_-]*[A-Za-z])(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{3,}\b")
_EMPTY_JSON = re.compile(r'"(?:count|total|n|size)"\s*:\s*0\b|^\s*(?:\[\s*\]|\{\s*\}|null)\s*$')


def _norm_number(text: str) -> str:
    text = text.replace(",", "")
    try:
        value = float(text)
    except ValueError:
        return text
    return str(int(value)) if value.is_integer() else str(value)


def outputs_are_empty(outputs: list[str]) -> bool:
    """전부 비었거나 0건 · 빈 배열 · null 인가."""
    if not outputs:
        return True
    return all(not o.strip() or _EMPTY_JSON.search(o.strip()) for o in outputs)


def numbers_in(text: str) -> set[str]:
    return {_norm_number(m) for m in _NUMBER.findall(text)}


def idents_in(text: str) -> set[str]:
    return {m.lower() for m in _IDENT.findall(text)}


def check_tool_numbers(answer: str, tool_calls: list[dict], outputs: list[str],
                       questions: list[str]) -> Check:
    if not tool_calls and not outputs:
        return Check(NAME, "not_applicable", "도구 호출 없음")
    asked = set()
    for q in questions:
        asked |= numbers_in(q) | idents_in(q)
    claimed_numbers = {n for n in numbers_in(answer) if n not in asked and _big(n)}
    claimed_idents = {i for i in idents_in(answer) if i not in asked}
    if outputs_are_empty(outputs):
        if claimed_numbers or claimed_idents:
            sample = sorted(claimed_numbers | claimed_idents)[:5]
            return Check(NAME, "violated",
                         f"빈결과: 도구 결과가 비었는데 답변에 수치 · 식별자 {len(sample)}개",
                         evidence=sample)
        return Check(NAME, "ok", "도구 결과가 비었고 답변도 수치를 단정하지 않음")
    haystack = " ".join(outputs)
    have_numbers = numbers_in(haystack)
    have_idents = idents_in(haystack)
    # JSON 안의 숫자는 따옴표 · 콜론 옆에 있어 _NUMBER 의 경계에 걸리므로 느슨하게 한 번 더
    have_numbers |= {_norm_number(m) for m in re.findall(r"\d[\d,]*(?:\.\d+)?", haystack)}
    missing = sorted({n for n in claimed_numbers if n not in have_numbers}
                     | {i for i in claimed_idents if i not in have_idents})
    if missing:
        return Check(NAME, "violated",
                     f"답변의 수치 · 식별자 {len(missing)}개가 도구 결과에 없음",
                     evidence=missing[:5])
    if not claimed_numbers and not claimed_idents:
        return Check(NAME, "not_applicable", "답변에 대조할 수치 · 식별자 없음")
    return Check(NAME, "ok", f"답변의 수치 · 식별자 {len(claimed_numbers | claimed_idents)}개가 도구 결과에 있음")


def _big(n: str) -> bool:
    try:
        return abs(float(n)) >= 10
    except ValueError:
        return True


def process_data(ctx) -> tuple[list, list]:
    # 후속 발화는 빼고 **앞 질문들만** 넘긴다. 사용자가 불만에서 답변의 숫자를 되풀이하는 것
    # ("12대 아닌데요")은 당연한데, 그걸 "사용자가 준 숫자" 로 치면 단정이 전부 빠져나간다.
    return run_check(ctx, NAME, lambda t: check_tool_numbers(
        t.case.llm_ans_on_last_q, t.case.tool_calls, t.case.tool_outputs, list(t.case.pre_queries)))
