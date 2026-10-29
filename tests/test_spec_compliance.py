"""구현 규격(IMPLEMENTATION_SPEC.md)을 코드로 지킨다.

규격의 규칙은 전부 제약에서 따라나온 것이고, 어긋나면 실행 환경 사이클 하나를 버린다.
문서로만 두면 다음에 파일 하나 추가하면서 조용히 깨진다.

여기서 재는 것:
  C6  가짜 데이터가 파일로 저장소에 있으면 사본을 통해 실행 환경으로 흘러간다
  C3  합성 데이터가 실데이터의 값을 흉내내면 그것도 유출 경로다
  1.3 바뀔 만한 값이 설정에 없으면 실행 환경에서 "코드 한 줄만" 이 된다
  3.2 계약 위반 메시지가 옮겨 적을 수 없으면 포맷 회수가 끊긴다
"""

import os
import pathlib
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

DATA_SUFFIXES = (".csv", ".tsv", ".parquet", ".xlsx", ".pkl", ".npy", ".npz",
                 ".h5", ".feather", ".sqlite", ".sqlite3", ".jsonl")


def tracked() -> list[str]:
    proc = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip("git 저장소가 아님")
    return proc.stdout.splitlines()


# ---------------------------------------------------------------------------
# C6 · 2.3 — 데이터가 저장소에 없다
# ---------------------------------------------------------------------------

def test_no_data_files_are_tracked():
    """규격 2.3 의 점검 명령을 그대로 돌린다."""
    bad = [f for f in tracked()
           if f.endswith(DATA_SUFFIXES) or f.startswith(".staging")]
    assert not bad, (
        "데이터성 파일이 추적되고 있다. 이식하면 운영 저장소로 넘어간다:\n"
        + "\n".join(f"  {f}" for f in bad))


# 규격 1.2 의 예외. **이름을 하나씩 적는다** - 패턴으로 열면 다음 사람이 거기에
# 아무 데이터나 놓는다.
#
# 요구 확인기(ragdiag/requests.py)를 재는 외부 한국어 벤치마크 두 벌이다. 우리가 만든
# 가짜 데이터가 아니라 공개 데이터셋이고(둘 다 Apache-2.0), 파이프라인은 읽지 않는다 -
# 테스트만 읽는다. 규격이 막으려는 것은 사내 로그가 섞인 픽스처가 운영으로 흘러가는
# 것인데 이건 그 부류가 아니다.
#
# 반대로 **함께 다녀야 한다.** 실행 환경은 에어갭이라 내려받을 수 없고, 없으면
# tests/test_requests.py 의 외부 데이터 시험이 조용히 건너뛴다 - 무엇을 안 쟀는지가
# 화면에서 사라진다. 갱신은 scripts/fetch-eval-data.sh.
EVAL_DATA = {
    "tests/data/ifeval_ko.json",           # 검증 342건 (allganize/IFEval-Ko)
    "tests/data/ifeval_ko_heldout.json",   # 검증 524건 (multi-ifeval ko)
    "tests/data/ifeval_ko_dk.json",        # 검증 464건 (davidkim205/ko-ifeval)
    "tests/data/ifeval_ko_snu.json",       # 테스트 841건 (SNU_Ko-IFEval, 홀수 절반만 씀)
}


def test_no_json_fixtures_are_tracked():
    """가짜 데이터는 파일이 아니라 코드다 (규격 1.2).

    .gitignore 는 `git add -f` 한 번에 뚫린다. 없는 파일은 올라갈 수 없다.
    예외는 EVAL_DATA 에 이름으로 적힌 것뿐이다.
    """
    bad = [f for f in tracked()
           if f.endswith(".json") and "package.json" not in f and f not in EVAL_DATA]
    assert not bad, (
        "JSON 데이터가 추적되고 있다:\n" + "\n".join(f"  {f}" for f in bad))


def test_the_eval_data_exemption_is_not_a_hiding_place():
    """예외로 적힌 파일이 실제로 그 벤치마크인지 확인한다.

    이름만 맞으면 통과하는 예외는 예외가 아니라 구멍이다. 두 파일이 IFEval 라벨
    구조를 그대로 갖고 있고 크기가 예상 범위인지 본다.
    """
    import json

    for name in sorted(EVAL_DATA):
        path = ROOT / name
        if not path.exists():
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        assert 300 <= len(rows) <= 900, f"{name} 크기가 예상 밖이다: {len(rows)}"
        assert all(set(r) == {"key", "prompt", "instruction_id_list"} for r in rows), (
            f"{name} 에 IFEval 라벨 구조가 아닌 행이 있다")


def test_local_config_is_not_tracked():
    """운영 실값이 밖으로 나가면 안 된다."""
    bad = [f for f in tracked() if "env.yaml" in f or f.endswith(".env")]
    assert not bad, f"운영 설정이 추적되고 있다: {bad}"


def test_synth_generates_at_runtime_not_from_a_file():
    """합성 데이터가 파일을 읽지 않아야 한다."""
    source = (ROOT / "src/ragdiag/fixtures/synth.py").read_text(encoding="utf-8")
    for banned in ("open(", "read_text", "json.load(", "Path("):
        assert banned not in source, (
            f"synth.py 가 {banned} 을 쓴다. 파일에서 읽으면 그 파일이 "
            "저장소에 있어야 하고, 그러면 실행 환경으로 흘러간다.")


def test_synth_is_deterministic():
    from ragdiag.fixtures.synth import generate

    assert generate(seed=0) == generate(seed=0)
    assert generate(seed=0) != generate(seed=1)


