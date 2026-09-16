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
        for cid in case["expect_case"]:
            assert cid in (taxonomy.UNCLASSIFIED, taxonomy.OUT_OF_TAXONOMY) or (
                taxonomy.get(cid) and taxonomy.get(cid).diagnosable), f"{case['id']}: {cid}"


def test_messy_set_looks_like_the_operational_log():
    """실행 로그(pseudo_input)에서 본 필드 모양을 따른다."""
    raw, _ = messy.build()
    user = raw["users"][0]
    assert {"user_id", "db_login_id", "job_grade"} <= set(user)
    turn = user["conversations"][0]["turns"][-1]
    assert {"timestamp", "user_question", "llm_response", "conversation_id",
            "llm_eval_result", "llm_eval_score", "llm_eval_score_top1", "llm_alternatives",
            "llm_emotion_result", "llm_emotion_alternatives"} <= set(turn)
    assert turn["conversation_id"].endswith("_conv_1")
