"""턴 단위 실행 — 턴 하나가 판정 기능 전부를 끝까지 간다.

단계별 실행과 **같은 판정**을 내야 한다 (기능은 한 줄도 안 바뀌고 도는 순서만 다르다).
느린 턴은 다른 턴을 막지 않고, 끝난 턴부터 저장되며, 낙오자는 턴 전체 시간으로 닫힌다.
"""

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from ragdiag import features, settings
from ragdiag.output import build_turn
from ragdiag.pipeline import judge_cases
from ragdiag.results import TurnResult

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stub_judge import ScriptedJudge, digest, make_case  # noqa: E402
from test_snapshot import scenarios  # noqa: E402


_CONV = SimpleNamespace(chat_id="chat", user=SimpleNamespace(dept="", job_grade="", job_name=""))


def _digests(mode, monkeypatch):
    monkeypatch.setattr(settings, "RUN_MODE", mode)
    results = judge_cases([make_case(s) for s in scenarios()], ScriptedJudge(), workers=3)
    return {r.case.case_id: digest(build_turn(r, _CONV)["verdict"] if r.verdict else {"error": r.error})
            for r in results}


def test_turn_mode_judges_exactly_like_stage_mode(monkeypatch):
    """모든 시나리오(관측 × 충족도 × 근거 활용 × 실패 · 캐시 · 붕괴)에서 결과가 같아야 한다."""
    assert _digests("turn", monkeypatch) == _digests("stage", monkeypatch)


def test_registry_is_split_into_judges_and_reports():
    names = [f.NAME for f in features.FEATURES]
    assert names == [f.NAME for f in features.JUDGES] + [f.NAME for f in features.REPORTS]
    assert len(features.REPORTS) == 4, "집계 넷 - 판정이 끝난 뒤 한 번 돈다"
    assert [f.NAME for f in features.JUDGES] == \
        ["integrity", "code_rules", "complaint", "evidence", "complaint_evidence"], \
        "결정 트리의 순서다 — 앞이 닫은 턴은 뒤로 안 간다"


class _SlowJudge(ScriptedJudge):
    """한 턴만 불만 판정(kev)에서 오래 걸린다."""

    def __init__(self, slow_id, seconds):
        super().__init__()
        self.slow_id, self.seconds = slow_id, seconds

    def decide(self, stage, state, questions):
        from ragdiag.features._shared import current_turn
        if stage == "complaint" and current_turn().case.case_id == self.slow_id:
            time.sleep(self.seconds)
        return super().decide(stage, state, questions)


@pytest.fixture
def quick_cutoff(monkeypatch):
    monkeypatch.setattr(settings, "RUN_MODE", "turn")
    monkeypatch.setattr(settings, "STRAGGLER_FACTOR", 4.0)
    monkeypatch.setattr(settings, "STRAGGLER_MIN_SEC", 0.3)


def test_a_slow_turn_does_not_block_the_others_and_is_abandoned_in_its_stage(quick_cutoff):
    cases = [make_case(f"generation-all{i}") for i in range(12)]
    slow = cases[4].case_id

    t0 = time.monotonic()
    results = judge_cases(cases, _SlowJudge(slow, 5.0), workers=4)
    took = time.monotonic() - t0

    assert took < 3.0, f"느린 턴을 기다렸다: {took:.1f}s"
    stuck = next(r for r in results if r.case.case_id == slow)
    assert stuck.error and stuck.error.startswith("[complaint] 낙오"), stuck.error
    assert all(r.verdict is not None for r in results if r.case.case_id != slow)


def test_finished_turns_are_handed_over_as_they_complete(monkeypatch):
    monkeypatch.setattr(settings, "RUN_MODE", "turn")
    cases = [make_case(f"generation-all{i}") for i in range(5)]
    seen = []
    ctx = features.RunContext(turns=[TurnResult(case=c) for c in cases], judge=ScriptedJudge(),
                              workers=2, progress=False, on_turn_done=seen.append)
    features.collect(ctx)
    assert len(seen) == 5 and all(t.verdict is not None for t in seen)


