"""검증기 여럿이 같이 쓰는 문자열 규칙. 기능이 아니므로 이름 앞에 밑줄을 둔다.

한 검증기만 쓰는 것은 그 폴더 안에 둔다. 여기 있는 것을 고치면 아래 적힌 검증기가
**함께** 바뀐다 - 목록 · 표 · 코드펜스를 format 과 (있다면 다른 검증기가) 같은
기준으로 봐야 한다. 전에는 truncated 도 여기 기댔다.
"""

import re

# 목록 · 표 · 코드펜스 — format(요구한 구조가 있나)
_NUMBERED = re.compile(r"^\s*(?:\d+[.)]|[①-⑳])\s+\S", re.M)
_BULLET = re.compile(r"^\s*[-*•·]\s+\S", re.M)
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.M)
_FENCE = re.compile(r"```")

# 코드 블록 — python_syntax · sql_shape
_CODE_BLOCK = re.compile(r"```(\w+)?\s*\n(.*?)```", re.S)


def extract_code_blocks(answer: str) -> list[tuple[str, str]]:
    return [(lang or "", body) for lang, body in _CODE_BLOCK.findall(answer)]
