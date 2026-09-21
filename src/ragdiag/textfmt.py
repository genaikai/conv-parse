"""터미널 표 정렬용 표시 폭.

한글 · 한자는 터미널에서 두 칸을 차지하므로 len() 으로 채우면 표가 깨진다.
실행 요약 · 필터 리포트 · 골든셋 채점이 같은 규칙으로 맞춰야 해서 한 곳에 둔다.
"""

import unicodedata


def text_width(text: str) -> int:
    """표시 폭. 동아시아 넓은 글자(W · F)는 2, 나머지는 1."""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def pad(text: str, width: int, right: bool = False) -> str:
    """표시 폭 기준으로 채운다. right 면 오른쪽 정렬."""
    gap = " " * max(0, width - text_width(text))
    return gap + text if right else text + gap
