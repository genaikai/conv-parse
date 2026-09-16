"""발화 인용 대조(verify_complaint_quote · verify_history_quote · verify_request_quote)가
약한 모델의 전형적인 인용 변형을 어떻게 가르는지. LLM 없이 돈다.

Step 1 은 Haiku 보다 약한 로컬 모델로 돈다. 그런 모델은 인용을 원문 그대로 못 따온다 —
재서술 · 요약 · 어미 변형 · 오탈자 · 영어 혼용 · 부분 인용 · 엉뚱한 곳(답변 · 마지막 질문 ·
후속 발화)에서 따오기. 골든셋 원문을 그렇게 변형해 넣고 종류별 통과율을 잰다.

**통과해야 맞는 변형**(원문에서 따온 것)은 최소 통과율을, **떨어져야 맞는 변형**(위치 오류 ·
짧은 조각 · 말을 바꾼 것)은 최대 통과율을 단언한다. 임계값(QUOTE_MATCH_THRESHOLD)이나
하한을 바꾸면 여기가 먼저 알려준다.

    python tests/test_quote_robustness.py     # 표로 본다
"""

from __future__ import annotations

import random
import re
import sys
from collections import defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ragdiag.fixtures.observations import CASES  # noqa: E402
from ragdiag.verify import (  # noqa: E402
    _coverage,
    verify_complaint_quote,
    verify_history_quote,
    verify_request_quote,
)

KINDS = ("complaint", "history", "request")

# 어미 · 동의어 · 영어 치환표. 약한 모델이 인용을 "고쳐 쓰는" 흔한 방식이다.
ENDINGS = [(r"주세요[.?]?$", "주라"), (r"인가요\?$", "인지?"), (r"예요\?$", "인가요?"),
           (r"습니다[.]?$", "어요"), (r"잖아요[.]?$", "잖니"), (r"나요\?$", "나?"),
           (r"세요[.]?$", "라"), (r"요[.?]?$", "")]
SYNONYMS = {"알려주세요": "말씀해 주세요", "알려 주세요": "말씀해 주세요", "얼마인가요": "얼마예요",
            "얼마": "어느 정도", "상한": "최대 한도", "정리해": "만들어", "주세요": "주십시오",
            "가능한가요": "되나요", "어떻게": "어떤 식으로", "언제": "며칠쯤", "기준": "잣대",
            "규정": "규칙", "절차": "순서", "신청": "접수"}
ENGLISH = {"표": "table", "영어": "English", "상한": "limit", "식비": "meal cost",
           "숙박비": "lodging", "링크": "link", "규정": "policy", "절차": "process",
           "신청": "apply", "번호": "number", "국내": "domestic", "기준": "basis"}
PARTICLES = re.compile(r"(은|는|이|가|을|를|도|의|에|에서|으로|로|만)(?=\s|$|[.?!,])")


def _sentences(s: str) -> list[str]:
    return [x for x in re.split(r"(?<=[.!?])\s+", s.strip()) if x]


def _with_ending_changed(s: str) -> str:
    for pat, rep in ENDINGS:
        if re.search(pat, s):
            return re.sub(pat, rep, s)
    return s


