"""골든셋 자체가 멀쩡한가. LLM 없이 돈다.

골든셋은 실제 모델로만 돌리므로 평소 테스트가 건드리지 않는다. 그래서 두 번 조용히
깨졌다 — build() 가 import 없이 라벨 표를 써서 --golden 이 통째로 멈췄고, id 가 겹쳐
두 케이스의 기대값이 다른 케이스에 덮여 채점되지 않았다.
"""

import pytest

from ragdiag import taxonomy
from ragdiag.fixtures import judgments, messy, observations


def test_observation_golden_set_builds_and_grades_every_case():
    ids = [case["id"] for case in observations.CASES]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"id 가 겹친다 — 뒤 케이스가 앞 케이스의 기대값을 덮는다: {dupes}"

    _, expected = observations.build()
    assert len(expected) == len(observations.CASES), "채점되지 않는 케이스가 있다"


def test_observation_golden_set_expects_only_real_fields():
    from ragdiag.schema import Observation

    graded = set(Observation.model_fields) | {
        "complaint_quote_verified", "request_quote_verified", "history_quote_verified"}
    unknown = sorted({name for case in observations.CASES for name in case["expect"]} - graded)
    assert not unknown, f"관측에 없는 필드를 기대한다: {unknown}"


def test_judgment_golden_ids_are_unique():
    for table in (judgments.SUFFICIENCY, judgments.GROUNDING):
        ids = [entry["id"] for entry in table]
        assert len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1})


def test_sufficiency_golden_set_is_well_formed():
    """expect_cited 는 실제 청크 범위 안이고, accept 는 expect_verdict 를 품는다."""
    for entry in judgments.SUFFICIENCY:
        for idx in entry.get("expect_cited") or ():
            assert 0 <= idx < len(entry["chunks"]), f"{entry['id']}: expect_cited {idx}"
        accept = entry.get("accept")
        if accept:
            assert entry["expect_verdict"] in accept, entry["id"]
        if entry.get("inflated"):
            assert entry["expect_verdict"] == "sufficient", (
                f"{entry['id']}: 부풀림 케이스는 질문 기준 정답(sufficient)을 둔다")


@pytest.mark.parametrize("need, multi, want", [
    ("근무지 내 국내 출장 4시간 미만 시 여비 금액과 그 지급 절차, 신청 서류, 정산 기한", False,
     "근무지 내 국내 출장 4시간 미만 시 여비 금액과 그 지급 절차"),   # "과" 는 경계가 아니다
    ("담당 부서의 구체적인 이름과 내선 번호", False, "담당 부서의 구체적인 이름과 내선 번호"),
    ("재직 3년차 공무원의 연가 일수, 연가 신청 방법, 반차 사용 가능 여부", False, "재직 3년차 공무원의 연가 일수"),
    ("반차 신청 가능 여부 및 반차 신청 방법", False, "반차 신청 가능 여부"),     # 좁혀진 요구는 첫 항목
    ("유럽 지역 숙박비 상한", False, "유럽 지역 숙박비 상한"),                   # 항목 하나면 그대로
    ("국내 출장 식비 상한과 교통비 상한", True, "국내 출장 식비 상한과 교통비 상한"),  # 복합 질문은 전부
    ("", False, ""),
])
def test_narrow_need_keeps_only_the_first_item_for_single_intent_questions(need, multi, want):
    from ragdiag.features.sufficiency import narrow_need
    assert narrow_need(need, multi) == want


def test_sufficiency_feature_narrows_the_need_but_keeps_the_observation_intact():
    """Step 2 프롬프트에는 첫 항목만 가고, 관측 · 결과 파일의 unmet_need 는 그대로다."""
    from types import SimpleNamespace

    from ragdiag.features import sufficiency
    from ragdiag.schema import Case, Observation, SufficiencyJudgment

    obs = Observation(
        reasoning="r", resolved_question="3년차면 연가 며칠이에요?",
        unmet_need="재직 3년차 연가 일수, 연가 신청 방법, 반차 사용 가능 여부",
        complaint_target="content_missing", question_domain="domain", question_clarity="clear",
        question_multi_intent=False, answer_refused=False, answer_covers_all_intents=True,
        answer_actionable=True, answer_ignored_history=False, requests_unsupported_output=False,
        requested_language="none", requested_length_kind="none", requested_length_value=0,
        requested_format="none")
    case = Case(case_id="c", user_id="-", dept="-", job_grade="-", job_name="-", position_name="-",
                conversation_id="-", turn=2, pre_queries=["3년차면 연가 며칠이에요?"],
                llm_ans_on_last_q="규정을 참고하세요", current_query="며칠이냐구요",
                rag_chunks=["재직 3년 이상 4년 미만 연가 14일"])
    seen = {}

    class FakeJudge:
        def judge_sufficiency_from(self, case, o):
            seen["need"] = o.unmet_need
            return SufficiencyJudgment(reasoning="", evidence=[], verdict="insufficient", missing=""), None

    turn = SimpleNamespace(case=case, observation=obs, judgment=None, error=None, notes=[], n_calls=0,
                           usage=None)
    ctx = SimpleNamespace(judge=FakeJudge(), turns=[turn], workers=1, backend=None,
                          open_turns=lambda: [turn])
    try:
        sufficiency.process_data(ctx)
    except Exception:
        pass   # each_turn 의 부수 처리는 여기서 재지 않는다 - 판정자에 간 요구만 본다
    assert seen["need"] == "재직 3년차 연가 일수"
    assert obs.unmet_need.startswith("재직 3년차 연가 일수, 연가 신청 방법")


