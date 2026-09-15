"""출력 잘림 — case8. 답변이 문장 중간에서 끊겼나."""

from __future__ import annotations

import unicodedata

from ragdiag.results import Check

from .._shared import run_check
from .._text import _BULLET, _FENCE, _NUMBERED, _TABLE_ROW

NAME = "truncated"


# 정상 종결로 볼 문자. 한국어 종결어미(다./요.)는 마침표가 붙으므로 별도 처리 불필요.
_CLOSERS = tuple(".!?。」』】)]}…\"'`")

# 이모지 하나를 이루는 글자들. 범주로 뭉뚱그리면 안 된다 - 백틱(`)이 Sk 라서
# Sk 를 포함시켰다가 닫는 코드펜스(```)까지 벗겨 "코드블록이 닫히지 않음" 으로
# 뒤집혔다. 실제로 이모지를 만드는 것만 적는다.
#
#   So        그림문자 본체 (😊 ✅ ⚠ 🇰 ★)
#   FE0E/FE0F 이형 선택자 — ⚠️ 의 뒤쪽 한 글자
#   200D      ZWJ — 👨‍👩‍👧 처럼 여러 글자를 잇는 것
#   1F3FB~FF  피부색 수정자
_EMOJI_JOINERS = {"\ufe0e", "\ufe0f", "\u200d"} | {chr(c) for c in range(0x1F3FB, 0x1F400)}


def _is_pictograph(ch: str) -> bool:
    return ch in _EMOJI_JOINERS or unicodedata.category(ch) == "So"


def _strip_pictographs(text: str) -> str:
    """끝에 붙은 이모지 장식을 떼어낸다. 이형 선택자·ZWJ 까지 함께 떨어진다."""
    end = len(text)
    while end and _is_pictograph(text[end - 1]):
        end -= 1
    return text[:end].rstrip()


def check_truncated(answer: str) -> Check:
    """case8 — 답변이 문장 중간에서 끊김.

    한계: 정상 답변도 목록 항목이나 표로 끝나면 종결 부호가 없다. 그래서 그런
    구조를 먼저 걸러낸 뒤에만 잘림으로 본다. finish_reason 필드가 생기면
    이 휴리스틱은 필요 없어진다.

    **이모지로 끝나는 것은 완결의 신호다.** 생성이 끊기면 토큰 중간에서 멈추지,
    그 자리에 장식을 붙이고 멈추지 않는다. 그래서 종결 부호와 같은 무게로 본다 -
    한국어 답변은 마침표를 생략하고 이모지로 끝맺는 일이 흔하다.
    """
    raw = answer.rstrip()
    if not raw:
        return Check("truncated", "undetermined", "답변이 비어 있음")

    # 이모지를 떼고 본문을 본다. 떼지 않으면 "확인해 보세요! 👍" 처럼 마침표까지
    # 있는 답변이 종결 부호 검사에서 떨어진다.
    text = _strip_pictographs(raw)
    ends_with_emoji = text != raw
    if not text:
        return Check("truncated", "ok", "이모지로만 이루어진 답변")

    last_line = text.splitlines()[-1].strip()
    # 목록·표·코드블록으로 끝나는 건 정상이다.
    if (
        _TABLE_ROW.match(last_line)
        or _BULLET.match(last_line)
        or _NUMBERED.match(last_line)
        or last_line.endswith("```")
    ):
        return Check("truncated", "ok", "구조적 종결(목록·표·코드블록)")

    # 닫히지 않은 코드블록이 먼저다. 종결 부호 검사를 앞에 두면 코드 마지막 줄의
    # 괄호("print(1)")를 정상 종결로 오판한다.
    if len(_FENCE.findall(text)) % 2 == 1:
        return Check("truncated", "violated", "코드블록이 닫히지 않음")

    if text.endswith(_CLOSERS):
        tail = " + 이모지" if ends_with_emoji else ""
        return Check("truncated", "ok", f"종결 부호로 끝남: {text[-1]!r}{tail}")

    if ends_with_emoji:
        return Check("truncated", "ok", f"이모지로 끝남: {raw[len(text):].strip()!r}")

    return Check("truncated", "violated", f"종결 부호 없이 끝남: …{text[-20:]!r}")


def process_data(ctx) -> tuple[list, list]:
    return run_check(ctx, NAME, lambda t: check_truncated(t.case.llm_ans_on_last_q))
