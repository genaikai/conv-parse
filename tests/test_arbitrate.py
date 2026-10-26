"""⑦ 중재 — 후보 생성 규칙과 등급 선택. LLM 없음.

라벨을 코드가 정하므로 여기서 전 경로를 덮을 수 있다. 규칙은 features/arbitrate/candidates.py,
선택은 features/arbitrate/__init__.py 다. 등급의 뜻은 docs/design/taxonomy_v3.md.
"""

import pytest

from ragdiag import settings, taxonomy
from ragdiag.features.arbitrate import arbitrate, candidates_for, close, pick
from ragdiag.results import Candidate, Check, ChunkSupport, ClaimVerdict, Sufficiency
from ragdiag.verify import QuoteCheck
from tests.helpers import case, checks, obs, probs, turn

CONTENT = probs(complaint_target={"content_missing": 0.95})


def labels(t) -> dict[str, int]:
    return {c.label: c.grade for c in candidates_for(t)}


def suff(verdict, p=None, verified=True, scope="own"):
    p = p if p is not None else {"sufficient": 0.95, "partial": 0.6, "insufficient": 0.05}[verdict]
    return {scope: Sufficiency(scope, "q", [ChunkSupport(0, p, "retrieved")], verdict, verified)}


# ---------------------------------------------------------------------------
# 선택 규칙 — 등급 최대, 같으면 ORDER 의 앞
# ---------------------------------------------------------------------------

def test_higher_grade_wins_regardless_of_order():
    assert pick([Candidate("G3", 1, ""), Candidate("D1", 3, ""), Candidate("I1", 2, "")]).label == "D1"


def test_same_grade_falls_back_to_the_label_order():
    assert pick([Candidate("G2", 2, ""), Candidate("G5", 2, "")]).label == "G5"
    assert taxonomy.ORDER.index("G5") < taxonomy.ORDER.index("G2")


def test_no_candidates_means_unclassified_grade_0():
    t = turn(obs(complaint_target="other"), probabilities=probs(complaint_target={"other": 0.4}))
    c = arbitrate(t)
    assert c.primary_case == taxonomy.UNCLASSIFIED and c.grade == 0 and c.confidence == "low"


def test_confidence_comes_from_the_grade_not_from_a_table():
    for grade, want in ((4, "high"), (3, "high"), (2, "medium"), (1, "low")):
        t = turn()
        close(t, "G1", grade, "r")
        assert t.classification.confidence == want


def test_other_candidates_become_secondary_and_their_tags_stay():
    t = turn(obs(), probabilities=CONTENT, sufficiency=suff("insufficient"),
             checks_=checks(format=Check("format", "violated", "표 없음")))
    c = arbitrate(t)
    assert c.primary_case == "G1" and c.grade == 4          # 코드 확정이 근거 확정을 이긴다
    assert "D1" in c.secondary_cases
    assert {"G1:포맷", "format"} <= set(c.tags)


def test_flags_and_events_ride_on_the_classification():
    t = turn(obs(), probabilities=CONTENT, sufficiency=suff("insufficient"))
    t.flags.append("C1"); t.events.append("U2")
    c = arbitrate(t)
    assert c.flags == ["C1"] and c.events == ["U2"]


# ---------------------------------------------------------------------------
# 확정 사건 · N0 · S1 · U1
# ---------------------------------------------------------------------------

def test_code_confirmed_events_are_grade_4():
    t = turn(obs(), checks_=checks(service_error=Check("service_error", "violated", "문구"),
                                   injection=Check("injection", "violated", "지시"),
                                   leak=Check("leak", "violated", "번호")))
    got = labels(t)
    assert got["I1"] == 4 and got["S2"] == 4 and got["S3"] == 4


def test_lean_illegibility_is_a_grade_1_candidate_only():
    t = turn(obs(), probabilities=CONTENT, legibility_p=0.7)
    assert labels(t).get("I2") == 1
    t.legibility_p = 0.3
    assert "I2" not in labels(t)