def test_grounding_golden_set_is_well_formed():
    """검색 결과 모양 케이스는 인용 청크(cited)가 있고, accept 는 expect 를 품는다."""
    for entry in judgments.GROUNDING_WIDE:
        assert entry["cited"] and all(0 <= i < len(entry["chunks"]) for i in entry["cited"]), entry["id"]
        assert entry["question"] and entry["answer"], entry["id"]
        if entry.get("accept"):
            assert entry["expect"] in entry["accept"], entry["id"]
        assert 10 <= len(entry["chunks"]) <= 15, entry["id"]


def test_score_sufficiency_grades_the_downgraded_verdict_and_two_tiers():
    """파이프라인과 같은 값을 채점한다 - 인용이 하나도 안 살면 sufficient 도 insufficient 다."""
    from ragdiag.golden import JudgeScore, score_sufficiency
    from ragdiag.schema import Evidence, SufficiencyJudgment
    from ragdiag.verify import verify_evidence

    chunks = ["국내 출장 식비는 1일 3만원을 상한으로 한다."]
    case = dict(id="x", note="", category="clear", chunks=chunks,
                expect_verdict="sufficient", expect_cited={0})

    def judged(verdict, quote):
        j = SufficiencyJudgment(reasoning="", verdict=verdict, missing="",
                                evidence=[Evidence(chunk_index=0, quote=quote)])
        return j, verify_evidence(j.evidence, chunks)

    score = JudgeScore()
    score_sufficiency(case, *judged("sufficient", "식비는 1일 3만원을 상한으로"), score)
    assert (score.verdict_hits, score.routing_hits, score.downgraded) == (1, 1, 0)

    # 지어낸 인용 → 강등 → 3분류 · 2분류 모두 틀림
    score_sufficiency(case, *judged("sufficient", "숙박비는 1박 8만원을 상한으로 한다"), score)
    assert (score.verdict_hits, score.routing_hits, score.downgraded) == (1, 1, 1)
    assert ("x", "sufficient", "insufficient") in [m[:3] for m in score.misses]

    # partial 을 낸 경우 - 3분류는 틀리고 2분류(sufficient 아님)는 기대와 다르므로 역시 틀림
    score_sufficiency(case, *judged("partial", "식비는 1일 3만원을 상한으로"), score)
    assert (score.verdict_hits, score.routing_hits) == (1, 1)

    # accept 로 넓힌 케이스 - partial 도 맞은 것으로 치고 2분류도 통과
    wide = dict(case, accept={"sufficient", "partial"})
    score_sufficiency(wide, *judged("partial", "식비는 1일 3만원을 상한으로"), score)
    assert (score.verdict_hits, score.routing_hits) == (2, 2)
    assert score.by_category["clear"] == [2, 4]


@pytest.mark.parametrize("fixture", [observations, messy])
def test_golden_sets_build_and_grade_every_case(fixture):
    ids = [case["id"] for case in fixture.CASES]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"{fixture.__name__}: id 가 겹친다: {dupes}"
    _, expected = fixture.build()
    assert len(expected) == len(fixture.CASES)


def test_messy_set_expects_real_fields_and_reachable_cases():
    from ragdiag.schema import Observation

    graded = set(Observation.model_fields) | {
        "complaint_quote_verified", "request_quote_verified", "history_quote_verified"}
    for case in messy.CASES:
        unknown = set(case["expect"]) - graded
        assert not unknown, f"{case['id']}: 관측에 없는 필드 {unknown}"
        assert case["expect_case"], f"{case['id']}: expect_case 가 없다"
        for cid in case["expect_case"] | case.get("expect_secondary", set()):
            assert cid in (taxonomy.UNCLASSIFIED, taxonomy.OUT_OF_TAXONOMY) or (
                taxonomy.get(cid) and taxonomy.get(cid).diagnosable), f"{case['id']}: {cid}"


def test_messy_set_looks_like_the_operational_log():
    """실행 로그(pseudo_input)에서 본 필드 모양을 따른다."""
    raw, _ = messy.build()
    user = raw["users"][0]
    assert {"user_id", "db_login_id", "job_grade"} <= set(user)
    turn = user["conversations"][0]["turns"][-1]
    assert {"timestamp", "user_question", "llm_response", "conversation_id",
            "llm_eval_result", "llm_eval_score", "llm_eval_score_top1", "llm_eval_alternatives",
            "llm_eval_context_summarized",
            "llm_emotion_result", "llm_emotion_alternatives",
            "llm_emotion_context_summarized"} <= set(turn)
    assert turn["conversation_id"].endswith("_conv_1")


def coverage() -> dict[str, int]:
    """messy 셋이 case 마다 몇 건을 겨냥하는가 (expect_case ∪ expect_secondary)."""
    counts = {cid: 0 for cid in taxonomy.CASES}
    for case in messy.CASES:
        for cid in case["expect_case"] | case.get("expect_secondary", set()):
            if cid in counts:
                counts[cid] += 1
    return counts


def test_messy_set_reaches_every_diagnosable_case():
    """판정 가능한 case 는 전부 라우팅 골든셋에 겨냥하는 케이스가 있어야 한다.

    없으면 그 case 로 가는 경로는 한 번도 실제로 돌아본 적이 없는 것이다 — case6 · 21 · 24 가
    그랬다. 판정 불가 넷(5 · 7 · 19 · 23)은 라우팅이 만들지 않으므로 제외한다.
    """
    missing = [cid for cid, n in coverage().items()
               if n == 0 and taxonomy.get(cid).diagnosable]
    assert not missing, f"라우팅 골든셋이 한 번도 겨냥하지 않는 case: {missing}"


if __name__ == "__main__":
    for cid, n in coverage().items():
        meta = taxonomy.get(cid)
        print(f"{cid:<8}{meta.name:<24}{n:>3}" + ("" if meta.diagnosable else "   (판정 불가)"))
