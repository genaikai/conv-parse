"""개인정보 패턴 — "질문에 개인정보" 플래그의 재료. integrity 가 부른다.

앵커가 분명한 패턴만 잡는다. 숫자 나열을 전부 의심하면 오탐이 쏟아진다. 결과에는 종류와
건수만 남기고 원본 값은 남기지 않는다 — 안 그러면 결과 파일이 개인정보 사본이 된다.
"""

from __future__ import annotations

import re

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
        for match in pattern.finditer(text or ""):
            hits.append({"kind": kind, "text": match.group()})
    return hits
