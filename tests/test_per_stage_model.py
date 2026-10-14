"""단계마다 다른 모델. ⑨ 근거 활용만 작은 모델로 내려 보는 것이 쓰는 자리다.

여기서 지키려는 것 셋이다.

    적은 단계만 바뀐다           나머지는 기본 모델 그대로
    나머지 단계의 캐시가 산다     한 단계 모델을 바꿔도 다시 사지 않는다
    출처가 파일에 남는다          "그 실행은 그 모델" 이 더는 성립하지 않으니까

실데이터를 가지고 나올 수 없는 환경이라, 판정의 출처가 결과 파일에 없으면
나중에 해석할 방법이 아예 없다. 세 번째가 테스트인 이유가 그것이다.
"""

import argparse

import pytest

from ragdiag.judge import STAGES, Judge
from ragdiag.schema import GroundingCheck
from tests.test_route import obs


class _Backend:
    """호출을 센다. 실제 모델 대신."""

    def __init__(self, model: str, base_url: str = "http://서버1:8000",
                 api_key: str = "키1"):
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.seen: list[str] = []
        self.fallbacks: list[str] = []

    def complete(self, system, user, out_model, contract_hint=""):
        self.seen.append(out_model.__name__)
        if out_model is GroundingCheck:
            return GroundingCheck(reasoning="", answer_used_rag="used"), None
        return obs(), None                   # 캐시를 거쳐도 다시 검증을 통과해야 한다

    def list_models(self):
        return [self.model]                  # 붙는다. 못 붙는 쪽은 e2e 로 본다

    def variant(self, *, model=None, base_url=None, api_key=None):
        # 실물처럼 안 준 것은 물려받는다. 모델을 비우면 그 서버가 알려준다고 가정한다.
        url = base_url or self.base_url
        return _Backend(model or f"{url} 의 첫 모델",
                        base_url=url, api_key=api_key or self.api_key)


def _case():
    from ragdiag.schema import Case

    return Case(
        case_id="c1:2", dept="인사팀", job_grade="대리", job_name="인사운영",
        conversation_id="c1", turn=2, pre_queries=["q1"],
        llm_ans_on_last_q="답변", current_query="q2", rag_chunks=["청크"],
    )


# ---------------------------------------------------------------------------
# 어느 백엔드로 가는가
# ---------------------------------------------------------------------------

def test_only_the_named_stage_changes_model():
    big, small = _Backend("큰모델"), _Backend("작은모델")
    judge = Judge(big, cache_dir=None, per_stage={"grounding": small})

    assert judge.backend_for("grounding") is small
    for stage in set(STAGES) - {"grounding"}:
        assert judge.backend_for(stage) is big


def test_the_call_actually_goes_to_the_stage_backend():
    big, small = _Backend("큰모델"), _Backend("작은모델")
    judge = Judge(big, cache_dir=None, per_stage={"grounding": small})

    judge.check_grounding(_case(), "q2")
    judge.observe(_case())

    assert small.seen == ["GroundingCheck"]
    assert big.seen == ["Observation"]


def test_unknown_stage_name_is_refused():
    """단계 이름을 틀리면 조용히 기본 모델로 돌아 버린다. 결과만 보면 알 수 없다."""
    with pytest.raises(ValueError) as e:
        Judge(_Backend("큰모델"), cache_dir=None,
              per_stage={"grouding": _Backend("작은모델")})
    assert "grouding" in str(e.value)
    assert "grounding" in str(e.value)       # 가능한 이름을 알려준다


def test_all_backends_dedupes_and_keeps_the_default_first():
    big, small = _Backend("큰모델"), _Backend("작은모델")
    judge = Judge(big, cache_dir=None,
                  per_stage={"grounding": small, "legibility": big})
    assert judge.all_backends() == [big, small]


# ---------------------------------------------------------------------------
# 캐시 — 이게 깨지면 실험 한 번에 전 단계를 다시 산다
# ---------------------------------------------------------------------------