def test_synth_default_stays_small_enough_for_a_smoke_run():
    """`--dry-run` 이 이걸 쓴다. 기본을 키우면 실행 환경의 첫 점검이 수백 번의
    LLM 호출로 바뀌고, 거기서는 그 비용을 되돌릴 방법이 없다.
    """
    from ragdiag.fixtures.synth import generate

    payload = generate(seed=0)
    turns = payload["metadata"]["total_turns"]
    assert turns < 500, (
        f"기본 합성 데이터가 {turns}턴이다. 규모는 cases= 로 키운다 - "
        "기본값은 스모크가 감당할 크기여야 한다.")


def test_synth_scales_without_losing_the_planted_signal():
    """규모를 키워도 부서 편중이 남아야 한다.

    화면에서 읽어낼 것이 있으려면 분포가 고르면 안 된다. 규모를 키우는 코드가
    성향을 평평하게 만들면 500건짜리 화면이 7건짜리보다 오히려 말을 덜 한다.
    """
    from ragdiag.fixtures.synth import generate

    big = generate(seed=0, cases=500)
    turns = big["metadata"]["total_turns"]
    assert turns > 500, f"cases=500 인데 {turns}턴뿐이다"

    # 해외영업팀에 검색 실패를 몰아 두었다. 그 부서의 질문에는 해외 규정 문서가
    # 붙고, 그 문서에는 답이 없다 - 그게 코퍼스 보강 화면이 세는 신호다.
    def questions(dept):
        return [t["user_question"] for u in big["users"] if u["db_dept_name"] == dept
                for c in u["conversations"] for t in c["turns"]]

    oversea = sum("해외" in q or "유럽" in q or "미주" in q for q in questions("해외영업팀"))
    control = sum("해외" in q or "유럽" in q or "미주" in q for q in questions("인사팀"))
    assert oversea > control * 2, (
        f"해외영업팀 {oversea}건 vs 인사팀 {control}건 - 편중이 사라졌다")


def test_synth_output_satisfies_the_contract():
    """계약이 바뀌면 합성 데이터도 따라 바뀌어야 한다.

    어긋나면 여기서는 도는 코드가 실행 환경에서 죽는다.
    """
    from ragdiag.contracts import check_log
    from ragdiag.fixtures.synth import generate

    report = check_log(generate(seed=0))
    assert report.ok, "\n".join(m.line() for m in report.mismatches)


def test_run_summary_lines_fit_eighty_columns():
    """옮겨 적는 사람 기준이다. 칸 수로 자르지 않으면 한글이 중간에서 끊긴다.

    실제로 `max_tokens=24,000(설정 ` 처럼 끊긴 줄이 나왔다. 반출이 안 되는 환경에서
    RUN SUMMARY 는 유일한 회수 채널인데, 중간에서 끊긴 줄은 옮겨 적을 수 없다.
    """
    from ragdiag.summary import Conditions, RunSummary, display_width

    cond = Conditions()
    cond.add("설정", "configs/env.yaml", note="4개 값을 덮어씀")
    cond.add("백엔드", "local", "설정 llm.backend")
    cond.add("주소", "http://some-rather-long-internal-host.example:8000", "환경변수 LLM_API_URL")
    cond.add("모델", "qwen3.5-397b-a17b-instruct-2507", "설정 llm.model")
    cond.add("판정", "json_mode=guided_json  thinking=off(설정 llm.thinking)  "
                     "max_tokens=24,000(설정 llm.max_tokens)")
    cond.add("동시", "8", "설정 run.workers")

    summary = RunSummary(version="v9.9", args="--conv-data x " * 8,
                         setup=cond.compact(), input_shape="3 users / 6 conv / 18 turns")
    for line in summary.render().splitlines():
        assert display_width(line) <= 80, f"{display_width(line)}칸: {line!r}"

    # 값이 통째로 살아 있어야 재현에 쓸 수 있다.
    joined = " ".join(summary.setup)
    for value in ("qwen3.5-397b-a17b-instruct-2507", "max_tokens=24,000", "동시=8"):
        assert value in joined, f"{value} 가 잘렸다: {joined!r}"


def test_prev_question_accepts_the_shape_the_real_log_uses():
    """실행 환경로그의 prev_question 은 list 다 (2026-09-01, 16,141건).

    계약이 str 만 받으면 매 실행마다 MISMATCH 한 줄이 뜨는데, 파이프라인은 이
    필드를 읽지 않으므로 판정은 멀쩡하다. 계약 위반 줄은 "판정이 틀렸을 수 있다"는
    뜻이어야 한다 - 거기 잡음이 섞이면 실행 환경에서 그 줄 자체를 안 보게 된다.
    """
    from ragdiag.contracts import check_log
    from ragdiag.fixtures.synth import generate

    payload = generate(seed=0)
    for user in payload["users"]:
        for conv in user["conversations"]:
            for turn in conv["turns"]:
                turn["prev_question"] = ["앞 질문 1", "앞 질문 2"]

    report = check_log(payload)
    assert report.ok, "\n".join(m.line() for m in report.mismatches)


