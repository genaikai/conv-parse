"""낙오자 — 한 턴이 안 오면 그 단계가 못 끝나고 다음 단계가 통째로 기다렸다.

HTTP 타임아웃(기본 600초)은 예산이 아니라 사실상 무한 대기다. 그 단계에서 끝난 턴들의
중앙값을 기준으로 삼아, 몇 배를 넘겨도 안 오는 턴은 에러로 닫고 넘어간다.
"""

import time
from types import SimpleNamespace

import pytest

from ragdiag import settings
from ragdiag.features._shared import each_turn, straggler_limit


@pytest.fixture
def quick_cutoff(monkeypatch):
    monkeypatch.setattr(settings, "STRAGGLER_FACTOR", 4.0)
    monkeypatch.setattr(settings, "STRAGGLER_MIN_SEC", 0.3)


def _turns(n):
    return [SimpleNamespace(error=None, idx=i, seen=False) for i in range(n)]


def _ctx(turns, workers=4):
    return SimpleNamespace(turns=turns, workers=workers, progress=False,
                           open_turns=lambda: turns)


def test_limit_needs_half_of_the_stage_done_and_scales_with_the_median(quick_cutoff):
    assert straggler_limit([], 20) is None
    assert straggler_limit([0.1] * 7, 20) is None                # 8건 미만
    assert straggler_limit([0.1] * 8, 20) is None                # 절반 미만
    assert straggler_limit([0.1] * 10, 20) == pytest.approx(0.4)  # 4 × 중앙값 (최소 0.3 보다 큼)
    assert straggler_limit([0.01] * 10, 20) == pytest.approx(0.3)  # 최소 초가 이긴다


def test_disabled_when_factor_is_zero(monkeypatch):
    monkeypatch.setattr(settings, "STRAGGLER_FACTOR", 0)
    assert straggler_limit([0.1] * 50, 50) is None


def test_a_stuck_turn_is_closed_and_the_stage_moves_on(quick_cutoff):
    turns = _turns(12)

    def fn(turn):
        if turn.idx == 5:
            time.sleep(3.0)                       # 붙잡힌 턴
        else:
            time.sleep(0.05)
        turn.seen = True

    t0 = time.monotonic()
    each_turn(_ctx(turns), "observe", fn, parallel=True)
    took = time.monotonic() - t0

    assert took < 2.0, f"낙오자를 기다렸다: {took:.1f}s"
    stuck = turns[5]
    assert stuck.error and stuck.error.startswith("[observe] 낙오"), stuck.error
    assert "재실행" in stuck.error
    assert all(t.error is None and t.seen for t in turns if t.idx != 5)


def test_a_late_reply_does_not_reopen_or_overwrite_the_abandoned_turn(quick_cutoff):
    turns = _turns(12)

    def fn(turn):
        if turn.idx == 3:
            time.sleep(2.5)                       # 낙오 판정(~1.2초) 뒤에 온다
            raise RuntimeError("늦게 와서 터짐")
        time.sleep(0.05)

    each_turn(_ctx(turns), "observe", fn, parallel=True)
    assert turns[3].error.startswith("[observe] 낙오")
    time.sleep(2.0)                                # 늦은 응답이 도착한 뒤에도
    assert turns[3].error.startswith("[observe] 낙오"), turns[3].error


def test_small_stages_never_abandon(quick_cutoff):
    """중앙값이 설 만큼 끝난 턴이 없으면 판단하지 않는다 - 그때는 HTTP 타임아웃이 지킨다."""
    turns = _turns(3)

    def fn(turn):
        time.sleep(0.6 if turn.idx == 0 else 0.01)

    each_turn(_ctx(turns), "observe", fn, parallel=True)
    assert all(t.error is None for t in turns)


def test_progress_line_counts_abandoned_separately():
    import io

    from ragdiag.progress import Progress

    out = io.StringIO()
    bar = Progress("observe", 3, stream=out)
    bar.done(); bar.done(ok=False); bar.abandon(); bar.finish()
    assert "(실패 1 · 포기 1)" in out.getvalue()
    bar.done()                                     # 낙오 턴의 늦은 응답 - 100% 를 넘기지 않는다
    assert bar.n == 3