def test_swapping_one_stage_keeps_the_other_stages_cache(tmp_path):
    big = _Backend("큰모델")
    first = Judge(big, cache_dir=tmp_path)
    first.observe(_case())
    first.check_grounding(_case(), "q2")
    assert big.seen == ["Observation", "GroundingCheck"]

    # ⑨ 만 다른 모델로. ⑤ 는 캐시 적중이어야 한다.
    small = _Backend("작은모델")
    second = Judge(_Backend("큰모델"), cache_dir=tmp_path,
                   per_stage={"grounding": small})
    second.observe(_case())
    second.check_grounding(_case(), "q2")

    assert second.backend_for("observe").seen == []      # 캐시에서 나왔다
    assert small.seen == ["GroundingCheck"]              # 모델이 바뀌어 다시 샀다


def test_the_cache_is_not_shared_between_two_models_on_one_stage(tmp_path):
    """같은 단계 · 같은 입력이라도 모델이 다르면 다른 판정이다. 섞이면 측정이 무의미하다."""
    a = Judge(_Backend("모델A"), cache_dir=tmp_path)
    b = Judge(_Backend("모델B"), cache_dir=tmp_path)
    assert (a._cache_path("grounding", "sys", "usr")
            != b._cache_path("grounding", "sys", "usr"))


# ---------------------------------------------------------------------------
# 출처가 남는가
# ---------------------------------------------------------------------------

def test_models_names_every_stage():
    judge = Judge(_Backend("큰모델"), cache_dir=None,
                  per_stage={"grounding": _Backend("작은모델")})
    assert judge.models() == {
        "observe": "큰모델", "sufficiency": "큰모델",
        "legibility": "큰모델", "grounding": "작은모델",
    }


def test_result_file_records_which_model_judged_each_stage():
    from ragdiag.output import build_output
    from tests.test_output import _pairs

    models = Judge(_Backend("큰모델"), cache_dir=None,
                   per_stage={"grounding": _Backend("작은모델")}).models()
    out = build_output(_pairs(), models)
    assert out["judged_by"]["grounding"] == "작은모델"
    assert out["judged_by"]["observe"] == "큰모델"


def test_the_shape_is_unchanged_when_every_stage_shares_one_model():
    """기본 경로는 건드리지 않는다. 모델 칸이 늘 생기면 전달본 쪽이 먼저 깨진다."""
    from ragdiag.output import build_output
    from tests.test_output import _pairs

    assert list(build_output(_pairs())) == ["analysis_results"]


def test_fallback_report_sees_every_backend():
    """백엔드 하나만 보면 절반을 놓친다. --thinking off 를 어디에 걸지 알 수 없다."""
    from ragdiag.features import llm_fallback

    big, small = _Backend("큰모델"), _Backend("작은모델")
    big.fallbacks = ["max_tokens 2배"]
    small.fallbacks = ["thinking off"]

    ctx = argparse.Namespace(backends=[big, small])
    metrics, notes = llm_fallback.process_data(ctx)

    joined = " ".join(text for _, text in metrics)
    assert "큰모델" in joined and "작은모델" in joined
    assert "2건" in notes[0]


def test_one_backend_keeps_the_label_plain():
    """모델이 하나면 모델 이름을 붙이지 않는다 - 읽을 사람에게 새 정보가 없다."""
    from ragdiag.features import llm_fallback

    only = _Backend("큰모델")
    only.fallbacks = ["thinking off", "thinking off"]
    metrics, _ = llm_fallback.process_data(argparse.Namespace(backends=[only]))
    assert metrics == [("llm_fallback", "2 recovered by thinking off")]


# ---------------------------------------------------------------------------
# 무엇을 적었을 때 백엔드가 생기나
# ---------------------------------------------------------------------------

def _args(**kw):
    """단계별 인자 전부 None 인 Namespace. 적은 것만 덮어쓴다."""
    blank = {}
    for stage in STAGES:
        blank[f"model_{stage}"] = None
        blank[f"base_url_{stage}"] = None
        blank[f"api_key_{stage}"] = None
    blank.update(kw)
    return argparse.Namespace(**blank)


