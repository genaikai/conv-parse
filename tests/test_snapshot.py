"""열한 경로의 verdict 스냅숏. 배관이 바뀌어도 결론이 흔들리면 안 된다."""

import sys
from pathlib import Path

import pytest

from ragdiag.output import build_turn
from ragdiag.pipeline import judge_cases

sys.path.insert(0, str(Path(__file__).parent))
from snapshots.v4 import SNAPSHOT  # noqa: E402
from stub_judge import ScriptedJudge, make_case, scenarios  # noqa: E402

CONV = type("C", (), {"chat_id": "chat", "user": type("U", (), {"dept": "부서", "job_grade": "직급", "job_name": "직무"})()})()


@pytest.fixture(scope="module")
def verdicts():
    results = judge_cases([make_case(s) for s in scenarios()], ScriptedJudge(), workers=1, progress=False)
    return {r.case.case_id.split(":")[1]: build_turn(r, CONV)["verdict"] for r in results}


def test_judgment_matches_the_snapshot(verdicts):
    assert verdicts == SNAPSHOT, "스냅숏과 다르다. 설계가 바뀐 것이면 snapshots/v4.py 를 갱신할 것"


def test_snapshot_walks_every_exit():
    assert set(SNAPSHOT) == set(scenarios())
    assert {v["bucket"] for v in SNAPSHOT.values()} == {"정상", "사용자", "근거", "생성", "시스템", "검토"}
