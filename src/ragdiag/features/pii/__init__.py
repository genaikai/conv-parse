"""개인정보 — case6. 질문에 개인 · 민감정보가 들어 있나."""

from __future__ import annotations

import re

from ragdiag.results import Check

from .._shared import run_check

NAME = "pii"


# 앵커가 분명한 패턴만 잡는다. 숫자 나열을 전부 의심하면 오탐이 쏟아진다.
_PII_PATTERNS = {
    "주민등록번호": re.compile(r"\b\d{6}[-\s]?[1-4]\d{6}\b"),
    "휴대전화": re.compile(r"\b01[016-9][-\s]?\d{3,4}[-\s]?\d{4}\b"),
    "이메일": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b"),
    "카드번호": re.compile(r"\b(?:\d{4}[-\s]){3}\d{4}\b"),
    "계좌번호": re.compile(r"\b\d{2,3}-\d{2,6}-\d{2,6}\b"),
}


def find_pii(text: str) -> list[dict]:
    hits = []
    for kind, pattern in _PII_PATTERNS.items():
        for match in pattern.finditer(text):
            hits.append({"kind": kind, "text": match.group()})
    return hits


def check_pii(text: str) -> Check:
    """case6 — 질문에 개인·민감정보가 포함됨."""
    hits = find_pii(text)
    if not hits:
        return Check("pii", "ok", "검출 없음")
    kinds = sorted({h["kind"] for h in hits})
    # 원본 값은 남기지 않는다. 종류와 개수만으로 충분하다.
    return Check("pii", "violated", f"{', '.join(kinds)} {len(hits)}건")


def process_data(ctx) -> tuple[list, list]:
    # 답변이 아니라 그 답변을 부른 질문을 본다 - case6 은 "질문에" 개인정보가 있는 경우다.
    return run_check(ctx, NAME, lambda t: check_pii(t.case.last_query))
