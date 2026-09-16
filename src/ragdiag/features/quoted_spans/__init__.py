"""답변 속 인용 대조 — case24. 답변이 문서에서 가져왔다고 제시한 것이 실제로 그런가."""

from __future__ import annotations

import re

from ragdiag import settings
from ragdiag.results import Check
from ragdiag.verify import match_ratio, normalize

from .._shared import run_check
from .._text import _CODE_BLOCK

NAME = "quoted_spans"


# verify.py 와 방향이 반대다. 거기서는 판정자의 인용을 검증하고, 여기서는
# 챗봇 답변이 문서에서 가져왔다고 제시한 문장을 검증한다. 같은 대조 함수를 쓴다.
#
# 여는 부호와 닫는 부호를 한 문자 집합으로 묶어 섞여 있어도 잡는다 - 모델이
# `“…"` 처럼 짝을 어긋나게 내는 일이 흔하다.
#
# 곧은 작은따옴표(')만 앞뒤로 가드를 둔다. 영어 축약형이 짝처럼 보이기 때문이다:
#   "you don't need to worry, it isn't required"
#      → 두 어포스트로피 사이가 23자라 인용으로 잡힌다.
# 글자·숫자에 붙어 있으면 어포스트로피로 보고 넘어간다.
_QUOTE_PATTERNS = [
    re.compile(r"[“\"]([^”\"]{10,200})[”\"]"),                    # 큰따옴표
    re.compile(r"‘([^’‘]{10,200})’"),                              # 둥근 작은따옴표
    re.compile(r"(?<![A-Za-z0-9])'([^']{10,200})'(?![A-Za-z0-9])"),  # 곧은 작은따옴표
]

# 제목 부호. 한국어에서 이 안에 들어가는 것은 **문장이 아니라 문서 이름**이다.
# 문장 인용과 통을 나누는 이유: 대조 대상이 다르다. 문장은 청크 본문과 맞춰야 하고
# 문서명은 청크 머리의 출처 표기와 맞춰야 한다. 한 통에 넣고 본문과 대조하면
# **정확히 인용한 답변까지 위반으로 나온다** - 본문에 문서명이 적혀 있을 리 없다.
_SOURCE_PATTERNS = [re.compile(r"[「『《〈]([^」』》〉\n]{2,60})[」』》〉]")]

# 청크 머리의 출처 표기. 본문 앞에 붙어서 온다:
#   "[정보보호정책 시행세칙 제7조] 사내 자료의 외부 반출은 보안심의를 거쳐야 한다."
# 어떤 괄호를 쓸지는 운영 로그가 정하므로 흔한 것을 모두 받는다.
_CHUNK_SOURCE = re.compile(r"^\s*[\[\(「『《【]([^\]\)」』》】\n]{1,80})[\]\)」』》】]")
ANSWER_QUOTE_MIN_CHARS = settings.ANSWER_QUOTE_MIN_CHARS
# 옛 이름. verify.py 의 동명 상수와 재는 대상이 다르다 - 이쪽은 답변이 인용부호로
# 제시한 문장, 저쪽은 판정자가 근거로 제출한 인용이다.
MIN_QUOTE_CHARS = ANSWER_QUOTE_MIN_CHARS


# 인라인 코드 `...`. 코드펜스는 _text._CODE_BLOCK 이 잡는다.
_INLINE_CODE = re.compile(r"`[^`\n]+`")


def _prose_only(answer: str) -> str:
    """코드 블록과 인라인 코드를 걷어낸 본문. 인용 대조는 산문에서만 한다.

    SQL 의 `'2026-04-01'` 같은 문자열 리터럴이 인용문으로 잡혀 "검색 결과 0건인데 인용"
    위반이 났다 (지저분한 골든셋 code01). 코드 안의 따옴표는 문서를 인용한 것이 아니다.
    """
    return _INLINE_CODE.sub(" ", _CODE_BLOCK.sub(" ", answer))


def extract_quotes(answer: str) -> list[str]:
    """답변이 인용부호로 제시한 **문장**. 제목 부호 안의 문서명과 코드 안은 빼고 센다."""
    prose = _prose_only(answer)
    quotes = []
    for pattern in _QUOTE_PATTERNS:
        quotes += [q.strip() for q in pattern.findall(prose)]
    return [q for q in quotes if len(normalize(q)) >= settings.ANSWER_QUOTE_MIN_CHARS]


