"""포맷 — case12. 특정 포맷을 요구했는데 지키지 않았나."""

from __future__ import annotations

import json
import re
from typing import Literal, Optional

from ragdiag.results import Check

from .._shared import run_check
from .._text import _BULLET, _FENCE, _NUMBERED, _TABLE_ROW

NAME = "format"

# Step 1 이 관측으로 뽑는 요구 형식. none 은 요구가 없었다는 뜻이라 여기 없다.
RequestedFormat = Literal[
    "numbered_list", "bullet_list", "table", "code_block", "json", "prose"
]


_TABLE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$", re.M)


def has_format(answer: str, kind: RequestedFormat) -> bool:
    if kind == "numbered_list":
        return len(_NUMBERED.findall(answer)) >= 2
    if kind == "bullet_list":
        return len(_BULLET.findall(answer)) >= 2
    if kind == "table":
        return len(_TABLE_ROW.findall(answer)) >= 2 and bool(_TABLE_SEP.search(answer))
    if kind == "code_block":
        return len(_FENCE.findall(answer)) >= 2
    if kind == "json":
        try:
            json.loads(_strip_fence(answer))
            return True
        except (ValueError, TypeError):
            return False
    if kind == "prose":
        # 줄글 요구는 목록이 없어야 지킨 것이다.
        return not (_NUMBERED.search(answer) or _BULLET.search(answer))
    return False


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\s*", "", stripped)
        stripped = re.sub(r"```\s*$", "", stripped)
    return stripped.strip()


def check_format(answer: str, requested: Optional[RequestedFormat]) -> Check:
    """case12 — 특정 포맷을 요구했는데 지키지 않음."""
    if not requested:
        return Check("format", "not_applicable", "포맷 요구 없음")
    if has_format(answer, requested):
        return Check("format", "ok", f"요구 {requested} 충족")
    return Check("format", "violated", f"요구 {requested} 인데 해당 구조가 없음")


def process_data(ctx) -> tuple[list, list]:
    return run_check(ctx, NAME, lambda t: check_format(
        t.case.llm_ans_on_last_q,
        None if t.observation.requested_format == "none" else t.observation.requested_format))