def _pick(args, config=None, default=None):
    from ragdiag.__main__ import per_stage_backends
    from ragdiag.config import Config

    return per_stage_backends(args, config or Config(), default or _Backend("큰모델"))


def test_no_flag_means_no_extra_backend():
    assert _pick(_args()) == {}


def test_naming_the_same_model_makes_no_second_backend():
    """같은 모델이면 백엔드를 또 만들 이유가 없다 - negotiate 프로브만 한 번 더 산다."""
    assert _pick(_args(model_grounding="큰모델")) == {}


def test_the_model_flag_builds_a_sibling_on_the_same_server():
    picked = _pick(_args(model_grounding="작은모델"))
    assert list(picked) == ["grounding"]
    assert picked["grounding"].model == "작은모델"
    assert picked["grounding"].base_url == "http://서버1:8000"   # 주소는 물려받는다


def test_an_address_alone_is_enough():
    """모델이 서버마다 따로 떠 있는 경우. 이름을 또 적지 않아도 그 서버가 알려준다."""
    picked = _pick(_args(base_url_grounding="http://서버2:8000"))
    assert picked["grounding"].base_url == "http://서버2:8000"
    assert picked["grounding"].model == "http://서버2:8000 의 첫 모델"


def test_an_address_and_a_model_together():
    picked = _pick(_args(base_url_grounding="http://서버2:8000",
                         model_grounding="작은모델"))
    assert picked["grounding"].base_url == "http://서버2:8000"
    assert picked["grounding"].model == "작은모델"


def test_the_key_is_inherited_unless_given():
    plain = _pick(_args(base_url_grounding="http://서버2:8000"))
    assert plain["grounding"].api_key == "키1"

    own = _pick(_args(base_url_grounding="http://서버2:8000",
                      api_key_grounding="키2"))
    assert own["grounding"].api_key == "키2"


def test_the_same_model_on_a_different_key_still_gets_its_own_backend():
    """키만 다른 배포가 있을 수 있다. 모델 이름이 같다고 접어 버리면 그 설정이 사라진다."""
    picked = _pick(_args(api_key_grounding="키2"))
    assert picked["grounding"].api_key == "키2"


def test_only_the_named_stage_gets_a_backend():
    picked = _pick(_args(model_grounding="작은모델",
                         base_url_legibility="http://서버2:8000"))
    assert sorted(picked) == ["grounding", "legibility"]


def test_config_can_name_the_stage_model_and_address():
    from ragdiag.config import Config

    config = Config(values={"llm.model_grounding": "작은모델",
                            "llm.url_grounding": "http://서버2:8000"})
    picked = _pick(_args(), config)
    assert picked["grounding"].model == "작은모델"
    assert picked["grounding"].base_url == "http://서버2:8000"


@pytest.mark.parametrize("flag,key,setting", [
    ("model_grounding", "llm.model_grounding", "설정모델"),
    ("base_url_grounding", "llm.url_grounding", "http://설정서버:8000"),
])
def test_the_flag_beats_the_config(flag, key, setting):
    from ragdiag.config import Config

    picked = _pick(_args(**{flag: "플래그값"}), Config(values={key: setting}))
    got = picked["grounding"]
    assert "플래그값" in (got.model, got.base_url)
    assert setting not in (got.model, got.base_url)


def test_an_injected_backend_that_cannot_clone_says_so():
    """tools/dev_run.py 로 넣은 백엔드는 OpenAI 호환 서버라는 전제가 없다."""
    from ragdiag.backends import JudgeError

    class _NoClone:
        model = "주입된모델"

    with pytest.raises(JudgeError) as e:
        _pick(_args(model_grounding="작은모델"), None, _NoClone())
    assert "--model-grounding" in str(e.value)
    assert "--backend local" in str(e.value)


