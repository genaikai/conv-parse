"""인용 검증 - knowledge leakage 차단 장치.

판정자 LLM이 "문서에 답이 있다"고 말할 때, 그게 문서를 읽어서인지 자기가 이미
알던 지식 때문인지 프롬프트로는 구분할 수 없다. 그래서 판정자에게 청크에서
글자 그대로 인용을 뽑게 하고, 그 인용이 실제로 청크 안에 있는지 여기서 대조한다.
지어낸 인용은 원문과 일치하지 않으므로 걸러진다.

"지어내지 마세요"라는 프롬프트와 달리 이건 검증 가능한 장치다.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Optional
from dataclasses import dataclass, field

from ragdiag.schema import Evidence, SufficiencyJudgment

from ragdiag import settings
from ragdiag.settings import EVIDENCE_MIN_QUOTE_CHARS, MATCH_THRESHOLD

# 옛 이름. features/quoted_spans 에도 같은 이름의 다른 값(답변이 제시한 인용의 최소 길이)이
# 있어서 한쪽만 고치고 양쪽을 고쳤다고 착각하기 쉬웠다. settings 에서 이름을
# 갈랐고, 여기 별칭은 기존 호출부를 위해 남긴다.
MIN_QUOTE_CHARS = EVIDENCE_MIN_QUOTE_CHARS

_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """공백과 유니코드 표기 차이를 제거. 청크 분할 과정에서 공백은 쉽게 달라진다."""
    return _WS.sub("", unicodedata.normalize("NFKC", text)).lower()


def match_ratio(quote: str, chunk: str) -> float:
    """quote가 chunk 안에 얼마나 연속으로 들어있는지. 1.0이면 완전 포함."""
    q, c = normalize(quote), normalize(chunk)
    if not q:
        return 0.0
    if q in c:
        return 1.0
    block = difflib.SequenceMatcher(None, q, c, autojunk=False).find_longest_match(
        0, len(q), 0, len(c)
    )
    return block.size / len(q)


@dataclass
class VerifiedEvidence:
    chunk_index: int
    quote: str
    ratio: float
    index_corrected: bool = False


@dataclass
class CitationCheck:
    kept: list[VerifiedEvidence] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)
    # 무엇을 상대로 대조했는지. 0 이면 검색 결과가 아예 없었다는 뜻이고,
    # 이건 판정이 아니라 로그에 적힌 사실이라 라우팅이 다르게 읽어야 한다.
    # None 은 '모름'이다 - 옛 호출부가 넘기지 않은 경우.
    n_chunks: Optional[int] = None

    @property
    def n_kept(self) -> int:
        return len(self.kept)

    @property
    def any_corrected(self) -> bool:
        return any(e.index_corrected for e in self.kept)


@dataclass
class QuoteCheck:
    """판정자가 "이건 불만이 아니다"라고 할 때 든 근거의 검증 결과."""

    quote: str
    ratio: float
    verified: bool


def _plain(text: str) -> str:
    """normalize 에 더해 문장부호까지 지운다. 짧은 발화는 부호 하나가 대조를 가른다."""
    return "".join(ch for ch in normalize(text)
                   if not unicodedata.category(ch).startswith("P"))


def _coverage(quote: str, text: str) -> float:
    """인용 글자 중 원문에 **순서대로** 들어 있는 비율.

    원문 쪽에 조사가 더 끼어 있어도("숙박비 얼마" ↔ "숙박비는 얼마") 1.0 이다. 한 글자짜리
    일치는 세지 않는다 - 흩어진 글자가 우연히 맞아 말을 바꾼 인용이 통과하는 것을 막는다.
    """
    q, t = _plain(quote), _plain(text)
    if not q:
        return 0.0
    if q in t:
        return 1.0
    blocks = difflib.SequenceMatcher(None, q, t, autojunk=False).get_matching_blocks()
    return sum(b.size for b in blocks if b.size >= 2) / len(q)


_SENTENCE_END = re.compile(r"(?<=[.!?。])\s+|\n+")


def verify_complaint_quote(quote: str, current_query: str) -> QuoteCheck:
    """그 구절이 후속 발화에 실제로 있는지 대조한다.

    "문제 없음"은 판정자가 낼 수 있는 가장 쉬운 답이다. 어디를 보고 그렇게 읽었는지
    원문에서 따오게 하면 근거 없이 넘어갈 수 없다 - verify_evidence 가 sufficient
    주장에 대해 하는 일과 같다.

    문서 인용과 다르게 대조 대상이 짧은 발화라 규칙이 셋이다.
    - 발화 전체나 그 한 문장을 그대로 따왔으면 짧아도 받는다 ("네 감사합니다")
    - 그 밖의 조각은 4자 이상이어야 한다. 짧은 조각("그럼")은 아무 발화에나 맞는다
    - 조사 · 문장부호가 빠진 것은 받고, 말을 바꾼 것은 받지 않는다
    약한 모델이 짧은 발화를 일부만 따오는 일이 잦아서 예전의 8자 · 연속 90% 규칙이
    맞는 판정을 떨어뜨렸다 (Haiku 로 재 보니 none 6건 중 3건).
    """
    plain = _plain(quote)
    whole = {_plain(s) for s in [current_query, *_SENTENCE_END.split(current_query.strip())]}
    if plain and plain in whole:
        return QuoteCheck(quote, 1.0, True)
    return verify_quote_in(quote, [current_query], settings.UTTERANCE_MIN_QUOTE_CHARS)


def _edits_to_substring(quote: str, text: str) -> int:
    """quote 와 text 의 어떤 부분 문자열 사이의 최소 편집 거리 (Sellers). 둘 다 정규화된 것."""
    n, m = len(quote), len(text)
    prev = [0] * (m + 1)                      # 첫 행이 0 - text 어디서든 시작할 수 있다
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (quote[i - 1] != text[j - 1]))
        prev = cur
    return min(prev)


def verify_quote_in(quote: str, texts: list[str], min_chars: int) -> QuoteCheck:
    """판정자가 발화에서 댄 구절이 주어진 문장들 중 하나에 실제로 있는지.

    문서 인용(verify_evidence)과 규칙이 다르다 - 발화는 짧아 오탈자 한 글자가 비율을
    크게 깎고, 떨어졌을 때의 처리가 안전한 방향이라 조금 느슨하다 (settings 참고).

    두 갈래로 통과한다. 연속 일치 비율이 QUOTE_MATCH_THRESHOLD 이상이거나, 인용이
    QUOTE_EDIT_TOLERANT_MIN_CHARS 이상이고 원문의 어느 부분과 한 글자 차이 이내이거나.
    뒤 갈래는 비율 규칙의 사각지대를 메운다 - 끝에서 두 번째 글자가 다르면 꼬리 한 글자가
    일치로 안 세어져 8~10자 인용이 떨어졌다. 재서술 · 영어 혼용 · 위치 오류의 통과율은
    이 갈래로 바뀌지 않는다 (tests/test_quote_robustness.py).
    """
    plain = _plain(quote)
    if len(plain) < min_chars:
        return QuoteCheck(quote, 0.0, False)
    ratio = max((_coverage(quote, t) for t in texts), default=0.0)
    if ratio >= settings.QUOTE_MATCH_THRESHOLD:
        return QuoteCheck(quote, ratio, True)
    if len(plain) >= settings.QUOTE_EDIT_TOLERANT_MIN_CHARS and any(
            _edits_to_substring(plain, _plain(t)) <= 1 for t in texts):
        return QuoteCheck(quote, ratio, True)
    return QuoteCheck(quote, ratio, False)


def verify_request_quote(quote: str, questions: list[str]) -> QuoteCheck:
    """판정자가 적은 요구의 구절이 이전 질문들 안에 실제로 있는지.

    요구는 비판받은 답변이 따를 수 있었던 것 - 그 답변을 부른 질문과 그 앞에 적힌 것만
    요구다. 후속 발화에서 처음 꺼낸 요구를 세면 답할 때는 없던 요구를 어긴 것이 된다.
    요구 구절은 짧으므로("표로", "영어로") 하한을 두 글자로 둔다.
    """
    return verify_quote_in(quote, questions, settings.REQUEST_MIN_QUOTE_CHARS)


def verify_history_quote(quote: str, earlier_questions: list[str]) -> QuoteCheck:
    """"이전 턴의 조건을 어겼다"는 주장의 근거가 앞 질문들에 실제로 있는지.

    ignored 는 case14 로 가는데, 약한 모델은 답변이 부실하기만 해도 ignored 로 읽는다
    (골든셋 halo02 에서 Haiku 가 실행마다 흔들렸다). 어긴 조건이 적힌 앞 질문을 대게 하고
    여기서 대조한다 - 마지막 질문은 뺀다. 거기 적힌 조건을 어긴 것은 히스토리 문제가 아니라
    의도를 잘못 읽은 것이다.

    하한이 4자인 이유: 2자 조각("국내")은 앞 질문들에 우연히 있을 확률이 14% 라
    근거를 대충 짧게 적어도 ignored 가 살아남는다. 4자면 5% 아래로 내려간다.
    """
    return verify_quote_in(quote, earlier_questions, settings.UTTERANCE_MIN_QUOTE_CHARS)


def verify_evidence(evidence: list[Evidence], chunks: list[str]) -> CitationCheck:
    check = CitationCheck(n_chunks=len(chunks))
    for ev in evidence:
        if len(normalize(ev.quote)) < settings.EVIDENCE_MIN_QUOTE_CHARS:
            check.dropped.append({"quote": ev.quote, "reason": "too_short"})
            continue

        if 0 <= ev.chunk_index < len(chunks):
            ratio = match_ratio(ev.quote, chunks[ev.chunk_index])
            if ratio >= settings.MATCH_THRESHOLD:
                check.kept.append(VerifiedEvidence(ev.chunk_index, ev.quote, ratio))
                continue

        # 인덱스는 틀렸어도 인용 자체가 실제 문서에 있으면 지어낸 게 아니다.
        # leakage를 막는 건 인용의 실재성이지 인덱스의 정확성이 아니므로 살린다.
        best_idx, best_ratio = -1, 0.0
        for i, chunk in enumerate(chunks):
            r = match_ratio(ev.quote, chunk)
            if r > best_ratio:
                best_idx, best_ratio = i, r
        if best_ratio >= settings.MATCH_THRESHOLD:
            check.kept.append(
                VerifiedEvidence(best_idx, ev.quote, best_ratio, index_corrected=True)
            )
        else:
            check.dropped.append(
                {"quote": ev.quote, "reason": "not_found", "best_ratio": round(best_ratio, 3)}
            )
    return check


def final_verdict(judgment: SufficiencyJudgment, citation: Optional[CitationCheck]) -> str:
    """인용 대조를 거친 verdict. 문서에 답이 있다고 주장하려면 살아남은 인용이 있어야 한다.

    인용이 하나도 검증되지 않은 sufficient · partial 은 판정자의 사전지식에서 나온
    주장으로 보고 insufficient 로 내린다. 근거 활용을 물을지 정하는 쪽(grounding)과
    case 를 정하는 쪽(route)이 같은 규칙을 봐야 해서 여기 한 곳에 둔다 - 두 곳에 적으면
    한쪽만 고치게 된다.
    """
    kept = citation.n_kept if citation else 0
    if judgment.verdict in ("sufficient", "partial") and kept == 0:
        return "insufficient"
    return judgment.verdict