def test_no_complaint_is_N0_graded_by_its_probability():
    t = turn(obs(complaint_target="none"), probabilities=probs(complaint_target={"none": 0.95}))
    assert labels(t) == {"N0": 2}
    t = turn(obs(complaint_target="none"), probabilities=probs(complaint_target={"none": 0.7}))
    assert labels(t) == {"N0": 1}


def test_refusal_is_S1_only_when_the_user_complained():
    t = turn(obs(answer_refused=True), probabilities={**CONTENT, **probs(answer_refused=0.95)})
    assert labels(t)["S1"] == 3
    t = turn(obs(answer_refused=True, complaint_target="none"),
             probabilities=probs(complaint_target={"none": 0.9}, answer_refused=0.95))
    assert "S1" not in labels(t) and labels(t)["N0"] == 2


def test_unsupported_output_request_is_U1():
    t = turn(obs(requests_unsupported_output=True),
             probabilities={**CONTENT, **probs(requests_unsupported_output=0.92)})
    assert labels(t)["U1"] == 2


# ---------------------------------------------------------------------------
# T 묶음 — 호출 기록으로
# ---------------------------------------------------------------------------

def test_no_tool_call_and_nothing_fetched_is_T1():
    t = turn(obs(), probabilities=CONTENT,
             case=case(rag_chunks=[], chunk_sources=[], n_fetched=0, tool_calls=[]))
    assert labels(t)["T1"] == 4


def test_T1_needs_a_doc_question_and_a_content_complaint():
    t = turn(obs(question_domain="general_knowledge"), probabilities=CONTENT,
             case=case(rag_chunks=[], chunk_sources=[], n_fetched=0))
    assert "T1" not in labels(t)
    t = turn(obs(complaint_target="format"), probabilities=probs(complaint_target={"format": 0.9}),
             case=case(rag_chunks=[], chunk_sources=[], n_fetched=0))
    assert "T1" not in labels(t)


def test_empty_tool_output_with_asserted_numbers_is_T3():
    c = case(tool_calls=[{"name": "lookup", "arguments": "{}", "order": 0, "turn_no": 2, "outputs": []}],
             tool_outputs=[])
    t = turn(obs(), probabilities=CONTENT, case=c,
             checks_=checks(tool_numbers=Check("tool_numbers", "violated", "빈결과: 수치 2개")))
    assert labels(t)["T3"] == 4


def test_business_tool_only_results_without_an_answer_are_T2(monkeypatch):
    monkeypatch.setattr(settings, "SEARCH_TOOL_NAMES", ("rag_search",))
    c = case(chunk_sources=["tool:line_status"],
             tool_calls=[{"name": "line_status", "arguments": "{}", "order": 0, "turn_no": 2, "outputs": ["x"]}])
    t = turn(obs(), probabilities=CONTENT, case=c, sufficiency=suff("insufficient"))
    got = labels(t)
    assert got["T2"] == 3 and "D1" not in got


def test_without_search_tool_names_the_split_is_not_made(monkeypatch):
    monkeypatch.setattr(settings, "SEARCH_TOOL_NAMES", ())
    c = case(chunk_sources=["tool:line_status"])
    t = turn(obs(), probabilities=CONTENT, case=c, sufficiency=suff("insufficient"))
    [d1] = [x for x in candidates_for(t) if x.label == "D1"]
    assert "D:출처미상" in d1.tags


# ---------------------------------------------------------------------------
# D1 — 2차 검증이 등급을 가른다
# ---------------------------------------------------------------------------

def test_D1_is_grade_3_when_verified_and_2_when_the_second_check_disagrees():
    t = turn(obs(), probabilities=CONTENT, sufficiency=suff("insufficient", verified=True))
    assert labels(t)["D1"] == 3
    t = turn(obs(), probabilities=CONTENT, sufficiency=suff("insufficient", verified=False))
    [d1] = [x for x in candidates_for(t) if x.label == "D1"]
    assert d1.grade == 2 and "2차불일치" in d1.tags


def test_partial_is_still_D1():
    t = turn(obs(), probabilities=CONTENT, sufficiency=suff("partial"))
    assert "D1" in labels(t)


def test_sufficient_documents_never_give_D1():
    t = turn(obs(), probabilities=CONTENT, sufficiency=suff("sufficient"))
    assert "D1" not in labels(t)


