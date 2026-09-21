"""case30 — 생성 붕괴. 답변이 같은 글자 · 기호의 반복뿐이다.

    5555555555555        !!!!!!!!!!!!!!!!!        안녕하세요안녕하세요안녕하세요안녕하세요

모델이 답을 만들다 무너진 것이라 LLM 이 만든 답이 아니고, 이런 문자열을 관측에
넣으면 판정자가 거절이나 무응답으로 읽어 엉뚱한 case 로 보낸다 - 호출 세 번이 그냥
날아간다. 그래서 코드로 먼저 걸러 LLM 호출 0회로 끝낸다.

잘림(case8)과 달리 여기는 규칙이 맞는 자리다. 잘림은 "끊겼다" 와 "그렇게 끝맺었다"
가 글자로는 같아 텍스트에 신호가 없었지만, 붕괴는 신호가 텍스트 그 자체다 -
정상 답변이 이런 모양일 가능성이 없다.

**되풀이는 붙어 있을 때만 붕괴다.** "다음도 시도해보세요: A. 다음도 시도해보세요: B. …"
처럼 같은 문구가 다른 내용을 사이에 두고 되풀이되는 것은 글의 구조이지 붕괴가 아니다.
_repeated_unit 은 조각이 **글자 그대로 연달아** 이어질 때만 잡는다.

**규칙은 보수적으로 둔다.** 오탐이 나면 그 턴의 진짜 원인이 LLM 판정도 못 받고
통째로 사라진다. 그래서 전부 답변 **전체**를 보고, 마크다운 구분선(--- · ===)처럼
정상 답변에 나오는 반복은 제외한다. 빈 답변은 여기서 잡지 않는다 - 다른 사건이다.
"""

import re

from ragdiag.results import Check

NAME = "degenerate"             # 결과가 checks["degenerate"] 로 남는다
CASE = "case30"
REASON = "답변이 같은 글자 · 기호의 반복뿐 (생성 붕괴)"
NOTES = (
    "모델이 답을 만들다 무너졌다. 검색·생성 품질이 아니라 모델·서빙 쪽 문제다.",
    "LLM 판정을 돌리지 않았다 — 관측·충족도·근거 활용이 모두 비어 있다.",
)

# 한글 · 한자 · 영문 · 숫자. 하나도 없으면 말이 아니다.
_WORD = re.compile(r"[0-9A-Za-zㄱ-ㆎ가-힣一-鿿぀-ヿ]")
# 마크다운 · 표 구분선에 쓰는 글자. 이게 길게 이어지는 건 정상이다.
_RULERS = set("-=─━*_~|·.")

MIN_CHARS = 10          # 이보다 짧으면 판단하지 않는다 ("네네" 는 붕괴가 아니다)
MIN_REPEATS = 4         # 조각이 이만큼 되풀이되면 붕괴로 본다
TAIL_RUN = 50           # 정상 문장 뒤에 같은 글자가 이만큼 이어지면 붕괴가 붙은 것


def _repeated_unit(text: str) -> str:
    """text 가 짧은 조각의 되풀이면 그 조각을, 아니면 빈 문자열을 돌려준다.

    조각 길이 1~30, 되풀이 MIN_REPEATS 이상, 전체의 90% 이상을 덮어야 한다.
    """
    n = len(text)
    for size in range(1, min(30, n // MIN_REPEATS) + 1):
        unit = text[:size]
        count = n // size
        if count >= MIN_REPEATS and text.startswith(unit * count) \
                and count * size >= n * 0.9:
            return unit
    return ""


def check_degenerate(answer: str) -> Check:
    """답변이 생성 붕괴인가."""
    packed = re.sub(r"\s+", "", answer)
    if not packed:
        return Check("degenerate", "not_applicable", "답변이 비어 있음")
    if len(packed) < MIN_CHARS:
        return Check("degenerate", "ok", "짧아서 판단하지 않음")

    if len(set(packed)) <= 2:
        return Check("degenerate", "violated",
                     f"글자 {len(set(packed))}종의 반복: {packed[:20]!r}")

    unit = _repeated_unit(packed)
    if unit and set(unit) - _RULERS:
        return Check("degenerate", "violated",
                     f"{unit[:20]!r} 이(가) {len(packed) // len(unit)}번 되풀이됨")

    if not _WORD.search(packed):
        return Check("degenerate", "violated", f"글자가 하나도 없음: {packed[:20]!r}")

    tail = re.search(r"(.)\1{%d,}$" % (TAIL_RUN - 1), packed)
    if tail and tail.group(1) not in _RULERS:
        return Check("degenerate", "violated",
                     f"끝에 {tail.group(1)!r} 이(가) {len(tail.group(0))}번 이어짐")

    return Check("degenerate", "ok", "반복 없음")


def check(turn) -> Check:
    return check_degenerate(turn.case.llm_ans_on_last_q)
