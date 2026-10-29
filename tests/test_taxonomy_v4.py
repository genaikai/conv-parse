"""v4 원본 두 곳 — 묶음 · 단계 · 고정 문장(taxonomy) 과 문항(questions) 이 설계대로인가."""

from ragdiag import questions, taxonomy


def test_buckets_are_five_plus_review_in_order():
    assert list(taxonomy.BUCKETS) == ["normal", "user", "evidence", "generation", "system", "review"]
    assert taxonomy.BUCKETS["evidence"].name == "근거"
    assert taxonomy.BUCKETS["review"].owner == "사람"


def test_complaint_questions_keep_the_reading_order():
    assert list(questions.COMPLAINT) == ["complains", "refusal", "illegible", "truncated",
                                         "language", "emotion_only", "new_demand", "no_doc"]
    assert set(questions.COMPLAINT_ROUTE) == set(questions.COMPLAINT)
    assert questions.COMPLAINT_ROUTE["complains"] == (None, "normal")


def test_every_question_has_a_result_sentence_and_sentences_are_unique():
    ids = [*questions.COMPLAINT, *questions.EVIDENCE_SLOT, *questions.EVIDENCE_ANY,
           *questions.COMPLAINT_EVIDENCE]
    assert set(ids) <= set(questions.TEXT)
    sentences = [questions.TEXT[i] for i in ids]
    assert len(sentences) == len(set(sentences))


def test_every_exit_has_a_fixed_sentence():
    for qid, (yes, no) in questions.COMPLAINT_ROUTE.items():
        if yes:
            assert f"{taxonomy.STEP_COMPLAINT}:{qid}:yes" in taxonomy.BECAUSE
        if no:
            assert f"{taxonomy.STEP_COMPLAINT}:{qid}:no" in taxonomy.BECAUSE
    for key in ("any:all", "any:none", "empty"):
        assert f"{taxonomy.STEP_EVIDENCE}:{key}" in taxonomy.BECAUSE
    for key in ("service_error", "empty_answer", "degenerate"):
        assert f"{taxonomy.STEP_CODE}:{key}" in taxonomy.BECAUSE
    for key in ("targeted:yes", "targeted:no"):
        assert f"{taxonomy.STEP_COMPLAINT_EVIDENCE}:{key}" in taxonomy.BECAUSE


def test_any_question_is_a_three_way_choice():
    assert list(questions.EVIDENCE_ANY["any"]["criteria"]) == ["all", "partial", "none"]


def test_slots_pair_ids_with_korean_names():
    assert [s for s, _ in questions.SLOTS] == ["retrieved", "tool", "history", "memory"]
    assert dict(questions.SLOTS)["history"] == "앞 턴 근거"
    assert set(questions.EVIDENCE_SLOT) == {"in_retrieved", "in_tool", "in_history", "in_memory"}


def test_review_sentences_carry_the_question_and_p():
    assert taxonomy.stopped_at_review("불만 판정", "x") == "불만 판정 · x"
    assert taxonomy.because_review("불만 판정", "x", 0.55) == "x — 확신이 없다 (p 0.55)"
