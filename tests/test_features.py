"""기능 등록부. 지표가 진입점이 아니라 여기서 나오는지 본다."""

from dataclasses import dataclass
from typing import Any, Optional

import pytest

from ragdiag import features


@dataclass
class _Cls:
    primary_case: str


@dataclass
class _Result:
    classification: Optional[_Cls] = None
    error: Optional[str] = None


@dataclass
class _Turn:
    eval_result: str = "정상"


@dataclass
class _Sel:
    turn: _Turn


class _Selection:
    def __init__(self, results):
        self.selected = [_Sel(_Turn()) for _ in results]


class _Outcome:
    def __init__(self, results, n_failed=0, n_llm_calls=0):
        self.results, self.n_failed, self.n_llm_calls = results, n_failed, n_llm_calls


class _Backend:
    def __init__(self, fallbacks=()):
        self.fallbacks = list(fallbacks)


def _ctx(results, *, n_failed=0, n_llm_calls=0, fallbacks=()) -> Any:
    return features.RunContext(
        selection=_Selection(results),
        results=results,
        outcome=_Outcome(results, n_failed, n_llm_calls),
        backend=_Backend(fallbacks),
    )


def test_metrics_come_from_features_not_the_entry_point():
    results = [_Result(_Cls("case1")), _Result(_Cls("case2"))]
    metrics, notes = features.collect(_ctx(results, n_llm_calls=4))

    names = [name for name, _ in metrics if name]
    assert "classified" in names
    assert "llm calls" in names
    assert notes == []


def test_quiet_features_add_nothing():
    """낼 것이 없으면 빈 목록이다. 0 을 찍으면 실패한 것처럼 읽힌다."""
    results = [_Result(_Cls("case1"))]
    metrics, _ = features.collect(_ctx(results))
    assert not any(name == "filter FP" for name, _ in metrics)
    assert not any(name == "truncated" for name, _ in metrics)
    assert not any(name == "failed at" for name, _ in metrics)


def test_failures_are_counted_by_stage():
    """관측에서 몰려 깨지면 프롬프트 문제, 흩어지면 서버 문제 — 조치가 갈린다."""
    results = [_Result(None, "[관측] 터짐"), _Result(None, "[관측] 또"),
               _Result(_Cls("case1"))]
    metrics, notes = features.collect(_ctx(results, n_failed=2))
    assert any(name == "failed at" for name, _ in metrics)
    assert any("분류 실패" in n for n in notes)


def test_filter_false_positives_surface_with_a_note():
    """case0 은 챗봇 지표가 아니라 필터 지표다. 필터 쪽으로 돌아가는 피드백이다."""
    results = [_Result(_Cls("case0")), _Result(_Cls("case1"))]
    metrics, notes = features.collect(_ctx(results))
    assert any(name == "filter FP" for name, _ in metrics)
    assert any("필터" in n for n in notes)


def test_colliding_metric_names_raise_instead_of_printing_twice():
    """같은 이름이 두 줄로 나오면 어느 쪽을 옮겨 적어야 할지 모른다."""

    class Twin:
        NAME = "twin"

        @staticmethod
        def process_data(ctx):
            return [("classified", "겹친다")], []

    original = features.FEATURES
    features.FEATURES = (*original, Twin)
    try:
        with pytest.raises(KeyError, match="twin"):
            features.collect(_ctx([_Result(_Cls("case1"))]))
    finally:
        features.FEATURES = original


def test_every_feature_exposes_the_agreed_shape():
    for feature in features.FEATURES:
        assert isinstance(feature.NAME, str) and feature.NAME
        assert callable(feature.process_data)
