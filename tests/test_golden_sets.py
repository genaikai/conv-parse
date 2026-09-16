"""골든셋 자체가 멀쩡한가. LLM 없이 돈다.

골든셋은 실제 모델로만 돌리므로 평소 테스트가 건드리지 않는다. 그래서 두 번 조용히
깨졌다 — build() 가 import 없이 라벨 표를 써서 --golden 이 통째로 멈췄고, id 가 겹쳐
두 케이스의 기대값이 다른 케이스에 덮여 채점되지 않았다.
"""

from ragdiag.fixtures import judgments, observations


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
