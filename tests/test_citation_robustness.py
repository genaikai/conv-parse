"""문서 인용 대조(verify_evidence)가 약한 모델의 전형적인 인용 변형을 어떻게 가르는지. LLM 없이 돈다.

Step 2 판정자는 청크에서 "글자 그대로" 인용해야 하는데 약한 모델은 그러지 못한다 —
항 번호 · <개정> 부기 · 한자 괄호 · 마크다운 표시를 지우고, 가운뎃점을 쉼표로 바꾸고,
한 글자를 틀리고, 표의 머리행과 한 행만 따오고, 두 문장을 줄임표로 잇는다. 그런 인용이
떨어지면 sufficient 가 insufficient 로 강등되어 case22 · 18 · 13 이 case20 으로 사라진다.

Step 2 골든셋(공개 법령 청크)의 문장을 그렇게 변형해 넣고 변형별 통과율을 잰다.
**통과해야 맞는 변형**은 최소 통과율을, **떨어져야 맞는 변형**(재서술 · 지어낸 문장 ·
다른 청크의 짧은 조각)은 최대 통과율을 단언한다. MATCH_THRESHOLD 나 조각 규칙을 바꾸면
여기가 먼저 알려준다.

    python tests/test_citation_robustness.py     # 표로 본다
"""

from __future__ import annotations

import random
import re
import sys
from collections import defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ragdiag.fixtures.judgments import SUFFICIENCY  # noqa: E402
from ragdiag.schema import Evidence  # noqa: E402
from ragdiag import settings  # noqa: E402
from ragdiag.verify import _doc_plain, _plain, verify_evidence  # noqa: E402

FLOOR = settings.EVIDENCE_MIN_QUOTE_CHARS

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪"
NOTE = re.compile(r"\s*<(?:개정|신설|전문개정)[^>]*>|\s*\[(?:전문개정|제목개정|본조신설)[^\]]*\]")
HANJA_PAREN = re.compile(r"\([一-鿿]+\)")
MARKDOWN = re.compile(r"\*\*|^#+\s*|^\s*[-*]\s+|^\s*\|\s*|\s*\|\s*$", re.M)

# 통과해야 맞는 변형 → 최소 통과율. 실측(2026-09 · 공개 법령 청크 32건)에 여유를 둔 값.
MUST_PASS = {
    "그대로": 1.0,
    "항 번호 · 부기 제거": 0.95,
    "한자 괄호 제거": 0.85,
    "마크다운 표시 제거": 0.95,
    "가운뎃점 → 쉼표": 0.95,
    "문장부호 제거": 0.95,
    "오탈자 1자 (치환)": 0.95,
    "오탈자 1자 (탈락)": 0.95,
    "앞 절반만": 0.95,
    "두 문장 … 연결": 0.95,
    "표 머리행 + 한 행": 0.95,
    "표 한 줄로 펴기": 0.95,
    "표 세로 자르기 (머리 셀 | 값 셀)": 0.95,
}
# 떨어져야 맞는 변형 → 최대 통과율
MUST_FAIL = {
    "의역": 0.30,
    "지어낸 문장": 0.05,
    "표 행의 숫자 바꿈": 0.10,
    "숫자 한 자리 바꿈": 0.10,
}
SHORT_FRAGMENT_MAX = 0.05   # 다른 청크의 12~16자 조각이 우연히 통과하는 비율 (하한 12자 · 청크 10~15개 실측 2.7%)

FABRICATED = [
    "국내 출장 숙박비는 1박 8만원을 상한으로 한다.",
    "경조사휴가는 본인 결혼 시 5일로 한다.",
    "육아휴직은 자녀 1명당 최대 1년까지 사용할 수 있다.",
    "국외 출장 숙박비 상한은 미주 지역 1일 200달러로 한다.",
    "연가는 반일 단위로 신청하며 팀장의 승인을 받아야 한다.",
]


