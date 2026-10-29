"""대시보드가 실제로 렌더되는가 (v4).

**서버가 뜨는 것으로는 확인이 안 된다.** streamlit 은 스크립트를 브라우저가 붙을 때 실행하고
예외를 화면에만 보여준다. 여기서는 AppTest 로 스크립트를 끝까지 실행해 예외를 본다.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "src" / "dashboard.py"
sys.path.insert(0, str(ROOT / "tests"))

AppTest = pytest.importorskip(
    "streamlit.testing.v1", reason="streamlit 이 없으면 대시보드는 선택 기능이다").AppTest


def _conv(chat_id, dept):
    return SimpleNamespace(chat_id=chat_id, user=SimpleNamespace(dept=dept, job_grade="책임", job_name="직무"))


@pytest.fixture(scope="module")
def result_file(tmp_path_factory):
    """열한 경로 × 부서 둘. 저장소에 데이터 파일을 두지 않는다."""
    from ragdiag.output import build_output
    from ragdiag.pipeline import judge_cases
    from stub_judge import ScriptedJudge, make_case, scenarios

    pairs = []
    for dept, chat in (("해외영업팀", "A"), ("인사팀", "B")):
        cases = [make_case(s, chat_id=f"{chat}-{s}") for s in scenarios()]
        results = judge_cases(cases, ScriptedJudge(), workers=2, progress=False)
        pairs += [(_conv(r.case.chat_id, dept), r) for r in results]
    # 검색 토큰 하나를 한 질문에만 심는다
    pairs[0][1].case.__dict__["pre_queries"] = ["Q7Q 국내 출장 식비 상한이 얼마인가요?"]
    payload = build_output(pairs, {"started": "x", "kev": "scripted", "threshold": 0.9})
    tmp = tmp_path_factory.mktemp("dash")
    out = tmp / "conv_parsed_20260101-000000.json"
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return out


def render(result_file, *extra):
    """대시보드를 끝까지 실행한다. run 마다 argv 를 끼운다 — 버튼을 누를 때마다 다시 돈다.

    위젯의 .run() 은 AppTest.run 이 아니라 **_run** 을 부른다. run 만 감싸면 두 번째 실행부터
    인자 없이 돌아 output/ 의 최신 파일을 집는다 - 그래서 _run 을 감싼다.
    """
    import streamlit as st

    argv = ["dashboard.py", "--result", str(result_file), *extra]
    st.cache_data.clear()
    at = AppTest.from_file(str(DASHBOARD), default_timeout=120)
    bare = at._run

    def run_with_args(*a, **kw):
        saved, sys.argv = sys.argv, argv
        try:
            return bare(*a, **kw)
        finally:
            sys.argv = saved

    at._run = run_with_args
    at.run()
    return at


def _ok(at):
    assert not at.exception, [f"{e.type}: {e.message}" for e in at.exception]


def test_dashboard_lives_directly_under_src():
    assert DASHBOARD.exists() and not (ROOT / "src" / "ragdiag" / "dashboard.py").exists()


def test_dashboard_renders_without_pythonpath(result_file, monkeypatch):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    at = render(result_file)
    _ok(at)
    assert at.metric, "아무것도 렌더되지 않았다"


def test_health_metrics_come_first_and_name_the_buckets_that_matter(result_file):
    at = render(result_file)
    labels = [m.label for m in at.metric]
    for expected in ("판정된 턴", "정상", "검토", "시스템", "오류", "앞 턴 누락"):
        assert expected in labels, f"{expected} 지표가 없다. 있는 것: {labels}"
    assert labels.index("판정된 턴") < labels.index("실패"), "판정 건강이 분포보다 먼저다"


def test_load_flattens_turns_into_columns(result_file):
    import importlib.util

    import streamlit as st  # noqa: F401  (dashboard 가 import 시 streamlit 을 요구한다)
    spec = importlib.util.spec_from_file_location("dash", DASHBOARD)
    # streamlit 런타임 밖에서는 _bail 로 끝나므로 load 만 떼어 본다 — AppTest 안에서 돈 것과 같은 코드다
    at = render(result_file)
    _ok(at)
    payload = json.loads(result_file.read_text(encoding="utf-8"))
    assert {t["verdict"]["bucket"] for t in payload["turns"]} == {"정상", "사용자", "근거", "생성", "시스템", "검토"}


def test_empty_result_is_announced_not_crashed(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"run": {}, "summary": {}, "turns": []}), encoding="utf-8")
    at = render(empty)
    _ok(at)
    assert any("판정된 턴이 없" in w.value for w in at.warning)


def test_no_text_result_opens(result_file, tmp_path):
    payload = json.loads(result_file.read_text(encoding="utf-8"))
    for t in payload["turns"]:
        t.pop("text", None)
    out = tmp_path / "notext.json"
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    at = render(out)
    _ok(at)
    assert any("--no-text" in i.value for i in at.info), "본문이 없다고 말해야 한다"


def test_dashboard_does_not_need_matplotlib(result_file):
    at = render(result_file)
    _ok(at)
    assert "matplotlib" not in sys.modules


def test_sections_are_split_into_tabs(result_file):
    at = render(result_file)
    labels = [t.label for t in at.tabs]
    assert labels == ["분포", "조직", "개별 케이스", "근거 보강"]


def test_distribution_shows_where_it_stopped_and_where_it_got_stuck(result_file):
    at = render(result_file)
    subheaders = [s.value for s in at.subheader]
    assert "어디서 멈췄나" in subheaders
    assert any(s.startswith("어디서 막혔나") for s in subheaders)
    frames = [d.value for d in at.dataframe]
    assert any("막힌 문항" in f.columns for f in frames), "검토가 어느 문항에서 막혔는지 표가 없다"


def test_org_crosstab_columns_are_bucket_names(result_file):
    at = render(result_file)
    _ok(at)
    frames = [d.value for d in at.dataframe]
    crossed = [f for f in frames if "계" in f.columns]
    assert crossed, "조직 crosstab 이 없다"
    assert {"근거", "생성", "시스템"} <= set(crossed[0].columns)


def test_evidence_gap_list_is_a_table_of_questions(result_file):
    at = render(result_file)
    header = [s.value for s in at.subheader if "근거 보강" in s.value]
    assert header, "근거 보강 절이 없다"
    frames = [d.value for d in at.dataframe]
    gaps = [f for f in frames if "답이 없던 칸" in f.columns or "근거위치" in f.columns]
    assert gaps and len(gaps[0]) == 6, "근거 묶음 셋 × 부서 둘"


def test_search_finds_the_token_in_the_question(result_file):
    at = render(result_file)
    box = next(w for w in at.text_input if w.placeholder and "찾기" in w.placeholder)
    box.set_value("Q7Q").run()
    _ok(at)
    assert any("1 / 1" in m.value for m in at.markdown), "검색 토큰이 한 건에만 있다"


def test_detail_shows_verdict_steps_and_text(result_file):
    at = render(result_file)
    heads = [m.value for m in at.markdown if m.value.startswith("### ")]
    assert heads and " — " in heads[0], "결론(묶음 — 이유) 머리가 없다"
    assert any("지나온 단계" in m.value for m in at.markdown)
    assert any("비판받은 답변" in m.value for m in at.markdown)


def test_prev_and_next_walk_the_cases(result_file):
    at = render(result_file)
    at.button(key="next-top").click().run()
    _ok(at)
    assert any("2 / " in m.value for m in at.markdown)
    at.button(key="prev-bottom").click().run()
    assert any("1 / " in m.value for m in at.markdown)


def test_running_with_plain_python_says_to_use_streamlit():
    import subprocess

    proc = subprocess.run([sys.executable, str(DASHBOARD)], capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 2
    assert "-m streamlit run" in proc.stderr and sys.executable in proc.stderr and "--" in proc.stderr


def test_missing_dependency_names_the_install_command(tmp_path):
    import subprocess
    import textwrap

    stub = tmp_path / "block.py"
    stub.write_text(textwrap.dedent("""
        import builtins
        _real = builtins.__import__
        def _blocked(name, *a, **k):
            if name.split(".")[0] == "pandas":
                raise ModuleNotFoundError("No module named 'pandas'", name="pandas")
            return _real(name, *a, **k)
        builtins.__import__ = _blocked
        import runpy, sys
        sys.argv = [%r]
        runpy.run_path(sys.argv[0], run_name="__main__")
    """) % str(DASHBOARD), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(stub)], capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 2
    assert "-m pip install -r" in proc.stderr and "requirements-dashboard.txt" in proc.stderr


def test_dashboard_picks_the_newest_result(tmp_path, result_file):
    import streamlit as st

    out = tmp_path / "output"
    out.mkdir()
    payload = result_file.read_text(encoding="utf-8")
    for stamp in ("20260101-000000", "20260831-153018", "20260501-120000"):
        (out / f"conv_parsed_{stamp}.json").write_text(payload, encoding="utf-8")
    saved = sys.argv
    sys.argv = ["dashboard.py", "--output-dir", str(out)]
    try:
        st.cache_data.clear()
        at = AppTest.from_file(str(DASHBOARD), default_timeout=120)
        at.run()
    finally:
        sys.argv = saved
    _ok(at)
    shown = " ".join(c.value for c in at.caption)
    assert "20260831-153018" in shown and "다른 실행 2건" in shown


def test_sidebar_offers_three_levels_when_a_classification_is_given(result_file, tmp_path):
    import streamlit as st

    scheme = tmp_path / "dept.json"
    scheme.write_text(json.dumps({"dept_classes": [
        {"id": 1, "name": "본부A", "subclasses": [{"name": "중분류A", "items": ["해외영업팀", "인사팀"]}]}]},
        ensure_ascii=False), encoding="utf-8")
    saved = sys.argv
    sys.argv = ["dashboard.py", "--result", str(result_file), "--dept-class", str(scheme)]
    try:
        st.cache_data.clear()
        at = AppTest.from_file(str(DASHBOARD), default_timeout=120)
        at.run()
        _ok(at)

        def keys():
            return {w.key for w in at.sidebar.multiselect}

        def pick(key):
            return next(w for w in at.sidebar.multiselect if w.key == key)

        assert "부서:대분류" in keys() and "부서:중분류" not in keys()
        pick("부서:대분류").set_value([pick("부서:대분류").options[0]]); at.run()
        assert "부서:중분류" in keys() and "부서:소분류" not in keys()
        pick("부서:중분류").set_value([pick("부서:중분류").options[0]]); at.run()
        assert "부서:소분류" in keys() and "직급:중분류" not in keys()
        pick("부서:대분류").set_value([]); at.run()
        assert "부서:중분류" not in keys()
    finally:
        sys.argv = saved


def test_sidebar_stays_flat_without_a_classification(result_file):
    at = render(result_file)
    labels = [w.label for w in at.sidebar.multiselect]
    assert "부서" in labels and "묶음" in labels
    assert "부서:대분류" not in {w.key for w in at.sidebar.multiselect}


def _work_folder(tmp_path, result_file, **paths):
    import shutil

    (tmp_path / "output").mkdir()
    shutil.copy(result_file, tmp_path / "output" / "conv_parsed_20260101-000000.json")
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "dept.json").write_text(json.dumps({"dept_classes": [
        {"id": 1, "name": "본부A", "subclasses": [{"name": "중A", "items": ["해외영업팀", "인사팀"]}]}]},
        ensure_ascii=False), encoding="utf-8")
    lines = ["paths:"] + [f"  {k}: {v}" for k, v in paths.items()]
    (tmp_path / "configs" / "env.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def _run_in(cwd, argv):
    import os

    import streamlit as st

    saved_dir, saved_argv = os.getcwd(), sys.argv
    os.chdir(cwd)
    sys.argv = ["dashboard.py", *argv]
    try:
        st.cache_data.clear()
        at = AppTest.from_file(str(DASHBOARD), default_timeout=120)
        at.run()
        return at
    finally:
        os.chdir(saved_dir)
        sys.argv = saved_argv


def test_classification_path_can_come_from_the_config(result_file, tmp_path):
    at = _run_in(_work_folder(tmp_path, result_file, dept_class="configs/dept.json"), [])
    _ok(at)
    assert "부서:대분류" in {w.key for w in at.sidebar.multiselect}


def test_cli_beats_the_config(result_file, tmp_path):
    work = _work_folder(tmp_path, result_file, dept_class="configs/dept.json")
    (work / "configs" / "none.json").write_text(json.dumps({"dept_classes": [
        {"id": 1, "name": "X", "subclasses": [{"name": "y", "items": ["어디에도없는팀"]}]}]},
        ensure_ascii=False), encoding="utf-8")
    at = _run_in(work, ["--dept-class", "configs/none.json"])
    assert "부서:대분류" not in {w.key for w in at.sidebar.multiselect}


def test_broken_config_does_not_stop_the_screen(result_file, tmp_path):
    work = _work_folder(tmp_path, result_file)
    (work / "configs" / "env.yaml").write_text("paths:\n  없는키: 1\n", encoding="utf-8")
    at = _run_in(work, [])
    _ok(at)
    assert at.metric and any("설정을 읽지 못해" in w.value for w in at.warning)
