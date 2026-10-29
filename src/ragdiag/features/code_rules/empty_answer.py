"""빈 답변 — 판정할 답이 없다.

모델이 안 낸 것인지 로그 적재가 떨어뜨린 것인지는 못 가르지만, 어느 쪽이든 "판정할 답이 없다"
는 사실이라 시스템으로 보낸다. v3 는 "묻지 않는다" 로 흘려보냈다.
"""

import re

NAME = "empty_answer"


def check(answer: str) -> tuple[bool, str]:
    if not re.sub(r"\s+", "", answer or ""):
        return True, "답변이 비어 있음"
    return False, "답변이 있음"