def test_unused_fields_do_not_count_as_contract_violations():
    """안 쓰는 필드의 어긋남은 노트로 내려가고, 쓰는 필드는 그대로 위반이다."""
    from ragdiag.contracts import check_log
    from ragdiag.fixtures.synth import generate

    payload = generate(seed=0)
    for user in payload["users"]:
        for conv in user["conversations"]:
            for turn in conv["turns"]:
                # route_intent 는 받아만 두고 판정에 안 쓴다. prev_question 이
                # 여기 있었는데 pre_queries 의 2순위가 되면서 쓰는 필드로 올라갔다.
                turn["route_intent"] = {"안": "쓰는 필드"}
                turn["llm_eval_score"] = "쓰는 필드"

    report = check_log(payload)
    assert [m.field for m in report.mismatches] == ["llm_eval_score"], (
        [m.line() for m in report.mismatches])
    # tool_calls 는 "없어도 되는 키" 라 합성 로그에 없으면 노트 한 줄이 더 붙는다.
    assert [m.field for m in report.notes if m.kind != "absent"] == ["route_intent"], (
        [m.line() for m in report.notes])
    assert not report.ok, "쓰는 필드가 어긋났으므로 ok 가 아니다"


# ---------------------------------------------------------------------------
# C3 · 3.2 — 실데이터 값이 화면으로 새지 않는다
# ---------------------------------------------------------------------------

def test_contract_mismatch_reports_types_not_values():
    """계약 위반 메시지에 실제 값이 실리면 그게 유출 경로다.

    타입 이름과 건수까지만 적는다.
    """
    from ragdiag.contracts import TURN_SCHEMA, validate

    rows = [{"turn": "비밀사번-12345", "user_question": "김철수 연봉이 얼마야"}]
    for m in validate(rows, TURN_SCHEMA, "turn"):
        assert "비밀사번" not in m.line()
        assert "김철수" not in m.line()


def test_contract_mismatch_is_transcribable():
    """`validation failed` 같은 메시지는 규격에서 결함이다.

    무엇이 어떻게 어긋났는지가 나와야 사람이 옮겨 적고 contracts.py 를 고친다.
    """
    from ragdiag.contracts import TURN_SCHEMA, validate

    rows = [{"turn": "1", "user_question": "질문", "새필드": 1}]
    lines = [m.line() for m in validate(rows, TURN_SCHEMA, "turn")]
    assert any("turn.turn" in l and "str" in l for l in lines), lines
    assert any("새필드" in l for l in lines), "새 필드는 관찰가 된다"


def test_run_summary_prints_every_required_row():
    """규격 3.2 의 블록. 성공·실패 무관하게 이 줄들이 있어야 한다."""
    from ragdiag.contracts import Mismatch
    from ragdiag.summary import RunSummary

    text = RunSummary(
        version="v0.4 (a1b2c3d)", input_shape="1,204,331 rows",
        contract_ok=24,
        contract_mismatches=[Mismatch("turn", "grade", "allowed", "허용값 밖 12건")],
        metrics=[("auc", "0.8123")], runtime_sec=412, peak_gb=6.2,
        status="OK",
    ).render()
    for row in ("version", "input", "contract", "metrics", "runtime", "status"):
        assert f"{row:<10}:" in text, f"{row} 줄이 없다:\n{text}"
    assert "MISMATCH" in text
    assert "turn.grade" in text


def test_run_summary_lines_fit_80_columns():
    """옮겨 적는 사람을 위해 한 줄에 한 항목, 80자 이내."""
    from ragdiag.contracts import Mismatch
    from ragdiag.summary import RunSummary

    text = RunSummary(
        version="v" * 40, input_shape="x" * 80,
        contract_mismatches=[Mismatch("turn", "f" * 40, "k", "d" * 80)],
        metrics=[("m" * 40, "v" * 60)],
    ).render()
    long = [l for l in text.splitlines() if len(l) > 80]
    assert not long, "80자를 넘는 줄:\n" + "\n".join(long)


def test_version_is_never_blank():
    """빈칸이면 옮겨 적을 때 빠진다. 모르면 모른다고 적는다."""
    from ragdiag.summary import version

    assert version().strip()


# ---------------------------------------------------------------------------
# 1.3 — 바뀔 만한 값이 전부 설정에 있다
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# scripting.md 가 약속한 계약
#
# 작업 폴더 쪽에서 이걸 감싸는 스크립트를 짠다. 종료 코드와 스트림 구분이
# 그 스크립트가 기댈 전부다 - 화면 문구는 바뀌어도 이 둘은 안 바뀌어야 한다.
# ---------------------------------------------------------------------------

def _entry(argv, cwd):
    import sys as _sys

    return subprocess.run([_sys.executable, str(ROOT / "src" / "run.py"), *argv],
                          capture_output=True, text=True, cwd=cwd)


def test_exit_codes_match_the_scripting_contract(tmp_path):
    """0=정상 / 1=돌았지만 온전치 않다 / 2=시작도 못 했다.

    1 과 2 를 가르는 기준은 "계산을 시작했나"다. 2 는 고치고 다시 돌리면 되고,
    1 은 이미 돈 것이라 재시도해도 같다 - 스크립트의 분기가 여기 걸린다.
    """
    import json

    from ragdiag.fixtures.synth import generate

    log = tmp_path / "conv.json"
    log.write_text(json.dumps(generate(n=1, seed=0), ensure_ascii=False), encoding="utf-8")

    assert _entry(["--conv-data", str(log), "--dry-run"], tmp_path).returncode == 0

    # 시작도 못 하는 것들
    assert _entry(["--conv-data", str(tmp_path / "없다.json")], tmp_path).returncode == 2

    # 돌았지만 볼 턴이 없다
    turns = tmp_path / "turns.json"
    turns.write_text("[]", encoding="utf-8")
    got = _entry(["--conv-data", str(log), "--turns", str(turns)], tmp_path)
    assert got.returncode == 1, got.stdout + got.stderr