def _run(tmp_path, *flags):
    """스텁 서버 하나를 띄우고 진입점을 끝까지 돌린다. (proc, 결과 payload)."""
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from stub_llm import StubLLM

    from ragdiag.fixtures.synth import generate

    root = Path(__file__).resolve().parents[1]
    log = tmp_path / "conv_eval.json"
    log.write_text(json.dumps(generate(n=2, seed=0), ensure_ascii=False),
                   encoding="utf-8")
    out = tmp_path / "outputs"

    with StubLLM() as stub:
        env = dict(os.environ, LLM_API_URL=stub.url, LLM_API_KEY="stub")
        proc = subprocess.run(
            [sys.executable, str(root / "src" / "run.py"), "--backend", "local",
             "--no-cache", "--no-progress", "--conv-data", str(log),
             "--output-dir", str(out), *flags],
            capture_output=True, text=True, env=env, cwd=tmp_path)

    written = sorted(out.glob("*.json"))
    payload = json.loads(written[-1].read_text(encoding="utf-8")) if written else {}
    return proc, payload


def test_the_whole_run_records_the_stage_model_in_the_result_file(tmp_path):
    """끝까지 돌려서 본다. 플래그가 Judge 까지 가도 결과 파일에 안 남으면 의미가 없다."""
    proc, payload = _run(tmp_path, "--model-grounding", "작은모델")

    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "model · grounding" in proc.stdout        # RUN SUMMARY 의 metrics
    assert "판정 · grounding" in proc.stderr          # 실행 조건 블록
    assert payload["judged_by"]["grounding"] == "작은모델"
    assert payload["judged_by"]["observe"] == "stub-model"


def test_a_stage_address_that_is_not_there_stops_before_judging(tmp_path):
    """주소를 막아 놓고 본다. 두 가지를 한 번에 증명한다.

    하나는 **그 주소로 실제로 간다**는 것 - 모델 이름을 안 줬으므로 그 서버의
    /v1/models 를 물어보고, 그래서 닫힌 포트가 메시지에 그대로 나온다.
    또 하나는 **시작 전에 죽는다**는 것 - 30분 돌린 뒤 grounding 턴이 전부 실패한
    것을 발견하는 쪽보다 낫다. 종료 코드 2 는 "사람이 고쳐야 한다" 다.
    """
    proc, _ = _run(tmp_path, "--base-url-grounding", "http://127.0.0.1:1")

    assert proc.returncode == 2, proc.stdout
    assert "127.0.0.1:1" in proc.stderr, proc.stderr
    assert "FAILED (백엔드)" in proc.stdout


def test_naming_the_model_does_not_let_a_bad_address_through(tmp_path):
    """모델 이름을 주면 생성자가 서버에 안 묻는다. 그래서 따로 확인한다.

    안 하면 턴마다 ⑤ ⑦ 를 다 사고 나서 이 단계만 전부 실패한다 - 사이클 하나를 버린다.
    """
    proc, _ = _run(tmp_path, "--base-url-grounding", "http://127.0.0.1:1",
                   "--model-grounding", "작은모델")

    assert proc.returncode == 2, proc.stdout
    assert "grounding 단계" in proc.stderr, proc.stderr
    assert "--base-url-grounding" in proc.stderr, proc.stderr


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("kind", ["model", "base-url", "api-key"])
def test_every_stage_has_every_flag(stage, kind, capsys):
    """단계를 늘리면 플래그도 같이 늘어야 한다. 빠뜨리면 그 단계만 조용히 못 바꾼다.

    값을 안 주고 불러서 argparse 가 무슨 말을 하는지로 본다 - 모르는 플래그면
    unrecognized, 아는 플래그면 값이 없다고 한다. 둘 다 2 로 죽어서 종료 코드로는
    구분이 안 된다.
    """
    from ragdiag.__main__ import main

    with pytest.raises(SystemExit) as e:
        main([f"--{kind}-{stage}"])
    assert e.value.code == 2
    assert "unrecognized" not in capsys.readouterr().err
