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


def test_narrow_need_keeps_the_first_item_for_single_questions():
    """v3 의 충족도는 resolved_question 과 unmet_need 로 묻는다. narrow_need 는 대시보드의
    "요구" 열과 골든셋 러너가 쓴다 - 질문이 한 가지면 첫 항목만."""
    from ragdiag.features.sufficiency import narrow_need

    need = "재직 3년차 연가 일수, 연가 신청 방법, 반차 사용 가능 여부"
    assert narrow_need(need, False) == "재직 3년차 연가 일수"
    assert narrow_need(need, True) == need


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
        # messy 셋은 v2 번호로 적혀 있다. v3 라벨로 옮겨지거나(라벨 · 태그) 제외된 것이어야 한다.
        for cid in case["expect_case"] | case.get("expect_secondary", set()):
            label, tag = taxonomy.from_v2(cid)
            assert cid in (taxonomy.UNCLASSIFIED, taxonomy.OUT_OF_TAXONOMY) or label or tag \
                or cid in taxonomy.V2_TO_V3, f"{case['id']}: {cid}"


def test_messy_set_looks_like_the_operational_log():
    """실행 로그(pseudo_input)에서 본 필드 모양을 따른다."""
    raw, _ = messy.build()
    user = raw["users"][0]
    # 사용자 식별자는 로그에 없다 (2026-10). 골든셋이 옛 모양을 들고 있으면
    # 거기서만 통과하는 코드가 생긴다.
    assert {"job_grade", "db_dept_name", "db_job_name"} <= set(user)
    assert not {"user_id", "db_login_id", "db_position_name"} & set(user)
    turn = user["conversations"][0]["turns"][-1]
    assert {"request_time", "user_question", "llm_response",
            "llm_eval_result", "llm_eval_score", "llm_eval_alternatives",
            "llm_eval_context_summarized",
            "llm_emotion_result", "llm_emotion_alternatives",
            "llm_emotion_context_summarized",
            # 2026-10. 골든셋이 옛 모양을 들고 있으면 실제 실행이 타는 경로를 안 잰다.
            "history_input", "tool_output", "memory", "carried_turn_nos",
            "ask_on", "answered_by", "route_intent", "fallback"} <= set(turn)
    # 2026-10 컬럼 목록에서 빠졌다. 짝인 emotion 쪽은 남아 있어 확인 중이다.
    assert "llm_eval_score_top1" not in turn
    # 대화 id 는 대화 층에만 있다 - 턴마다 되풀이되던 것은 옛 로그 모양이다.
    assert "conversation_id" not in turn
    assert user["conversations"][0]["conversation_id"].endswith("_conv_1")
    # 2턴 이상인 턴은 history_input 이 있고, 그 안의 user 메시지가 앞 질문들이다.
    prior = user["conversations"][0]["turns"][:-1]
    users_in_chat = [m["content"] for m in turn["history_input"]["history_chat"]
                     if m["role"] == "user"]
    assert users_in_chat == [t["user_question"] for t in prior]


def coverage() -> dict[str, int]:
    """messy 셋(v2 번호 → v3 라벨)과 v3 테스트셋이 라벨 · 플래그 · 이벤트마다 몇 건을 겨냥하는가."""
    from ragdiag.fixtures import v3_cases

    counts = {cid: 0 for cid in taxonomy.LABELS}
    for case in messy.CASES:
        for cid in case["expect_case"] | case.get("expect_secondary", set()):
            label, _ = taxonomy.from_v2(cid)
            if label in counts:
                counts[label] += 1
    for case in v3_cases.CASES:
        for cid in [case["expect"], *case.get("flags", []), *case.get("events", [])]:
            if cid in counts:
                counts[cid] += 1
    return counts


def test_test_sets_reach_every_label_flag_and_event():
    """라벨 · 플래그 · 이벤트는 전부 어느 테스트셋이든 겨냥하는 케이스가 있어야 한다.

    없으면 그리로 가는 경로는 한 번도 실제로 돌아본 적이 없는 것이다.
    """
    missing = [cid for cid, n in coverage().items() if n == 0]
    assert not missing, f"어느 테스트셋도 겨냥하지 않는 라벨: {missing}"


if __name__ == "__main__":
    for cid, n in coverage().items():
        meta = taxonomy.get(cid)
        print(f"{cid:<6}{meta.name:<24}{n:>3}")


def test_legibility_golden_set_is_well_formed():
    """붕괴 쪽은 코드 규칙이 못 잡는 모양만 담는다 - 규칙이 잡는 것은 여기 있을 자리가 아니다."""
    from ragdiag.features.short_circuit.degenerate import check_degenerate

    ids = [c["id"] for c in judgments.LEGIBILITY]
    assert len(ids) == len(set(ids))
    assert sum(not c["legible"] for c in judgments.LEGIBILITY) == 22
    assert sum(c["legible"] for c in judgments.LEGIBILITY) == 50, "정상을 붕괴의 두 배 이상으로 둔다 - 재는 것이 오탐이다"
    caught = [c["id"] for c in judgments.LEGIBILITY if check_degenerate(c["answer"]).violated]
    assert not caught, f"코드 규칙이 먼저 잡는다: {caught}"


def test_golden_sets_take_the_whole_history_chat_and_fall_back_to_a_window():
    """pre_queries 에 고정 길이는 없다. history_chat 이 있으면 그 길이만큼이다.

    최근 3턴(MAX_HISTORY_TURNS)으로 자르는 것은 history_input 이 **없을 때의** 폴백이다.
    두 길이 다르게 나오는 케이스(긴 대화)가 있어야 폴백이 실제로 다른 길인 것이고,
    짧은 대화에서는 둘이 같아야 폴백이 멀쩡한 것이다.
    """
    import copy

    from ragdiag import settings
    from ragdiag.conv import parse_conversations, to_case

    def cases(raw):
        return {c.case_id: c for conv in parse_conversations(raw)
                for c in [to_case(conv, conv.turns[-1].turn)]}

    for mod in (observations, messy):
        raw, _ = mod.build()
        stripped = copy.deepcopy(raw)
        for user in stripped["users"]:
            for conv in user["conversations"]:
                for turn in conv["turns"]:
                    for key in ("history_input", "prev_question",
                                "carried_turn_nos", "carried_turn_count"):
                        turn.pop(key, None)
        full, fallback = cases(raw), cases(stripped)
        longer = 0
        for conv in parse_conversations(raw):
            key = f"{conv.conversation_id}:{conv.turns[-1].turn}"
            questions = [t.user_question for t in conv.turns[:-1]]
            # 새 경로: 앞 질문 전부 + 비판받은 답변을 부른 질문. 자르지 않는다.
            assert full[key].pre_queries == questions, key
            # 폴백: 최근 N개.
            assert fallback[key].pre_queries == questions[-settings.MAX_HISTORY_TURNS:], key
            # 청크 풀과 이 턴 검색 건수는 길에 따라 달라지면 안 된다.
            assert full[key].rag_chunks == fallback[key].rag_chunks, key
            assert full[key].n_fetched == fallback[key].n_fetched, key
            longer += len(full[key].pre_queries) > len(fallback[key].pre_queries)
        assert longer, f"{mod.__name__}: 폴백과 길이가 갈리는 긴 대화가 하나도 없다"