def test_run_summary_goes_to_stdout_and_progress_to_stderr(tmp_path):
    """로그로 남길 것과 사람이 보며 판단할 것을 가른다.

    RUN SUMMARY 가 stderr 로 새면 `> log.txt` 로 남긴 파일이 비어 있게 된다.
    """
    import json

    from ragdiag.fixtures.synth import generate

    log = tmp_path / "conv.json"
    log.write_text(json.dumps(generate(n=1, seed=0), ensure_ascii=False), encoding="utf-8")

    got = _entry(["--conv-data", str(log), "--dry-run"], tmp_path)
    assert "RUN SUMMARY" in got.stdout, "요약은 stdout 이다"
    assert "RUN SUMMARY" not in got.stderr
    assert "실행 조건" in got.stderr, "진행 상황은 stderr 다"
    assert "실행 조건" not in got.stdout


def test_scripting_example_uses_only_documented_things():
    """예시 스크립트가 문서에 없는 것을 쓰면 읽는 사람이 그걸 계약으로 오해한다."""
    doc = (ROOT / "todo/scripting.md").read_text(encoding="utf-8")
    example = doc.split("#!/usr/bin/env bash")[1].split("```")[0]

    assert "log_analysis/src/run.py" in example, "진입점을 그대로 보여줘야 한다"
    assert "ls -1 output/[0-9]*_*.json" in example, "결과는 이름 규칙으로 찾는다"
    assert "결과:" not in example.replace('echo "결과: $LATEST"', ""), (
        "stderr 를 긁어서 경로를 얻으면 안 된다")
    for banned in ("--upgrade", "pip install", "activate"):
        assert banned not in example, f"예시가 {banned} 를 쓰고 있다"


def test_docs_are_grouped_and_still_shipped():
    """참조 문서는 docs/ 에 모으되 반입은 되어야 한다.

    docs/insights/ 만 export-ignore 다. 규칙을 docs/ 로 넓히면 실행 환경에서
    filter.md · scripting.md 를 못 보게 된다 - 거기서 봐야 하는 문서다.
    """
    # 성격이 다르다 - todo/ 는 저쪽에서 **만들 것**의 규격이고,
    # docs/ 는 이 프로그램이 **어떻게 도는지**의 참고다.
    for where, names in (("todo", ("filter.md", "scripting.md")),
                         ("docs", ("process_flow.md", "taxonomy.md"))):
        for name in names:
            assert (ROOT / where / name).exists(), f"{where}/{name} 가 없다"
            assert not (ROOT / name).exists(), f"{name} 이 루트에 남아 있다"

    for folder in ("docs/", "todo/"):
        ignored = subprocess.run(["git", "check-attr", "export-ignore", "--", folder],
                                 capture_output=True, text=True, cwd=ROOT)
        assert not ignored.stdout.strip().endswith(": set"), (
            f"{folder} 를 통째로 뺐다. 실행 환경에서 봐야 하는 문서다.")


def test_root_keeps_only_what_has_to_be_there():
    """루트는 도구·관례가 찾는 것과 첫 화면만. 나머지는 docs/ 다."""
    allowed = {"README.md", "TODO.md"}
    at_root = {f for f in tracked() if f.endswith(".md") and "/" not in f}
    assert at_root == allowed, f"루트의 문서: {sorted(at_root)}"


def test_todo_says_which_items_are_this_project_only():
    """어느 것이 이 프로젝트의 사정이고 어느 것이 일반인지 갈라 적는다.

    다음 프로젝트에서 이 저장소를 본보기로 쓸 때, 필터를 저쪽에 두는 것이
    규격이 요구하는 것인지 이 프로젝트의 사정인지 구분되지 않으면 안 해도 될
    일을 하게 된다.
    """
    todo = (ROOT / "TODO.md").read_text(encoding="utf-8")
    assert "이 프로젝트의 사정" in todo
    assert "어느 프로젝트나" in todo


def test_todo_points_at_the_specs_instead_of_repeating_them():
    """할 일 목록이 규격을 베끼면 둘이 갈라진다. 가리키기만 한다."""
    todo = (ROOT / "TODO.md").read_text(encoding="utf-8")
    for spec in ("todo/filter.md", "todo/scripting.md"):
        assert spec in todo, f"{spec} 를 가리켜야 한다"
    assert len(todo.splitlines()) < 220, (
        "TODO 가 규격을 베끼고 있다. 무엇이 남았나만 세고 방법은 docs/ 에 둔다.")


def test_readme_does_not_hand_out_a_command_that_needs_an_uncommitted_file():
    """갓 clone 한 사본에서 그대로 쳐서 실패하는 명령을 적어두지 않는다.

    실제로 `--config configs/env.yaml` 을 그냥 적어 두었었다. 그 파일은 커밋되지
    않으므로 clone 직후에는 없다. 이런 줄은 "설정을 안 만들었나" 가 아니라
    "문서가 틀렸나" 를 먼저 의심하게 만든다.
    """
    doc = (ROOT / "README.md").read_text(encoding="utf-8")
    for block in doc.split("```bash")[1:]:
        block = block.split("```")[0]
        if "--config configs/env.yaml" not in block:
            continue
        # log_analysis/ 를 경로에 두는 블록은 작업 폴더(작업 폴더) 기준이다. 거기서는
        # sync.sh 가 env.yaml 을 만들어 주므로 복사 단계가 필요 없다.
        in_work_folder = "log_analysis/" in block or "작업 폴더" in block
        assert "cp configs/env.example.yaml" in block or in_work_folder, (
            "clone 직후에 없는 파일을 쓰는 명령이다. 복사 단계를 함께 적을 것:\n"
            + block.strip()[:300])