# ---------------------------------------------------------------------------
# G1 — 코드 검증기 · 어조
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, tag", [("format", "G1:포맷"), ("language", "G1:언어"), ("length", "G1:길이")])
def test_a_violated_request_is_G1_grade_4_with_its_tag(name, tag):
    t = turn(obs(), probabilities=CONTENT, checks_=checks(**{name: Check(name, "violated", "d")}))
    [g1] = [x for x in candidates_for(t) if x.label == "G1"]
    assert g1.grade == 4 and tag in g1.tags


def test_undetermined_length_is_G1_grade_2_only_when_the_complaint_is_about_length():
    t = turn(obs(complaint_target="length"), probabilities=probs(complaint_target={"length": 0.9}),
             checks_=checks(length=Check("length", "undetermined", "잴 수 없음")))
    assert labels(t)["G1"] == 2
    t = turn(obs(), probabilities=CONTENT, checks_=checks(length=Check("length", "undetermined", "")))
    assert "G1" not in labels(t)


def test_tone_complaint_is_G1_tagged_tone():
    t = turn(obs(complaint_target="tone"), probabilities=probs(complaint_target={"tone": 0.93}))
    [g1] = [x for x in candidates_for(t) if x.label == "G1"]
    assert g1.grade == 2 and "G1:어조" in g1.tags


# ---------------------------------------------------------------------------
# G5 — 주장 단위
# ---------------------------------------------------------------------------

def test_a_contradicted_claim_is_G5_grade_3():
    t = turn(obs(), probabilities=CONTENT, sufficiency=suff("sufficient"),
             claim_verdicts=[ClaimVerdict("x", "doc", "contradicted", 0.9, [0])])
    [g5] = [x for x in candidates_for(t) if x.label == "G5"]
    assert g5.grade == 3 and "G5:어긋남" in g5.tags


def test_sufficient_documents_with_no_supported_claim_is_G5_unused():
    t = turn(obs(), probabilities=CONTENT, sufficiency=suff("sufficient"),
             claim_verdicts=[ClaimVerdict("x", "doc", "not_found", 0.9, [0])])
    [g5] = [x for x in candidates_for(t) if x.label == "G5"]
    assert g5.grade == 2 and "G5:안씀" in g5.tags


def test_supported_claims_are_not_G5():
    t = turn(obs(), probabilities=CONTENT, sufficiency=suff("sufficient"),
             claim_verdicts=[ClaimVerdict("x", "doc", "supported", 0.9, [0])])
    assert "G5" not in labels(t)


def test_evidence_only_in_carried_documents_adds_the_carried_tag():
    sufficiency = {**suff("insufficient"), **suff("sufficient", scope="carried")}
    t = turn(obs(), probabilities=CONTENT, sufficiency=sufficiency,
             claim_verdicts=[ClaimVerdict("x", "doc", "not_found", 0.9, [0])])
    [g5] = [x for x in candidates_for(t) if x.label == "G5"]
    assert {"G5:안씀", "G5:과거근거"} <= set(g5.tags)


def test_fabricated_quotation_marks_are_G5_fabricated():
    t = turn(obs(), probabilities=CONTENT, sufficiency=suff("sufficient"),
             checks_=checks(quoted_spans=Check("quoted_spans", "violated", "원문 없음")))
    [g5] = [x for x in candidates_for(t) if x.label == "G5"]
    assert "G5:지어낸인용" in g5.tags


def test_tool_claims_are_checked_by_code_not_kev():
    t = turn(obs(), probabilities=CONTENT, sufficiency=suff("sufficient"),
             claim_verdicts=[ClaimVerdict("장비 12대", "tool", "tool_mismatch", 1.0)])
    [g5] = [x for x in candidates_for(t) if x.label == "G5"]
    assert g5.grade == 3 and "tool_numbers" in g5.tags


# ---------------------------------------------------------------------------
# G6 · G4 · G2 · G3
# ---------------------------------------------------------------------------

