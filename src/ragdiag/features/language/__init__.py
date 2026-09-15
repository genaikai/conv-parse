"""언어 — case10. 특정 언어를 요구했는데 지키지 않았나."""

from __future__ import annotations

import re
from typing import Optional

from ragdiag.results import Check

from .._shared import run_check

NAME = "language"


_SCRIPTS = {
    "hangul": re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]"),
    "latin": re.compile(r"[A-Za-z]"),
    "kana": re.compile(r"[぀-ヿ]"),
    "han": re.compile(r"[一-鿿]"),
}

# 한국어 답변에는 영문 용어가 흔히 섞인다("VPN 접속 시 MFA 인증").
# 그래서 다수결이 아니라 낮은 임계값으로 한글 존재 여부를 본다.
_HANGUL_THRESHOLD = 0.10


def script_profile(text: str) -> dict[str, float]:
    """문자 종류별 비율. 글자가 아닌 문자(숫자·기호·공백)는 분모에서 뺀다."""
    counts = {name: len(pattern.findall(text)) for name, pattern in _SCRIPTS.items()}
    total = sum(counts.values())
    if total == 0:
        return {name: 0.0 for name in counts}
    return {name: n / total for name, n in counts.items()}


def detect_language(text: str) -> str:
    """ko / en / ja / zh / unknown.

    한계: 스크립트 기반이라 라틴 문자를 쓰는 언어들(영어·독일어·프랑스어)을
    구분하지 못한다. 실행 환경 챗봇에서 실제로 갈리는 건 한국어와 영어라 이 수준이면 된다.
    """
    profile = script_profile(text)
    if sum(profile.values()) == 0:
        return "unknown"
    if profile["hangul"] >= _HANGUL_THRESHOLD:
        return "ko"
    if profile["kana"] > 0.05:
        return "ja"
    if profile["han"] > 0.3:
        return "zh"
    if profile["latin"] > 0.5:
        return "en"
    return "unknown"


def check_language(answer: str, requested: Optional[str]) -> Check:
    """case10 — 특정 언어를 요구했는데 지키지 않음."""
    if not requested:
        return Check("language", "not_applicable", "언어 요구 없음")
    actual = detect_language(answer)
    if actual == "unknown":
        return Check("language", "undetermined", "답변의 언어를 판별할 수 없음")
    if actual == requested:
        return Check("language", "ok", f"요구 {requested} · 실제 {actual}")
    return Check("language", "violated", f"요구 {requested} · 실제 {actual}")


def process_data(ctx) -> tuple[list, list]:
    return run_check(ctx, NAME, lambda t: check_language(
        t.case.llm_ans_on_last_q, t.observation.requested_language or None))