def test_only_the_example_config_is_committed():
    """운영 실값이 든 설정이 저장소에 들어오면 그게 유출이다 (C3).

    실제로 한 번 뚫렸다. .gitignore 에 파일 이름을 하나씩 적어 두었는데 그중
    하나가 일괄 치환으로 망가지면서 무시가 풀렸고, `git add -A` 가 그걸 그대로
    커밋했다. 이름을 나열하는 대신 configs/*.yaml 을 막고 예시만 예외로 둔다.
    """
    committed = {f for f in tracked() if f.startswith("configs/") and f.endswith(".yaml")}
    assert committed == {"configs/env.example.yaml"}, (
        f"예시 말고 다른 설정이 커밋돼 있다: {sorted(committed - {'configs/env.example.yaml'})}")


def test_ignore_rule_is_an_allowlist_not_a_namelist():
    """이름을 하나씩 적으면 오타 한 번에 무시가 풀린다. 그때 조용히 커밋된다."""
    rules = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "configs/*.yaml" in rules, "설정은 전부 막고 예시만 예외로 둘 것"
    assert "!configs/env.example.yaml" in rules

    # git 에게 직접 물어본다. 적어 놓은 것과 적용되는 것은 다를 수 있다.
    for path, want_ignored in (("configs/env.yaml", True),
                               ("configs/아무거나.yaml", True),
                               ("configs/env.example.yaml", False)):
        ignored = subprocess.run(["git", "check-ignore", "-q", "--no-index", path],
                                 cwd=ROOT).returncode == 0
        assert ignored is want_ignored, f"{path}: 무시={ignored}, 기대={want_ignored}"


def test_example_config_is_committed():
    assert "configs/env.example.yaml" in tracked()


def test_sync_script_is_committed_and_executable():
    assert "scripts/sync.sh" in tracked()
    assert (ROOT / "scripts/sync.sh").stat().st_mode & 0o111


def test_sync_derives_names_instead_of_hardcoding_them():
    """규격: 사본 는 스크립트 위치에서, <pkg> 는 src/ 아래에서 유도한다.

    이름을 박아 두면 저장소나 패키지 이름이 바뀔 때 실행 환경에서 조용히 엉뚱한
    경로를 만든다. 거기서는 고칠 수 없다.
    """
    text = (ROOT / "scripts/sync.sh").read_text(encoding="utf-8")
    assert 'STAGING=".staging/BB"' not in text, "저장소 이름이 박혀 있다"
    assert 'DEST="BB"' not in text, "사본 경로가 박혀 있다"
    assert "BASH_SOURCE" in text, "스크립트 위치에서 이름을 유도해야 한다"
    assert '"$DEST"/src/*.py' in text, "src/ 에서 진입점을 찾아야 한다"


def test_sync_refuses_outside_the_two_known_places():
    """실행 위치가 모드를 정한다. 셋째 위치에서 돌면 엉뚱한 자리에 사본을 만든다."""
    proc = subprocess.run(["bash", str(ROOT / "scripts/sync.sh"), "v0.0"],
                          capture_output=True, text=True, cwd="/tmp")
    assert proc.returncode != 0
    assert "실행 위치가 맞지 않습니다" in proc.stderr
    # 둘 중 어디로 가야 하는지 둘 다 알려줘야 한다. 문구는 규격 부록 전문
    # 그대로라 이 저장소의 용어 정리 대상이 아니다 (아래 테스트가 전문 일치를 잰다).
    assert proc.stderr.count("bash") >= 2, proc.stderr


def test_sync_refuses_without_a_tag():
    """태그 없이 실행하지 않는다 (규격 '하지 말 것' 4)."""
    proc = subprocess.run(["bash", str(ROOT / "scripts/sync.sh")],
                          capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode != 0
    assert "태그" in proc.stderr


def test_pyproject_declares_runtime_deps():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "pydantic" in text
    assert "PyYAML" in text, "--config 를 쓰려면 필요하다"
    # 대시보드는 선택이어야 한다. 반입 부담을 늘리지 않는다.
    assert "streamlit" in text.split("optional-dependencies")[1]


def _fake_repo(tmp_path, with_launcher=True, extra_req=""):
    """sync.sh 만 시험하기 위한 최소 저장소. 이 저장소의 git 상태에 기대지 않는다."""
    import subprocess

    bb = tmp_path / "toolkit"
    (bb / "scripts").mkdir(parents=True)
    (bb / "src" / "somepkg").mkdir(parents=True)
    (bb / "src" / "somepkg" / "__init__.py").write_text("", encoding="utf-8")
    (bb / "configs").mkdir()
    (bb / "configs" / "env.example.yaml").write_text("a: 1\n", encoding="utf-8")
    (bb / "requirements.txt").write_text("pydantic>=2.0\n" + extra_req, encoding="utf-8")
    (bb / "scripts" / "sync.sh").write_text(
        (ROOT / "scripts/sync.sh").read_text(encoding="utf-8"), encoding="utf-8")
    if with_launcher:
        (bb / "src" / "run.py").write_text("print('hi')\n", encoding="utf-8")
    run = lambda *a: subprocess.run(["git", "-C", str(bb), *a],
                                    capture_output=True, text=True, check=True)
    run("init", "-q")
    run("config", "user.email", "t@t"); run("config", "user.name", "t")
    run("add", "-A"); run("commit", "-q", "-m", "x")
    return bb


def _sync(aa, bb, tag):
    import subprocess
    return subprocess.run(["bash", ".staging/toolkit/scripts/sync.sh", tag],
                          capture_output=True, text=True, cwd=aa)


def _fresh_aa(tmp_path, bb):
    import subprocess

    aa = tmp_path / "work"
    (aa / ".staging").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(aa)], check=True)
    subprocess.run(["git", "clone", "-q", str(bb), str(aa / ".staging" / "toolkit")],
                   check=True)
    return aa