def variants(s: str, wrong: str) -> dict[str, str | None]:
    """원문 s 의 인용 변형. wrong 은 엉뚱한 곳(답변 · 마지막 질문 · 후속 발화)의 원문.

    None 은 그 원문에 적용할 수 없는 변형이다 (치환할 낱말이 없음).
    """
    toks = s.split()
    mid = len(s) // 2
    out: dict[str, str | None] = {
        "그대로": s,
        "한 문장": _sentences(s)[0],
        "부분 · 앞 절반": s[: max(2, mid)],
        "부분 · 앞 두 어절": " ".join(toks[:2]),
        "부분 · 뒤 두 어절": " ".join(toks[-2:]),
        "조사 제거": PARTICLES.sub("", s),
        "부호 · 공백 변형": s.replace(" ", "  ").rstrip("?.!") + " !",
        "오탈자 1글자 (치환)": s[:mid] + "ㅇ" + s[mid + 1:],
        "오탈자 1글자 (삭제)": s[:mid] + s[mid + 1:],
        "오탈자 2글자": (s[: len(s) // 3] + "ㅇ" + s[len(s) // 3 + 1: 2 * len(s) // 3]
                     + "ㅇ" + s[2 * len(s) // 3 + 1:]),
        "엉뚱한 곳에서 (위치 오류)": wrong,
        "짧은 조각 2자": s.replace(" ", "")[:2],
        "짧은 조각 3자": s.replace(" ", "")[:3],
    }
    ending = _with_ending_changed(s)
    out["어미 변형"] = ending if ending != s else None
    para = s
    for a, b in SYNONYMS.items():
        if a in para:
            para = para.replace(a, b, 1)
    out["재서술 (동의어)"] = para if para != s else None
    out["요약 (동의어 + 어미)"] = None
    if para != s:
        summary = _with_ending_changed(para)
        out["요약 (동의어 + 어미)"] = (" ".join(summary.split()[:-1])
                                  if len(summary.split()) > 2 else summary)
    en = s
    for a, b in ENGLISH.items():
        if a in en:
            en = en.replace(a, b, 1)
            break
    out["영어 혼용"] = en if en != s else None
    return out


# 통과해야 맞는 변형 → 최소 통과율.  떨어져야 맞는 변형 → 최대 통과율.
# 골든셋 실측(2026-09)에서 여유를 조금 두고 잡았다. 임계값 0.85 · 발화 하한 4자 · 요구 하한 2자.
MUST_PASS = {
    "그대로": 1.0, "한 문장": 1.0, "부호 · 공백 변형": 1.0,
    "조사 제거": 0.90, "오탈자 1글자 (치환)": 0.90, "오탈자 1글자 (삭제)": 0.90,
    "어미 변형": 0.80,
    "부분 · 앞 절반": 0.85, "부분 · 앞 두 어절": 0.85, "부분 · 뒤 두 어절": 0.90,
}
MUST_FAIL = {
    "엉뚱한 곳에서 (위치 오류)": 0.0,
    "재서술 (동의어)": 0.10, "영어 혼용": 0.05,
}
# 짧은 조각은 종류마다 다르다 - 요구 구절은 정당하게 짧아서(“표로”) 2자를 받는다.
SHORT_FRAGMENT_MAX = {"complaint": 0.0, "history": 0.0}


def targets() -> list[tuple[str, str, list[str], str]]:
    """(종류, 원문, 원문이 들어 있는 문장들, 엉뚱한 곳의 원문)."""
    rows = []
    for c in CASES:
        q, ans, comp = c["pre_queries"], c["answer"], c["complaint"]
        rows.append(("complaint", comp, [comp], ans))
        rows.append(("request", q[-1], q, comp))
        if len(q) >= 2:
            rows.append(("history", q[0], q[:-1], q[-1]))
    return rows


def verified(kind: str, quote: str, sources: list[str]) -> bool:
    if kind == "complaint":
        return verify_complaint_quote(quote, sources[0]).verified
    if kind == "history":
        return verify_history_quote(quote, sources).verified
    return verify_request_quote(quote, sources).verified


def pass_rates() -> dict[tuple[str, str], tuple[int, int]]:
    """(변형, 종류) → (통과, 전체)."""
    tally: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for kind, src, sources, wrong in targets():
        for name, quote in variants(src, wrong).items():
            if quote is None:
                continue
            t = tally[(name, kind)]
            t[1] += 1
            t[0] += verified(kind, quote, sources)
    return {k: (v[0], v[1]) for k, v in tally.items()}


def _rate(rates, name, kinds=KINDS) -> float:
    hits = sum(rates.get((name, k), (0, 0))[0] for k in kinds)
    total = sum(rates.get((name, k), (0, 0))[1] for k in kinds)
    assert total, f"{name}: 잴 원문이 없다"
    return hits / total


@pytest.fixture(scope="module")
def rates():
    return pass_rates()


@pytest.mark.parametrize("name, floor", sorted(MUST_PASS.items()))
def test_quotes_taken_from_the_utterance_pass(rates, name, floor):
    """원문에서 따온 인용은 조금 흐트러져도 통과해야 한다 — 약한 모델이 그렇게 따온다."""
    got = _rate(rates, name)
    assert got >= floor, f"{name}: 통과 {got:.0%} < 최소 {floor:.0%}"


@pytest.mark.parametrize("name, ceiling", sorted(MUST_FAIL.items()))
def test_quotes_that_change_the_words_fail(rates, name, ceiling):
    """말을 바꾸거나 엉뚱한 곳에서 따온 인용은 떨어져야 한다 — 그게 이 대조의 존재 이유다."""
    got = _rate(rates, name)
    assert got <= ceiling, f"{name}: 통과 {got:.0%} > 최대 {ceiling:.0%}"


@pytest.mark.parametrize("kind", sorted(SHORT_FRAGMENT_MAX))
def test_short_fragments_do_not_pass_where_they_fit_anything(rates, kind):
    """2~3자 조각은 앞 질문들에 우연히 있을 확률이 14% 다 — ignored 오탐이 그대로 살아남는다."""
    for name in ("짧은 조각 2자", "짧은 조각 3자"):
        got = _rate(rates, name, (kind,))
        assert got <= SHORT_FRAGMENT_MAX[kind], f"{kind} · {name}: 통과 {got:.0%}"


def test_request_quotes_may_be_short():
    """요구 구절은 정당하게 짧다. "표로" 가 떨어지면 요구가 전부 지워진다."""
    assert verify_request_quote("표로", ["항목별 상한을 표로 정리해 주세요."]).verified


def chance_rates(seed: int = 0) -> dict[int, float]:
    """다른 케이스 원문의 k자 조각이 이 케이스의 앞 질문들에 우연히 있을 확률."""
    rng = random.Random(seed)
    all_q = [q for c in CASES for q in c["pre_queries"]]
    out = {}
    for k in (2, 3, 4, 5, 6):
        hit = tot = 0
        for c in CASES:
            own = c["pre_queries"][:-1] if len(c["pre_queries"]) >= 2 else c["pre_queries"]
            others = [q for q in all_q if q not in c["pre_queries"]]
            for q in rng.sample(others, min(20, len(others))):
                plain = q.replace(" ", "")
                for i in range(0, max(1, len(plain) - k), 3):
                    frag = plain[i:i + k]
                    if len(frag) == k:
                        tot += 1
                        hit += any(_coverage(frag, s) >= 0.9 for s in own)
        out[k] = hit / tot
    return out


def test_the_floor_sits_where_chance_matches_drop_below_five_percent():
    """발화 하한 4자의 근거. 골든셋이 같은 주제를 반복해 실데이터보다 후한 추정이다."""
    from ragdiag import settings

    chance = chance_rates()
    assert chance[2] > 0.10, "2자 조각의 우연 일치가 낮아졌다면 하한을 다시 볼 것"
    assert chance[settings.UTTERANCE_MIN_QUOTE_CHARS] < 0.06


def render() -> str:
    rates = pass_rates()
    names = list(variants("a b c d e?", "x").keys())
    lines = [f"{'변형':<22}" + "".join(f"{k:>12}" for k in KINDS) + "      합산"]
    for name in names:
        cells = []
        for k in KINDS:
            p, t = rates.get((name, k), (0, 0))
            cells.append(f"{p:>3}/{t:<3}{p / t:>4.0%}" if t else "      —    ")
        lines.append(f"{name:<22}" + "".join(f"{c:>12}" for c in cells)
                     + f"{_rate(rates, name):>9.0%}")
    lines.append("\n우연 일치율: " + " · ".join(f"{k}자 {v:.1%}" for k, v in chance_rates().items()))
    return "\n".join(lines)


if __name__ == "__main__":
    print(render())
