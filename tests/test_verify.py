"""인용 검증 테스트. leakage 차단 장치가 실제로 막는지가 핵심."""

import pytest

from ragdiag.schema import Evidence
from ragdiag.verify import MATCH_THRESHOLD, match_ratio, normalize, verify_evidence

CHUNKS = [
    "해외 출장 시 미주 지역의 1일 숙박비 상한은 250달러이다.",
    "국내 출장 식비는 1일 3만원을 상한으로 한다.",
]


def ev(idx, quote):
    return Evidence(chunk_index=idx, quote=quote)


def test_exact_quote_is_kept():
    r = verify_evidence([ev(0, "1일 숙박비 상한은 250달러")], CHUNKS)
    assert r.n_kept == 1
    assert r.kept[0].ratio == 1.0
    assert not r.kept[0].index_corrected


def test_whitespace_differences_are_tolerated():
    # 청크 분할 과정에서 공백은 쉽게 달라진다. 그걸로 근거를 버리면 안 된다.
    r = verify_evidence([ev(0, "1일  숙박비\n상한은 250달러")], CHUNKS)
    assert r.n_kept == 1


def test_fabricated_quote_is_dropped():
    # 문서에 없는 내용을 지어낸 경우. 이게 막히지 않으면 검색 실패가
    # '근거 미활용'으로 오분류되어 통계에서 사라진다.
    r = verify_evidence([ev(0, "유럽 지역의 1일 숙박비 상한은 300달러이다")], CHUNKS)
    assert r.n_kept == 0
    assert r.dropped[0]["reason"] == "not_found"


def test_short_quote_is_dropped():
    # 짧은 인용은 아무 문서에나 우연히 맞아 검증을 무력화한다.
    r = verify_evidence([ev(0, "출장")], CHUNKS)
    assert r.n_kept == 0
    assert r.dropped[0]["reason"] == "too_short"


def test_wrong_index_but_real_quote_is_kept_and_flagged():
    # leakage를 막는 건 인용의 실재성이지 인덱스의 정확성이 아니다.
    r = verify_evidence([ev(1, "미주 지역의 1일 숙박비 상한은 250달러")], CHUNKS)
    assert r.n_kept == 1
    assert r.kept[0].chunk_index == 0
    assert r.kept[0].index_corrected
    assert r.any_corrected


def test_out_of_range_index_falls_back_to_scan():
    r = verify_evidence([ev(99, "국내 출장 식비는 1일 3만원")], CHUNKS)
    assert r.n_kept == 1
    assert r.kept[0].chunk_index == 1


def test_no_chunks_means_nothing_can_be_verified():
    r = verify_evidence([ev(0, "무엇이든 상관없는 충분히 긴 인용문")], [])
    assert r.n_kept == 0


def test_normalize_removes_whitespace_and_normalizes_unicode():
    assert normalize("가 나\t다\n") == "가나다"
    assert normalize("２５０달러") == "250달러"


@pytest.mark.parametrize("quote,expected_min", [
    ("미주 지역의 1일 숙박비 상한은 250달러이다", 1.0),
    ("전혀 관계없는 문장입니다 여기에는", 0.0),
])
def test_match_ratio_bounds(quote, expected_min):
    ratio = match_ratio(quote, CHUNKS[0])
    assert ratio >= expected_min if expected_min == 1.0 else ratio < MATCH_THRESHOLD


# ---------------------------------------------------------------------------
# 인용 대조를 거친 verdict — 근거 활용을 물을지와 case 를 정하는 쪽이 같이 본다
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("verdict, kept, want", [
    ("sufficient", 0, "insufficient"),   # 인용 없는 "있다" 는 사전지식이다
    ("partial", 0, "insufficient"),
    ("sufficient", 1, "sufficient"),
    ("partial", 1, "partial"),
    ("insufficient", 0, "insufficient"),
])
def test_final_verdict_downgrades_claims_without_a_surviving_quote(verdict, kept, want):
    from ragdiag.schema import SufficiencyJudgment
    from ragdiag.verify import CitationCheck, VerifiedEvidence, final_verdict

    judgment = SufficiencyJudgment(reasoning="r", evidence=[], verdict=verdict, missing="")
    citation = CitationCheck(kept=[VerifiedEvidence(0, "q" * 12, 1.0)] * kept, n_chunks=2)
    assert final_verdict(judgment, citation) == want


def test_final_verdict_without_a_citation_check_counts_no_quotes():
    from ragdiag.schema import SufficiencyJudgment
    from ragdiag.verify import final_verdict

    judgment = SufficiencyJudgment(reasoning="r", evidence=[], verdict="sufficient", missing="")
    assert final_verdict(judgment, None) == "insufficient"



# ---------------------------------------------------------------------------
# 판정자의 인용 — 불만 아님의 근거(후속 발화) · 요구(이전 질문들)
#
# 문서 인용과 달리 대조 대상이 짧은 발화다. 발화 전체를 인용했으면 짧아도 받고,
# 조사 · 문장부호가 빠진 것은 받되, 말을 바꾼 것은 받지 않는다.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("quote, utterance", [
    ("네 감사합니다", "네 감사합니다"),               # 발화 전체 — 짧아도 받는다
    ("네 감사합니다", "네 감사합니다. 승인은 누가 하나요?"),  # 발화의 한 문장 그대로
    ("숙박비는요", "숙박비는요?"),                     # 문장부호 차이
    ("숙박비 얼마인가요", "그럼 숙박비는 얼마인가요?"),  # 조사가 빠짐
    ("그럼 숙박비는 얼마인가요", "그럼 숙박비는 얼마인가요?"),
])
def test_complaint_quote_accepts_the_utterance_itself(quote, utterance):
    from ragdiag.verify import verify_complaint_quote
    assert verify_complaint_quote(quote, utterance).verified


@pytest.mark.parametrize("quote, utterance", [
    ("숙박비가 궁금하다", "그럼 숙박비는 얼마인가요?"),  # 말을 바꿈
    ("그럼", "그럼 숙박비는 얼마인가요?"),               # 짧은 조각 — 무엇이든 맞는다
    ("", "그럼 숙박비는 얼마인가요?"),
])
def test_complaint_quote_rejects_what_is_not_in_the_utterance(quote, utterance):
    from ragdiag.verify import verify_complaint_quote
    assert not verify_complaint_quote(quote, utterance).verified


def test_request_quote_must_come_from_the_questions():
    """요구는 비판받은 답변이 따를 수 있었던 것 — 이전 질문들에 적힌 것만이다."""
    from ragdiag.verify import verify_request_quote

    questions = ["출장비 규정 알려주세요.", "항목별 상한을 표로 정리해 주세요."]
    assert verify_request_quote("표로", questions).verified
    assert verify_request_quote("표로 정리해 주세요", questions).verified
    assert not verify_request_quote("영어로 답해줘", questions).verified   # 후속 발화에만 있던 요구
    assert not verify_request_quote("", questions).verified