# 규격 문서는 옆 저장소에 있다. 절대 경로를 박으면 개인 머신 경로가 소스에 남고
# 점검 스크립트가 그걸 잡는다 (§1.3 위반이기도 하다).
SPEC = pathlib.Path(
    os.environ.get("IMPLEMENTATION_SPEC")
    or ROOT.parent / "general_implementation" / "IMPLEMENTATION_SPEC.md")


def test_internal_command_sequence_only_uses_what_ships():
    """실행 환경 순서에 반입 안 되는 것이 등장하면 거기서 사이클이 하나 날아간다.

    실제로 README 가 `tools/legacy_run.py --check-llm` 을 시키고 있었다. tools/ 는
    export-ignore 라 실행 환경에 없다 - 물어볼 데도 없는 장비에서 command not found 를
    만나게 된다. 그래서 순서 블록은 archive 에 실제로 담기는 것만 참조해야 한다.
    """
    doc = (ROOT / "README.md").read_text(encoding="utf-8")
    block = doc.split("<!-- BEGIN 실행 환경 순서 -->")[1].split("<!-- END 실행 환경 순서 -->")[0]

    ignored = [l.split()[0].rstrip("/") for l in
               (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
               if l.strip() and not l.strip().startswith("#") and "export-ignore" in l]
    hits = [name for name in ignored if f"{name}/" in block]
    assert not hits, f"실행 환경에 없는 것을 시키고 있다: {hits}"

    # 진입점과 점검 순서가 실제로 있는지.
    for needed in ("scripts/sync.sh", "src/run.py --check-llm", "--dry-run"):
        assert needed in block, f"순서에 {needed} 가 없다"


def test_check_llm_lives_in_the_shipped_entry_point():
    """에어갭에서 가장 먼저 돌릴 것이다. tools/ 에 있으면 거기서는 못 돈다."""
    from ragdiag.__main__ import check_llm  # noqa: F401

    source = (ROOT / "src/ragdiag/__main__.py").read_text(encoding="utf-8")
    assert "--check-llm" in source


def test_gitattributes_has_no_end_of_line_comments():
    """git 은 .gitattributes 에서 줄 끝 주석을 지원하지 않는다.

    실제로 이걸로 한 번 뚫렸다. `tools/ export-ignore  # 설명` 은 경고 한 줄만
    내고 **그 줄이 통째로 무시된다.** 무시된 줄은 조용히 무시되므로 archive 를
    풀어보기 전에는 tools/ 가 실행 환경으로 넘어가는 것을 알 수 없다.
    """
    path = ROOT / ".gitattributes"
    assert path.exists(), "이식 표면을 정하는 파일이 없다 (규격 §2.3)"

    bad = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "#" in stripped:
            bad.append(f"{n}: {stripped}")
    assert not bad, ("줄 끝 주석은 그 줄을 통째로 무효로 만든다. 주석은 따로 줄을 "
                     "쓸 것:\n" + "\n".join(bad))


def test_every_export_ignore_line_actually_registers():
    """적어 놓은 것과 git 이 실제로 적용하는 것은 다를 수 있다.

    패턴 문법이 .gitignore 와 미묘하게 다르고, 잘못 쓴 줄은 **조용히** 무시된다.
    한 줄이 죽으면 그 디렉터리가 통째로 실행 환경에 도착하는데, archive 를 풀어보기
    전에는 알 수 없다. 그래서 줄마다 git 에게 직접 물어본다.

    패턴을 쓴 그대로 물어봐야 한다 - `tools/` 는 set 이지만 `tools` 나
    `tools/dev_run.py` 로 물으면 unspecified 다. 디렉터리 패턴은 archive 가
    디렉터리 항목에서 걸러내기 때문이다.
    """
    lines = [l.strip() for l in (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()]
    patterns = [l.split()[0] for l in lines
                if l and not l.startswith("#") and "export-ignore" in l]
    assert patterns, ".gitattributes 에 export-ignore 줄이 없다"

    dead = []
    for pattern in patterns:
        out = subprocess.run(["git", "check-attr", "export-ignore", "--", pattern],
                             capture_output=True, text=True, cwd=ROOT)
        if not out.stdout.strip().endswith(": set"):
            dead.append(f"{pattern} → {out.stdout.strip().split(': ')[-1]}")
    assert not dead, "이 줄들은 무시된다:\n" + "\n".join(dead)


def test_sync_matches_the_spec_appendix():
    """부록 A 가 전문이다. 여기서 손대면 양쪽이 조용히 갈라진다.

    예전에는 이 저장소에만 있는 편차(조건부 pip 안내)를 두고 그 이유를 테스트로
    고정했었다. 규격이 두 모드로 다시 쓰이면서 그 편차가 사라졌고, 편차를 재던
    테스트만 남아 실패했다. 이제는 **전문 일치**만 재고 편차를 두지 않는다.
    """
    if not SPEC.exists():
        pytest.skip("규격 문서가 이 장비에 없다 (다른 저장소)")
    body = SPEC.read_text(encoding="utf-8").split("<!-- BEGIN sync.sh -->")[1]
    body = body.split("<!-- END sync.sh -->")[0]
    want = body.split("```bash\n", 1)[1].rsplit("```", 1)[0]
    have = (ROOT / "scripts/sync.sh").read_text(encoding="utf-8")
    assert have == want, "scripts/sync.sh 가 규격 부록과 다르다. 부록을 그대로 옮길 것."


def test_preflight_catches_a_file_that_must_not_ship(tmp_path):
    """①에서 걸리면 태그를 다시 내면 되고, ②에서 걸리면 사이클을 하나 버린다."""
    import subprocess

    bb = _fake_repo(tmp_path)
    (bb / "tools").mkdir()
    (bb / "tools" / "dev.py").write_text("import anthropic\n", encoding="utf-8")
    for a in (["add", "-A"], ["commit", "-q", "-m", "tools"], ["tag", "v1"]):
        subprocess.run(["git", "-C", str(bb), *a], check=True)

    out = subprocess.run(["bash", "scripts/sync.sh", "v1"],
                         capture_output=True, text=True, cwd=bb)
    assert out.returncode != 0, out.stdout
    assert "tools" in out.stderr, out.stderr
    assert "export-ignore" in out.stderr, "무엇을 하라는지까지 적어야 한다"


def test_preflight_passes_when_the_surface_is_clean(tmp_path):
    import subprocess

    bb = _fake_repo(tmp_path)
    subprocess.run(["git", "-C", str(bb), "tag", "v1"], check=True)
    out = subprocess.run(["bash", "scripts/sync.sh", "v1"],
                         capture_output=True, text=True, cwd=bb)
    assert out.returncode == 0, out.stderr
    assert "preflight: OK" in out.stdout
    assert "git push origin v1" in out.stdout, "다음에 할 일을 알려줘야 한다"


def test_sync_writes_version_and_leaves_no_git(tmp_path):
    """결과 파일이 반출 안 되는 상황에서 VERSION 이 '어떤 코드로 돌렸는지'의 전부다."""
    import subprocess

    bb = _fake_repo(tmp_path)
    subprocess.run(["git", "-C", str(bb), "tag", "v1"], check=True)
    aa = _fresh_aa(tmp_path, bb)

    out = _sync(aa, bb, "v1")
    assert out.returncode == 0, out.stderr
    assert (aa / "toolkit" / "VERSION").read_text(encoding="utf-8").startswith("v1 ")
    assert not (aa / "toolkit" / ".git").exists(), "C6 — .git 이 AA 로 넘어갔다"
    assert (aa / "outputs").is_dir() and (aa / "notebooks").is_dir()
    assert (aa / ".staging" / ".gitignore").read_text(encoding="utf-8").strip() == "*"


def test_sync_keeps_local_yaml_and_names_the_new_keys(tmp_path):
    """운영 실값이 든 유일한 파일이다. 덮어쓰면 되돌릴 방법이 없다."""
    import subprocess

    bb = _fake_repo(tmp_path)
    subprocess.run(["git", "-C", str(bb), "tag", "v1"], check=True)
    aa = _fresh_aa(tmp_path, bb)
    _sync(aa, bb, "v1")
    (aa / "configs" / "env.yaml").write_text("a: 실행 환경 실값\n", encoding="utf-8")

    (bb / "configs" / "env.example.yaml").write_text("a: 1\nb: 2\n", encoding="utf-8")
    for a in (["add", "-A"], ["commit", "-q", "-m", "key"], ["tag", "v2"]):
        subprocess.run(["git", "-C", str(bb), *a], check=True)

    out = _sync(aa, bb, "v2")
    assert out.returncode == 0, out.stderr
    assert (aa / "configs" / "env.yaml").read_text(encoding="utf-8") == "a: 실행 환경 실값\n"
    assert "b" in out.stderr, "example 에만 있는 키를 알려줘야 한다\n" + out.stderr


def test_sync_removes_the_copy_when_the_check_fails(tmp_path):
    """실수로 커밋되는 것을 막는다. 걸린 사본이 남아 있으면 그게 운영 git 에 들어간다."""
    import subprocess

    bb = _fake_repo(tmp_path)
    (bb / "tools").mkdir()
    (bb / "tools" / "dev.py").write_text("x = 1\n", encoding="utf-8")
    for a in (["add", "-A"], ["commit", "-q", "-m", "tools"], ["tag", "v1"]):
        subprocess.run(["git", "-C", str(bb), *a], check=True)
    aa = _fresh_aa(tmp_path, bb)

    out = _sync(aa, bb, "v1")
    assert out.returncode != 0
    assert not (aa / "toolkit").exists(), "걸린 사본이 남아 있다"


def test_dashboard_deps_are_not_in_the_main_requirements():
    """설치할 것을 늘리지 않는다. 분류 파이프라인은 pydantic·PyYAML 이면 된다."""
    main = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    active = [l for l in main.splitlines() if l.strip() and not l.startswith("#")]
    for banned in ("streamlit", "pandas"):
        assert not any(banned in l for l in active), (
            f"{banned} 이 requirements.txt 에 있다. "
            "requirements-dashboard.txt 로 옮길 것.")
    assert (ROOT / "requirements-dashboard.txt").exists()


# ---------------------------------------------------------------------------
# 문서가 코드보다 앞서 나가지 않도록 — v4 (docs/design/decision_tree_v4.md)
# ---------------------------------------------------------------------------

def _doc(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_taxonomy_doc_lists_every_bucket_with_its_owner():
    from ragdiag import taxonomy as tx

    doc = _doc("docs/taxonomy.md")
    table = doc.split("## 묶음 — 고치는 사람이다")[1].split("## 네 단계")[0]
    for b in tx.BUCKETS.values():
        if b.id == tx.REVIEW:
            continue
        assert f"| **{b.name}** | {b.owner} |" in table, f"{b.name} 행이 없거나 고치는 사람이 다르다"
    assert "**검토**는 묶음이 아니라 상태다" in doc


def test_taxonomy_doc_lists_the_complaint_questions_in_reading_order():
    from ragdiag import questions as qs

    doc = _doc("docs/taxonomy.md")
    section = doc.split("### 불만 판정의 문항 여덟")[1].split("### 근거 판정")[0]
    positions = [section.index(qs.TEXT[qid]) for qid in qs.COMPLAINT]
    assert positions == sorted(positions), "문서의 문항 순서가 questions.COMPLAINT 와 다르다"
    for qid in (*qs.EVIDENCE_SLOT, "any"):
        assert qs.TEXT[qid] in doc, f"근거 판정 문항이 문서에 없다: {qs.TEXT[qid]}"


def test_taxonomy_doc_states_every_way_into_a_bucket():
    """'들어오는 길' 은 BECAUSE 문장의 요약이다. 출구가 늘거나 줄면 문서도 바뀌어야 한다."""
    from ragdiag import taxonomy as tx

    doc = _doc("docs/taxonomy.md")
    assert str(len(tx.STEPS)) in doc.split("## 네 단계")[0] or "네 단계" in doc
    for step in tx.STEPS:
        assert step in doc, f"단계 이름이 문서에 없다: {step}"


def test_process_flow_names_the_four_steps_and_the_judges_in_order():
    from ragdiag import features, taxonomy as tx

    doc = _doc("docs/process_flow.md")
    for step in tx.STEPS:
        assert f"{step}" in doc
    for module in features.JUDGES:
        assert f"features/{module.NAME}" in doc or f"`features/{module.NAME}`" in doc, (
            f"process_flow.md 가 판정 기능 {module.NAME} 을 가리키지 않는다")
    order = [doc.index(f"features/{m.NAME}") for m in features.JUDGES]
    assert order == sorted(order), "문서의 단계 순서가 JUDGES 와 다르다"


def test_process_flow_output_example_uses_real_sentences():
    from ragdiag import questions as qs, taxonomy as tx

    doc = _doc("docs/process_flow.md")
    example = doc.split("## 한 턴이 낳는 것 전부")[1].split("## 파일")[0]
    assert tx.BECAUSE[f"{tx.STEP_EVIDENCE}:any:all"] in example
    assert qs.TEXT["complains"] in example and qs.SKIPPED in example
    for key in ("verdict", "steps", "flags", "axes", "text", "target_turn"):
        assert f'"{key}"' in example


def test_readme_flow_matches_the_judge_order():
    from ragdiag import features

    readme = _doc("README.md")
    flow = readme.split("## 처리 흐름")[1].split("## 분류 체계")[0]
    names = [m.NAME for m in features.JUDGES]
    positions = [flow.index(f"`{n}`") for n in names]
    assert positions == sorted(positions), "README 의 기능 순서가 JUDGES 와 다르다"


def test_because_sentences_have_no_question_ids_or_v3_labels():
    """결과 파일에 코드가 아니라 말이 간다. 문항 id · 옛 라벨이 새면 읽는 사람이 번역해야 한다."""
    import re

    from ragdiag import questions as qs, taxonomy as tx

    for key, sentence in tx.BECAUSE.items():
        assert not re.search(r"\b[NUCTDGSI]\d\b", sentence), f"{key}: 옛 라벨이 들어 있다: {sentence}"
        for qid in qs.TEXT:
            assert qid not in sentence, f"{key}: 문항 id 가 들어 있다: {sentence}"


@pytest.mark.parametrize("name", ["README.md", "docs/taxonomy.md", "docs/process_flow.md",
                                  "docs/insights/TEMPLATE.md"])
def test_markdown_renders_as_markdown(name):
    """코드 펜스가 안 닫히면 GitHub 에서 나머지가 통째로 코드블록이 된다.

    실제로 그렇게 깨뜨린 적이 있다. 치환 스크립트가 블록 경계를 잘못 잡아
    문서의 모든 펜스를 표로 바꿔치웠고, 화면에서만 알아챌 수 있었다.
    """
    path = ROOT / name
    if not path.exists():
        pytest.skip(f"{name} 없음")
    lines = path.read_text(encoding="utf-8").splitlines()

    fences = [i + 1 for i, l in enumerate(lines) if l.startswith("```")]
    assert len(fences) % 2 == 0, (
        f"{name}: 코드 펜스가 홀수({len(fences)}개)라 닫히지 않았다. "
        f"마지막 펜스는 {fences[-1]}줄.")

    # 표가 코드블록 안에 갇히지도 않아야 한다
    inside, trapped = False, []
    for i, line in enumerate(lines, 1):
        if line.startswith("```"):
            inside = not inside
        elif inside and line.startswith("|") and "---" in line:
            trapped.append(i)
    assert not trapped, f"{name}: 표가 코드블록 안에 있다 — {trapped[:3]}줄"


def test_no_section_is_duplicated():
    """같은 제목이 여러 번 나오면 치환이 잘못 퍼진 것이다."""
    import re
    from collections import Counter

    for name in ["README.md", "docs/taxonomy.md", "docs/process_flow.md"]:
        text = (ROOT / name).read_text(encoding="utf-8")
        heads = Counter(re.findall(r"^#{2,4} (.+)$", text, re.M))
        dupes = {h: n for h, n in heads.items() if n > 1}
        assert not dupes, f"{name}: 제목이 반복된다 — {dupes}"
