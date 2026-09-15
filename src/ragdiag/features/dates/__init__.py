"""날짜 — case26 보강. 답변에 적힌 날짜가 달력에 있고, 요일 주장이 맞는가.

check_arithmetic 과 나눠 둔 이유: 저쪽의 미덕은 **ok 가 진짜 ok** 라는 것이다.
식을 계산하면 끝이라 가정이 없다. 날짜는 연도가 생략되는 등 판정할 수 없는
경우가 훨씬 잦아서, 한 검증기에 섞으면 ok 가 "둘 다 맞다" 인지 "하나만 봤다"
인지 구분되지 않는다.

**답변 텍스트만 본다.** 청크도 기준일도 공휴일표도 쓰지 않는다. 로그에는
계산의 기점이 없다 - 턴의 timestamp 는 "언제 물었나" 이지 기점이 아니다.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

from ragdiag.results import Check

from .._shared import run_check

NAME = "dates"


# "3월 13일" · "2026년 3월 13일". 월과 일이 **함께** 있을 때만 날짜로 본다 -
# "30일 이내"(기간) · "매월 25일"(반복) · "제30일차"(순번)는 대상이 아니다.
_DATE_KO = re.compile(
    r"(?:(?P<year>\d{4})\s*년\s*)?(?P<month>\d{1,2})\s*월\s*(?P<day>\d{1,2})\s*일"
)
# "2026-02-30" · "2026/2/30". 연도가 붙어 있어야 날짜로 본다.
_DATE_ISO = re.compile(r"(?P<year>\d{4})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2})")

_WEEKDAYS = "월화수목금토일"
# 날짜 **바로 뒤**의 요일 주장만 본다. 떨어져 있으면 무엇에 대한 주장인지 모른다.
_WEEKDAY_CLAIM = re.compile(r"[\s은는이가]*(?:요일은\s*)?(?P<weekday>[월화수목금토일])요일")


def _valid_date(year: Optional[int], month: int, day: int) -> Optional[bool]:
    """달력에 있는 날짜인가. 연도를 모르면 윤년을 가를 수 없어 None."""
    if not 1 <= month <= 12:
        return False
    if year is None:
        # 2월 29일은 연도에 따라 갈린다. 모르면 판정하지 않는다.
        return None if (month, day) == (2, 29) else 1 <= day <= _LONGEST_MONTH[month]
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


# 연도를 모를 때 쓰는 월별 최대 일수. 2월은 위에서 따로 처리한다.
_LONGEST_MONTH = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
                  7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def _dates_in(answer: str):
    """답변에 적힌 날짜를 (원문, 연도, 월, 일, 끝위치) 로. 연도는 없으면 None."""
    found = []
    for pattern in (_DATE_ISO, _DATE_KO):
        for m in pattern.finditer(answer):
            year = m.group("year")
            found.append((m.group(0), int(year) if year else None,
                          int(m.group("month")), int(m.group("day")), m.end()))
    return found


def check_dates(answer: str) -> Check:
    """답변에 적힌 날짜가 달력에 있는지, 요일 주장이 맞는지 본다.

    잡는 것 두 가지다.

    1. **없는 날짜** — "2월 30일" · "13월 1일". 사람이 오타로 쓸 일은 드물고
       모델이 그럴듯한 숫자를 채울 때 나온다. 맥락과 무관하게 틀렸으므로
       오탐이 원리적으로 없다.
    2. **요일 주장** — "2026년 3월 13일은 목요일입니다". 그레고리력 계산이라
       확정적이다. 다만 **연도가 없으면 판정하지 않는다** - timestamp 의 연도를
       갖다 쓰면 12월에 물어본 1월 일정에서 틀리고, 그 틀린 판정이 high 신뢰도로
       나간다. 모르는 것을 아는 척하지 않는 편이 낫다.

    영업일("5영업일 뒤")은 **일부러 보지 않는다.** 공휴일표 없이 주말만 빼면
    설·추석에 조용히 틀린다.
    """
    dates = _dates_in(answer)
    if not dates:
        return Check("dates", "not_applicable", "답변에 날짜 표기가 없음")

    wrong, unknown = [], 0
    for text, year, month, day, end in dates:
        ok = _valid_date(year, month, day)
        if ok is False:
            wrong.append(f"{text} — 달력에 없는 날짜")
            continue
        if ok is None:
            unknown += 1
            continue

        claim = _WEEKDAY_CLAIM.match(answer, end)
        if claim is None:
            continue
        if year is None:
            unknown += 1
            continue
        actual = _WEEKDAYS[date(year, month, day).weekday()]
        if claim.group("weekday") != actual:
            wrong.append(f"{text}{claim.group(0)} — 실제 {actual}요일")

    if wrong:
        return Check("dates", "violated",
                     f"날짜 {len(dates)}개 중 {len(wrong)}개 오류", evidence=wrong[:5])
    if unknown:
        return Check("dates", "undetermined",
                     f"날짜 {len(dates)}개 · 연도가 없어 판정 불가 {unknown}개")
    return Check("dates", "ok", f"날짜 {len(dates)}개 확인")


def process_data(ctx) -> tuple[list, list]:
    return run_check(ctx, NAME, lambda t: check_dates(t.case.llm_ans_on_last_q))