def test_broken_arithmetic_on_a_non_doc_question_is_G6():
    t = turn(obs(question_domain="calculation", complaint_target="content_wrong"),
             probabilities=probs(complaint_target={"content_wrong": 0.9}),
             checks_=checks(arithmetic=Check("arithmetic", "violated", "3+4=8")))
    [g6] = [x for x in candidates_for(t) if x.label == "G6"]
    assert g6.grade == 4 and "G6:계산" in g6.tags


def test_general_knowledge_complaint_without_code_evidence_is_G6_grade_1():
    t = turn(obs(question_domain="general_knowledge", complaint_target="content_wrong"),
             probabilities=probs(complaint_target={"content_wrong": 0.9}))
    [g6] = [x for x in candidates_for(t) if x.label == "G6"]
    assert g6.grade == 1 and "G6:일반" in g6.tags


def test_partial_coverage_of_a_multi_intent_question_is_G4():
    t = turn(obs(question_multi_intent=True, answer_covers_all_intents=False),
             probabilities={**CONTENT, **probs(question_multi_intent=0.95, answer_covers_all_intents=0.05)})
    assert labels(t)["G4"] == 2
    assert "복합질문" in arbitrate(t).tags


def test_ignored_history_is_grade_3_with_a_verified_quote_and_2_without():
    t = turn(obs(answer_ignored_history=True, history_quote="국내 기준으로만"),
             probabilities={**CONTENT, **probs(answer_ignored_history=0.93)},
             history=QuoteCheck("국내 기준으로만", 1.0, True))
    [g2] = [x for x in candidates_for(t) if x.label == "G2"]
    assert g2.grade == 3 and "G2:조건" in g2.tags
    t.history = QuoteCheck("x", 0.0, False)
    [g2] = [x for x in candidates_for(t) if x.label == "G2"]
    assert g2.grade == 2


def test_C1_removes_every_G2_candidate():
    t = turn(obs(answer_ignored_history=True), probabilities={**CONTENT, **probs(answer_ignored_history=0.95)},
             memory_use="ignored", memory_p=0.95, consistency={0: 0.95})
    assert "G2" in labels(t)
    t.flags.append("C1")
    assert "G2" not in labels(t)


def test_C2_removes_only_the_memory_candidate():
    t = turn(obs(), probabilities=CONTENT, memory_use="ignored", memory_p=0.95, consistency={0: 0.95})
    t.flags.append("C2")
    tags = {tag for c in candidates_for(t) if c.label == "G2" for tag in c.tags}
    assert tags == {"G2:모순"}


def test_a_contradiction_with_a_prior_answer_is_G2_graded_by_p_or_quote():
    t = turn(obs(), probabilities=CONTENT, consistency={0: 0.95})
    [g2] = [x for x in candidates_for(t) if x.label == "G2"]
    assert g2.grade == 2 and "G2:모순" in g2.tags
    t.quotes.append({"kind": "G2:모순", "verified": True})
    [g2] = [x for x in candidates_for(t) if x.label == "G2"]
    assert g2.grade == 3


def test_G3_is_the_residual_and_never_outranks_a_specific_cause():
    t = turn(obs(), probabilities=CONTENT)
    assert labels(t) == {"G3": 1}
    t = turn(obs(), probabilities=CONTENT, sufficiency=suff("insufficient"))
    assert "G3" not in labels(t)


def test_G3_carries_the_asked_back_tag_when_the_question_was_unclear():
    t = turn(obs(question_clarity="vague", answer_asked_back=False),
             probabilities={**CONTENT, **probs(question_clarity={"vague": 0.9})})
    c = arbitrate(t)
    assert c.primary_case == "G3" and {"되묻기없음", "U3"} <= set(c.tags)


def test_violated_checks_always_become_tags():
    t = turn(obs(), probabilities=CONTENT, sufficiency=suff("insufficient"),
             checks_=checks(pii=Check("pii", "violated", "x"), dates=Check("dates", "violated", "y")))
    assert {"pii", "dates"} <= set(arbitrate(t).tags)


def test_every_candidate_label_is_a_failure_label():
    for label in taxonomy.ORDER:
        assert taxonomy.get(label).kind == "failure"