def _sentences(chunk: str) -> list[str]:
    out = []
    for line in chunk.split("\n"):
        for s in re.split(r"(?<=[.。])\s+", line.strip()):
            s = s.strip()
            if 20 <= len(s) <= 160 and not s.startswith("|"):
                out.append(s)
    return out


def _table_rows(chunk: str) -> list[str]:
    return [ln for ln in chunk.split("\n") if ln.startswith("|") and "---" not in ln]


def variants(s: str, chunk: str) -> dict[str, str | None]:
    toks = s.split()
    sents = _sentences(chunk)
    i = sents.index(s) if s in sents else -1
    # 오탈자 · 문장부호 변형은 한자 병기를 뺀 문장에 건다. 괄호만 지우고 한자를 남기거나
    # 한자 한 글자를 틀리는 인용은 실제로 나오지 않는다.
    base = HANJA_PAREN.sub("", s)
    # 오탈자는 한글 글자에 낸다. 숫자를 바꾸거나 날짜 사이의 점을 글자로 바꾸는 건
    # 오탈자가 아니라 알맹이 변경이다.
    mid = len(base) // 2
    while mid < len(base) - 1 and not ("가" <= base[mid] <= "힣"):
        mid += 1
    out = {
        "그대로": s,
        "항 번호 · 부기 제거": NOTE.sub("", s.lstrip(CIRCLED + " ")).strip(),
        "한자 괄호 제거": base if base != s else None,
        "마크다운 표시 제거": MARKDOWN.sub("", s).strip(),
        "가운뎃점 → 쉼표": s.replace("·", ", ") if "·" in s else None,
        "문장부호 제거": re.sub(r"[「」『』.,、:;()]", "", base),
        "오탈자 1자 (치환)": base[:mid] + "ㅇ" + base[mid + 1:],
        "오탈자 1자 (탈락)": base[:mid] + base[mid + 1:],
        "앞 절반만": s[: len(s) // 2] if len(_plain(s[: len(s) // 2])) >= FLOOR else None,
        "두 문장 … 연결": (s + " … " + sents[i + 2]) if 0 <= i and i + 2 < len(sents) else None,
    }
    # 의역은 낱말을 둘 이상 바꾼 것만 센다. 꼬리 한 낱말("지급한다"→"준다")은 연속 일치
    # 비율 0.9 가 원래 흡수하는 범위라 재서술이 아니다.
    para, changed = s, 0
    for a, b in (("하여야 한다", "해야 함"), ("지급한다", "준다"), ("경우에는", "때는"),
                 ("공무원", "직원"), ("행정기관의 장", "기관장"), ("이내", "안"),
                 ("사용자는", "회사는"), ("근로자", "직원"), ("승인", "허가"), ("신청", "요청")):
        if a in para:
            para = para.replace(a, b)
            changed += 1
    out["의역"] = para if changed >= 2 else None
    # 숫자 한 자리 바꿈 - 오탈자와 편집 거리는 같지만 규정에서는 알맹이가 바뀐 것이다
    m = re.search(r"\d", base)
    out["숫자 한 자리 바꿈"] = (base[:m.start()] + str((int(m.group()) + 1) % 10) + base[m.end():]) if m else None
    if len(toks) < 3:
        out["앞 절반만"] = None
    return {k: (v or None) for k, v in out.items()}   # 부기만 있던 문장은 지우면 빈 문자열이 된다


def _cases() -> list[dict]:
    return [c for c in SUFFICIENCY if c["chunks"] and c.get("category", "short") != "short"]


def _passes(quote: str, idx: int, chunks: list[str]) -> bool:
    return verify_evidence([Evidence(chunk_index=idx, quote=quote)], chunks).n_kept == 1


def measure() -> dict[str, tuple[int, int]]:
    """변형 이름 -> (통과, 전체)."""
    random.seed(0)
    tally: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    cases = _cases()
    for c in cases:
        for idx, chunk in enumerate(c["chunks"]):
            sents = _sentences(chunk)
            if sents:
                s = random.choice(sents)
                for name, quote in variants(s, chunk).items():
                    if quote is None:
                        continue
                    t = tally[name]
                    t[1] += 1
                    t[0] += _passes(quote, idx, c["chunks"])
            rows = _table_rows(chunk)
            if len(rows) >= 3:
                t = tally["표 머리행 + 한 행"]
                t[1] += 1
                t[0] += _passes(rows[0] + "\n|---|---|\n" + rows[-1], idx, c["chunks"])
                t = tally["표 한 줄로 펴기"]
                t[1] += 1
                lead = _sentences(chunk)[0] if _sentences(chunk) else ""
                t[0] += _passes(lead + " " + rows[0] + " |---|---| " + rows[-1], idx, c["chunks"])
                t = tally["표 행의 숫자 바꿈"]
                t[1] += 1
                t[0] += _passes(rows[0] + "\n" + re.sub(r"\d+", "99", rows[-1]), idx, c["chunks"])
                # 세로 자르기: 머리행의 마지막 셀 | 마지막 행의 마지막 셀 (하한 미만이면 too_short 가 맞다)
                head, last = rows[0].strip("| ").split("|"), rows[-1].strip("| ").split("|")
                slice_ = head[-1].strip() + " | " + last[-1].strip()
                if len(_plain(slice_)) >= FLOOR:
                    t = tally["표 세로 자르기 (머리 셀 | 값 셀)"]
                    t[1] += 1
                    t[0] += _passes(slice_, idx, c["chunks"])
    for c in cases[:12]:
        for fab in FABRICATED:
            t = tally["지어낸 문장"]
            t[1] += 1
            t[0] += _passes(fab, 0, c["chunks"])
    # 다른 케이스 청크의 짧은 조각
    allc = [ch for c in cases for ch in c["chunks"]]
    for c in cases[:12]:
        others = [ch for ch in allc if ch not in c["chunks"]]
        for ch in random.sample(others, 4):
            p = _plain(ch)
            for k in (FLOOR, FLOOR + 4):
                for start in range(0, max(1, len(p) - k), 97):
                    frag = p[start:start + k]
                    if len(frag) < k:
                        continue
                    # 원문에 그대로 있는 조각(겹침 창 · 같은 조가 다른 케이스에도 있음)은 우연이
                    # 아니라 실재다. 원문에 없는데 퍼지 규칙으로 통과한 것만 센다.
                    if any(frag in _doc_plain(t) for t in c["chunks"]):
                        continue
                    t = tally["짧은 조각 (다른 청크 · 원문에 없음)"]
                    t[1] += 1
                    t[0] += _passes(frag, 0, c["chunks"])
    return {name: (p, t) for name, (p, t) in tally.items()}


@pytest.fixture(scope="module")
def rates():
    return measure()


@pytest.mark.parametrize("name, floor", sorted(MUST_PASS.items()))
def test_quotes_taken_from_the_chunk_pass(rates, name, floor):
    p, t = rates[name]
    assert t, f"{name}: 잴 원문이 없다"
    assert p / t >= floor, f"{name}: 통과 {p / t:.0%} < 최소 {floor:.0%}"


@pytest.mark.parametrize("name, ceiling", sorted(MUST_FAIL.items()))
def test_quotes_that_change_the_words_fail(rates, name, ceiling):
    p, t = rates[name]
    assert t, f"{name}: 잴 원문이 없다"
    assert p / t <= ceiling, f"{name}: 통과 {p / t:.0%} > 최대 {ceiling:.0%}"


def test_short_fragments_from_other_chunks_rarely_pass(rates):
    p, t = rates["짧은 조각 (다른 청크 · 원문에 없음)"]
    assert p / t <= SHORT_FRAGMENT_MAX, f"우연 일치 {p / t:.0%}"


if __name__ == "__main__":
    for name, (p, t) in measure().items():
        print(f"{name:<24}{p:>4}/{t:<4}{p / t:>5.0%}")
