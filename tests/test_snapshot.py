"""판정 결과 스냅숏 — 구조를 바꿔도 결과가 그대로인지 본다.

부품 테스트(test_checks · test_arbitrate)는 부품 하나하나를 잰다. 이건 **부품이 어떤
순서로 불리고 무엇을 넘겨받는지**를 잰다 - 어느 단계를 건너뛰는지, LLM · kev 를 몇 번
부르는지, 실패가 어느 단계 이름으로 남는지. 판정 순서를 옮기는 동안 여기가 한 글자도
바뀌면 안 된다.

LLM 도 kev 도 부르지 않는다. case_id 에 적힌 시나리오대로 답하는 판정자를 쓴다
(tests/stub_judge.py):

    텍스트|관측|충족도|주장|모드      예: rich|missing|partial|not_found|ok

스냅숏은 판정 결과가 **의도적으로** 바뀌었을 때만 다시 뜬다:

    UPDATE_SNAPSHOT=1 ./venv/bin/python -m pytest tests/test_snapshot.py

스냅숏이 JSON 이 아니라 파이썬인 이유: 이 저장소는 JSON 을 추적하지 않는다
(tests/test_spec_compliance.py::test_no_json_fixtures_are_tracked).
"""

import os
import runpy
import sys
from pathlib import Path

from ragdiag import settings
from ragdiag.output import build_turn
from ragdiag.pipeline import judge_cases

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stub_judge import (CLAIMS, DOMAIN_CONTENT, OBSERVATIONS, SUFFICIENCY_P,  # noqa: E402
                        ScriptedJudge, digest, make_case)

SNAPSHOT = Path(__file__).parent / "snapshots" / "judgment.py"


def scenarios():
    yield "service|missing|sufficient|supported|ok"
    yield "injected|missing|sufficient|supported|ok"
    for o in ("format", "language", "length", "missing"):
        yield f"asked|{o}|sufficient|supported|ok"
    for s in ("sufficient", "insufficient"):
        yield f"conditioned|history|{s}|supported|ok"
    yield "tooled|technical|insufficient|none|ok"
    yield "bizonly|technical|insufficient|none|ok"
    yield "gapped|history|sufficient|supported|ok"
    yield "foreign-memory|missing|sufficient|supported|memory-ignored"
    yield "clean|other|sufficient|supported|unsure"
    for mode in ("ok", "memory-ignored", "inconsistent"):
        yield f"contextual|missing|sufficient|supported|{mode}"
    for text in ("clean", "rich", "empty", "broken"):
        for o in OBSERVATIONS:
            pairs = ([(s, c) for s in SUFFICIENCY_P for c in CLAIMS]
                     if o in DOMAIN_CONTENT else [("sufficient", "supported")])
            for s, c in pairs:
                yield f"{text}|{o}|{s}|{c}|ok"
    # 실패는 그 단계 이름으로 남아야 하고, 캐시 적중은 호출로 세지 않는다
    for mode in ("fail-observe", "fail-sufficiency", "fail-claims", "cached", "illegible"):
        yield f"rich|missing|sufficient|supported|{mode}"


def current() -> dict:
    # 검색 도구 이름이 있어야 D1 과 T2 가 갈린다. 시나리오 "bizonly" 가 그 길을 밟는다.
    saved = settings.SEARCH_TOOL_NAMES
    settings.SEARCH_TOOL_NAMES = ("rag_search",)
    try:
        results = judge_cases([make_case(s) for s in scenarios()], ScriptedJudge(), workers=1,
                              progress=False)
    finally:
        settings.SEARCH_TOOL_NAMES = saved
    return {r.case.case_id: digest(build_turn(r, r.case.turn - 1)["classification"])
            for r in results}


def load_snapshot() -> dict:
    return runpy.run_path(str(SNAPSHOT))["EXPECTED"]


def test_judgment_matches_the_snapshot():
    got = current()
    if os.environ.get("UPDATE_SNAPSHOT"):
        SNAPSHOT.parent.mkdir(exist_ok=True)
        rows = "".join(f"    {key!r}: {got[key]!r},\n" for key in sorted(got))
        SNAPSHOT.write_text(
            "# 판정 결과 스냅숏. tests/test_snapshot.py 가 만든다 — 손으로 고치지 말 것.\n"
            "EXPECTED = {\n" + rows + "}\n",
            encoding="utf-8")
    want = load_snapshot()

    assert got.keys() == want.keys(), "시나리오 목록이 바뀌었다 — 스냅숏을 다시 떠야 한다"
    diff = [k for k in want if got[k] != want[k]]
    assert not diff, (f"{len(diff)}건이 달라졌다. 예: {diff[0]}\n"
                      f"  전: {want[diff[0]]}\n  후: {got[diff[0]]}")


def test_snapshot_walks_every_branch_of_a_turn():
    """시나리오가 줄어 스냅숏이 아무것도 안 재게 되는 것을 막는다."""
    want = load_snapshot()

    cases = {v.get("case") for v in want.values()}
    assert {"N0", "U1", "T1", "T2", "T3", "D1", "G1", "G2", "G3", "G4", "G5", "G6",
            "S1", "S2", "I1", "I2", "unclassified"} <= cases, sorted(cases - {None})
    tags = {t for v in want.values() for t in v.get("tags", [])}
    assert {"G1:포맷", "G1:언어", "G1:길이", "G1:어조", "G2:조건", "G2:memory", "G2:모순",
            "G5:어긋남", "G5:안씀", "G6:계산", "G6:코드", "U3", "복합질문", "tool_numbers"} <= tags, sorted(tags)
    assert {"C1", "C2"} <= {f for v in want.values() for f in v.get("flags", [])}
    assert {"U2"} <= {e for v in want.values() for e in v.get("events", [])}
    assert {v.get("history_verified") for v in want.values()} >= {True, False}
    assert {v.get("request_verified") for v in want.values()} >= {True, False}
    # LLM 0회(I1 · 캐시) · 1회(관측 텍스트) · 2회(+주장) · 3회(+인용)
    assert {v.get("llm_calls") for v in want.values()} >= {0, 1, 2, 3}
    assert {v.get("grade") for v in want.values()} >= {0, 1, 2, 3, 4}
    stages = {v["error"].split("]")[0] + "]" for v in want.values() if "error" in v}
    assert stages == {"[observe]", "[sufficiency]", "[claims]"}