def test_checkpoint_writes_only_finished_turns(tmp_path):
    from ragdiag.__main__ import _checkpointer

    owners = [SimpleNamespace(chat_id=f"c{i}", user=SimpleNamespace(
        job_grade="", dept="", job_name="")) for i in range(3)]
    turns = [TurnResult(case=make_case(f"generation-all{i}")) for i in range(3)]
    out = tmp_path / "out.json"
    save = _checkpointer(owners, turns, out, {"started": "x"}, every_sec=0)

    save(turns[0])
    assert not out.exists(), "끝난 턴이 없으면 쓰지 않는다"
    turns[0].error = "[complaint] 낙오"
    save(turns[0])
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert len(payload["turns"]) == 1 and "error" in payload["turns"][0]


class _AnyJudge(ScriptedJudge):
    """어떤 case 든 같은 경로(근거 없음 → 근거)로 답한다. 합성 로그용 - case_id 가 경로가 아니다."""

    def __init__(self):
        from ragdiag.decide import ScriptedBackend
        from ragdiag.judge import Judge

        def script(state, questions):
            if "complains" in questions:
                return {"complains": True}
            if "any" in questions:
                return {"any": "none"}
            return {}
        Judge.__init__(self, backend=None, cache_dir=None, decision=ScriptedBackend(script))


def _four_turn_log() -> dict:
    """한 사용자 · 대화 둘 · 한 대화에 턴 넷. 후속 턴 셋(2·3·4)이 전부 판정 대상이다."""
    def turn(no):
        return {"turn": no, "timestamp": f"2026-04-01 10:0{no}:00.000",
                "user_question": f"질문 {no}", "llm_response": f"답변 {no} 입니다.",
                "retrieved_data": json.dumps(["국내 출장 식비는 1일 3만원을 상한으로 한다."]),
                "trace_matched": True, "llm_eval_result": None if no == 1 else "명확화 요구",
                "llm_eval_score": None if no == 1 else 25, "llm_eval_score_top1": None if no == 1 else 25,
                "llm_eval_alternatives": [], "llm_emotion_result": None if no == 1 else "부정",
                "llm_emotion_score": None if no == 1 else 12.5, "llm_emotion_score_top1": None,
                "llm_emotion_alternatives": []}
    user = {"user_id": "E1", "db_login_id": "e1", "db_dept_name": "인사팀", "db_job_name": "-",
            "job_grade": "대리", "db_position_name": "-",
            "conversations": [{"chat_id": "E1_conv_1", "turns": [turn(n) for n in range(1, 5)]},
                              {"chat_id": "E1_conv_2", "turns": [turn(1), turn(2)]}]}
    return {"users": [user]}


def test_turn_mode_writes_the_same_turn_list(tmp_path, monkeypatch):
    """끝나는 순서가 뒤섞여도 결과 파일의 turns 는 입력 순서다.

    build_output 이 zip(owners, results) 의 원래 순서로 쓰므로 실행 순서와 무관하다.
    """
    from ragdiag.pipeline import build_outcome, load_and_select

    log = tmp_path / "conv_eval.json"
    log.write_text(json.dumps(_four_turn_log(), ensure_ascii=False), encoding="utf-8")
    selection = load_and_select(log)
    assert len(selection) == 4, "conv_1 의 턴 2·3·4 와 conv_2 의 턴 2"

    def payload(mode):
        monkeypatch.setattr(settings, "RUN_MODE", mode)
        results = judge_cases(selection.cases, _AnyJudge(), workers=4)
        assert all(r.error is None for r in results), [r.error for r in results]
        return build_outcome(selection.owners, results, run_info={"started": "x"}).payload

    turn_mode, stage_mode = payload("turn"), payload("stage")
    assert turn_mode == stage_mode

    assert [(t["chat_id"], t["turn"]) for t in turn_mode["turns"]] == \
        [("E1_conv_1", 2), ("E1_conv_1", 3), ("E1_conv_1", 4), ("E1_conv_2", 2)]
    assert all(t["verdict"]["bucket"] == "근거" for t in turn_mode["turns"])