def extract_sources(answer: str) -> list[str]:
    """답변이 제목 부호로 댄 **문서 이름**. 코드 안은 빼고 센다.

    길이 하한이 문장 인용보다 훨씬 낮다. 「휴가규정」은 정규화하면 4자인데,
    문장 기준(10자)을 그대로 쓰면 짧은 문서명이 조용히 빠진다 - 실제로
    「연차휴가 운영지침」(8자)이 그래서 검증을 통째로 건너뛰고 있었다.
    """
    prose = _prose_only(answer)
    names = []
    for pattern in _SOURCE_PATTERNS:
        names += [n.strip() for n in pattern.findall(prose)]
    return [n for n in names if len(normalize(n)) >= 2]


def chunk_sources(chunks: list[str]) -> list[str]:
    """청크 머리에 붙어 온 출처 표기. 없으면 빈 목록."""
    found = []
    for chunk in chunks:
        m = _CHUNK_SOURCE.match(chunk)
        if m:
            found.append(m.group(1).strip())
    return found


def check_quoted_spans(answer: str, chunks: list[str], threshold: float = 0.9) -> Check:
    """case24 — 답변이 문서에서 가져왔다고 제시한 것이 실제로 그런가.

    두 가지를 따로 본다. **대조 대상이 다르기 때문이다.**

    1. **문장 인용** (`"…"` `'…'`) → 청크 **본문**과 대조. 조사·띄어쓰기가 쉽게
       달라지므로 최장 연속 일치율 90% 를 기준으로 한다.
    2. **문서명** (`「」` `『』` `《》` `〈〉`) → 청크 **머리의 출처 표기**와 대조.
       문서명은 산문이 아니라 식별자라 부분 점수를 주면 안 된다 - 「휴가규정」이
       「휴가규정 시행세칙」에 1.0 으로 통과해 버린다. 대신 **포함 관계**로 본다:
       출처 표기에는 조항까지 붙어 오므로("정보보호정책 시행세칙 제7조") 이름만
       댄 인용도 맞다고 봐야 한다.

    한 통에 넣고 본문과 대조하던 때는 **정확히 인용한 답변까지 위반**이 됐다.
    청크 본문에 문서명이 적혀 있을 리가 없어서다. 그때 안 터진 것은 길이 덕이었다 -
    「연차휴가 운영지침」은 정규화하면 8자라 10자 하한에 걸려 조용히 빠졌다.

    청크에 출처 표기가 없으면 문서명은 **대조하지 않고 그렇게 적는다.** 운영 로그가
    출처를 실어 보내기 시작하면 그때부터 저절로 켜진다.
    """
    quotes = extract_quotes(answer)
    sources = extract_sources(answer)
    if not quotes and not sources:
        return Check("quoted_spans", "not_applicable", "답변에 인용된 문장이 없음")
    if not chunks:
        # 검색 결과가 0건인데 답변이 문서를 인용했다. 대조할 것이 없는 게 아니라
        # **가져올 곳이 없었는데 가져온 척한 것**이다. 전에는 undetermined 로 넘겨서
        # 이 신호가 조용히 사라졌다 - case21(Retrieve 미수행)과 겹치는 자리다.
        return Check("quoted_spans", "violated",
                     f"검색 결과가 0건인데 인용 {len(quotes) + len(sources)}건",
                     evidence=(quotes + sources)[:5])

    wrong = [f"문장: {q}" for q in quotes
             if max(match_ratio(q, c) for c in chunks) < threshold]

    known = [normalize(x) for x in chunk_sources(chunks)]
    unchecked = ""
    if sources and known:
        wrong += [f"문서명: {n}" for n in sources
                  if not any(normalize(n) in k for k in known)]
    elif sources:
        unchecked = f" · 문서명 {len(sources)}건은 대조 불가(청크에 출처 표기 없음)"

    checked = len(quotes) + (0 if unchecked else len(sources))
    if wrong:
        return Check("quoted_spans", "violated",
                     f"인용 {checked}건 중 {len(wrong)}건이 원문에 없음{unchecked}",
                     evidence=wrong[:5])
    return Check("quoted_spans", "ok", f"인용 {checked}건 모두 원문과 일치{unchecked}")


def process_data(ctx) -> tuple[list, list]:
    return run_check(ctx, NAME, lambda t: check_quoted_spans(
        t.case.llm_ans_on_last_q, t.case.rag_chunks))
