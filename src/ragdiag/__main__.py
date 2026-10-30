#!/usr/bin/env python
"""conv_eval 로그를 taxonomy case 로 분류한다.

  python <저장소>/src/run.py --conv-data <로그> --output-dir outputs --dry-run
  python <저장소>/src/run.py --conv-data <로그> --filter-data <필터> --output-dir outputs

필터가 고른 턴만 세 층으로 분류한다:

  묻는다    LLM 에는 좁은 관측만 (읽기 · Step 1 관측 · Step 2 충족도 · Step 3 근거 활용)
  되돌린다  코드가 원문과 대조해 받쳐 주지 않는 주장을 지운다 (인용 · 요구 · 검증기 10종)
  정한다    진리표가 조합해 case 를 고른다. case 는 LLM 이 고르지 않는다

결과는 pre_data_format 형태로 나온다. 원본 필드는 그대로 두고 분류 결과는
`classification` 아래에 모은다.

설정은 --config 로 준다. 실행 환경에서는 코드를 못 고치므로 바뀔 값은 전부 거기 있다.
CLI 플래그는 설정을 덮어쓴다 - 한 번만 다르게 돌려볼 때 쓴다.

설정 없이 돌리려면 환경변수 두 개면 된다:
  export LLM_API_URL=http://<서버>:8000
  export LLM_API_KEY=<키>
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from ragdiag.backends import (
    KEY_VARS,
    THINKING_PARAMS,
    URL_VARS,
    JudgeError,
    backend_from_env,
)
from ragdiag import contracts, features, settings
from ragdiag.config import ConfigError, apply_overrides
from ragdiag.config import apply as apply_config
from ragdiag.config import load as load_config
from ragdiag.judge import Judge
from ragdiag.pipeline import (
    build_outcome,
    load_and_select,
    select_turns,
    make_judge,
)
from ragdiag.results import TurnResult
from ragdiag.survey import chunk_metric, chunk_report
from ragdiag.output import build_output
from ragdiag.summary import (
    Conditions,
    RunSummary,
    Timer,
    peak_memory_gb,
    version,
)

# --output-dir 도 설정도 없을 때. 실행 위치 기준이라 실행 환경에서는
# 작업 폴더 아래에 생긴다.
DEFAULT_OUTPUT_DIR = "output"


def result_name(stamp: str, conv_data, filter_path=None, turns_path=None) -> str:
    """결과 파일의 이름 — <시각>_<로그 이름>_<턴을 고른 것의 이름>.

    로그 이름과 필터 이름은 경로에서 확장자만 뗀 것이다. 로그가 없으면(합성 데이터
    스모크) synthetic, 필터도 턴 목록도 없으면 all 이다. 요약 파일은 같은 이름에
    _summary.txt 가 붙어 나란히 정렬된다.
    """
    log = Path(conv_data).stem if conv_data else "synthetic"
    scope = Path(filter_path or turns_path).stem if (filter_path or turns_path) else "all"
    return f"{stamp}_{log}_{scope}"

# --config 를 안 줬을 때 찾아보는 자리. 실행 위치 기준이라 작업 폴더에서 돌리면
# 작업 폴더의 configs/env.yaml 이 된다 - 설정은 언제나 거기 둔다.
DEFAULT_CONFIG = Path("configs/env.yaml")


# 재실행 루프 방지. 갈아탄 파이썬이 또 다른 prefix 를 보고하면 무한히 돈다.
_REEXEC_FLAG = "RAGDIAG_VENV_SWITCHED"


def switch_to_configured_venv(config) -> None:
    """paths.venv 에 적은 파이썬으로 갈아타고 다시 시작한다.

    적어만 두고 쓰지 않으면 "설정했는데 무시된다" 가 된다. 설정 파일에 적은 값이
    아무것도 바꾸지 않는 것은 그 자체로 결함이다 - 특히 공용 환경에서는
    activate 를 잊었는지 확인할 방법이 화면밖에 없다.

    exec 라 이 프로세스가 그대로 대체된다. 인자와 cwd 가 보존되므로 같은 명령이
    새 파이썬으로 다시 도는 것과 같다. 계산을 시작하기 전이라 잃을 것이 없다.
    """
    want = config.get("paths.venv")
    if not want or os.environ.get(_REEXEC_FLAG):
        return
    venv = Path(want)
    if venv.resolve() == Path(sys.prefix).resolve():
        return                                   # 이미 그 venv 다

    for candidate in (venv / "bin" / "python", venv / "Scripts" / "python.exe"):
        if candidate.exists():
            break
    else:
        raise ConfigError(
            f"paths.venv 에 적은 곳에 파이썬이 없습니다: {venv}\n"
            f"  찾은 곳: {venv / 'bin' / 'python'}\n"
            f"  경로를 확인하거나, 설정에서 paths.venv 를 비우고 그 venv 를 "
            f"activate 한 뒤 실행하세요.")

    print(f"[venv] {sys.prefix}\n    -> {venv}  (설정 paths.venv)", file=sys.stderr)
    os.environ[_REEXEC_FLAG] = "1"
    os.execv(str(candidate), [str(candidate), *sys.argv])


def make_backend(args, config=None, trace=None):
    """CLI 인자 > 설정 > 환경변수 순으로 고른다.

    trace(Conditions)를 주면 각 값이 **어디서 왔는지** 함께 적는다. 값만 찍으면
    "왜 저 값이지"를 못 푼다 - 실행 환경에는 .bashrc 의 환경변수, AA/configs/env.yaml,
    CLI 플래그가 겹쳐 있고 셋 다 화면에 안 보인다. 어느 쪽이 이겼는지가 안 보이면
    설정을 고쳐도 안 먹는 이유를 알 수 없다.
    """
    src: dict[str, str] = {}

    def pick(flag, key, default=None, flag_name=""):
        if flag is not None:
            src[key] = flag_name or "--" + key.rsplit(".", 1)[-1].replace("_", "-")
            return flag
        if config is not None and config.get(key) is not None:
            # llm.env_file 로 끌어온 값은 그 사실을 적는다. "설정 llm.url" 로만
            # 찍으면 어느 파일에 적힌 값인지 알 수 없어서, 고쳐도 안 먹는 이유를
            # 못 찾는다 - 이 블록을 두는 이유가 그것이다.
            src[key] = config.origins.get(key) or f"설정 {key}"
            return config.get(key)
        src[key] = "기본값"
        return default

    # 이 진입점이 아는 백엔드는 하나다. 예전에는 LLM_API_URL 이 없으면 claude CLI 로
    # 떨어졌는데, 그 경로가 tools/ 로 나가면서 자동 선택도 같이 사라졌다.
    # 주소가 없으면 backend_from_env 가 무엇을 export 하라고 알려준다.
    backend = pick(args.backend, "llm.backend", "local")
    if src["llm.backend"] == "기본값":
        found = next((n for n in URL_VARS if os.environ.get(n)), None)
        src["llm.backend"] = f"기본값 · 주소는 {found}" if found else "기본값"
    model = pick(args.model, "llm.model")
    timeout = pick(args.timeout, "llm.timeout_sec", 600)
    json_mode = pick(args.json_mode, "llm.json_mode", "auto")
    thinking = pick(args.thinking, "llm.thinking", "auto")
    # 추론을 끄는 파라미터 이름이 서버마다 다르다. 기본값은 실행 환경인 vLLM 쪽이고,
    # OpenRouter 같은 중계 서비스로 잴 때만 바꾼다 (backends.THINKING_PARAMS).
    thinking_param = pick(args.thinking_param, "llm.thinking_param", "chat_template_kwargs")
    max_tokens = pick(args.max_tokens, "llm.max_tokens", 16000)

    def note(built):
        if trace is None:
            return built
        trace.add("백엔드", backend, src["llm.backend"])
        if backend != "cli":
            trace.add("주소", url or "(없음)", src["llm.url"])
            # 키는 값을 절대 찍지 않는다. 어디서 왔는지만 적는다.
            trace.add("키", "설정됨" if key else "(없음)", src["llm.key"])
        trace.add("모델", built.model,
                  src["llm.model"] if model else "자동 탐지",
                  "" if model else "서버 /v1/models 의 첫 항목")
        if backend != "cli":
            # 값마다 출처가 달라서 한 줄로 묶으면 어느 게 어디서 왔는지 사라진다.
            # 기본값이 아닌 것에만 출처를 붙인다.
            def tag(key, text):
                where = src[key]
                return text if where == "기본값" else f"{text}({where})"
            trace.add("판정", "  ".join([
                tag("llm.json_mode", f"json_mode={json_mode}"),
                tag("llm.thinking", f"thinking={thinking}"),
                tag("llm.thinking_param", f"thinking_param={thinking_param}"),
                tag("llm.max_tokens", f"max_tokens={max_tokens:,}")]))
        return built

    if backend != "local":
        # 이 진입점은 실행 환경에서 도는 경로만 안다. claude CLI 와 Anthropic API 는
        # 실행 환경에서 호출이 전부 실패하므로 tools/ 에 있고, src/ 는 tools/ 를
        # import 하지 않는다.
        raise JudgeError(
            f"--backend {backend} 는 이 진입점에 없습니다.\n"
            "  실행 환경에서 실패할 호출은 src/ 에 두지 않습니다.\n"
            "  그 백엔드로 돌리려면:\n"
            "    python tools/dev_run.py --backend " + backend + " ...\n"
            "  실행 환경·서버 경로는 --backend local 입니다."
        )

    url = pick(args.base_url, "llm.url", flag_name="--base-url")
    if url is None:
        for name in URL_VARS:
            if os.environ.get(name):
                url, src["llm.url"] = os.environ[name], f"환경변수 {name}"
                break
    key = pick(args.api_key, "llm.key", flag_name="--api-key")
    if key is None:
        for name in KEY_VARS:
            if os.environ.get(name):
                key, src["llm.key"] = os.environ[name], f"환경변수 {name}"
                break
    return note(backend_from_env(
        base_url=url, api_key=key, model=model,
        json_mode=json_mode, thinking=thinking, max_tokens=max_tokens,
        timeout=timeout, thinking_param=thinking_param,
    ))


def _checkpointer(owners, turns, out_path, run_info=None, with_text=True,
                  every_sec: float = 10.0):
    """끝난 턴만 모아 결과 파일에 쓴다. 마지막 저장은 collect 뒤의 outcome.save 가 한다."""
    import threading
    import time

    lock = threading.Lock()
    last = [0.0]

    def save(_turn):
        now = time.monotonic()
        with lock:
            if now - last[0] < every_sec:
                return
            last[0] = now
            done = [(o, t) for o, t in zip(owners, turns) if not t.is_open]
            if not done:
                return
            try:
                build_outcome([o for o, _ in done], [t for _, t in done],
                              run_info=run_info, with_text=with_text).save(out_path)
            except OSError:
                pass                     # 중간 저장이 실패해도 판정은 계속 간다

    return save


def check_llm(args, config=None) -> int:
    """로컬 LLM 서버가 붙는지, 구조화 출력을 어떻게 강제할 수 있는지 점검한다.

    **에어갭 장비에서 가장 먼저 돌릴 것이다.** 거기서는 물어볼 데가 없으므로 스스로
    진단이 되어야 하고, 전체를 돌리기 전에 서버 규약과 1회 소요시간을 확정해야
    한다 - 그래야 전체가 몇 분인지 알고 시작한다.

    v4 에서 일반 LLM 은 kev 가 없을 때의 에뮬레이션에만 쓴다. 그래서 탐침도 에뮬레이션
    1회다 — 불만 판정 문항 하나를 빈 답변에 묻는다. 이 함수는 로컬 서버만 본다.
    """
    import time

    from ragdiag import questions
    from ragdiag.decide import LLMDecisionBackend, _emulation_model

    try:
        backend = make_backend(args, config)
    except JudgeError as e:
        print(e, file=sys.stderr)
        return 2

    print(f"서버 : {backend.base_url}")
    print(f"모델 : {backend.model}" + ("   (자동 탐지)" if backend.discovered else ""))
    if backend.discovered:
        others = [m for m in backend.list_models() if m != backend.model]
        if others:
            print(f"       서버의 다른 모델: {', '.join(others)}")
            print(f"       다른 걸 쓰려면 --model <이름>")
    print(f"추론 모드 : {backend.thinking}   (auto = 서버 기본값 유지)")

    probe = {"truncated": questions.COMPLAINT["truncated"]}
    try:
        started = time.monotonic()
        mode = backend.negotiate(_emulation_model(probe))
        print(f"구조화 출력 강제 방식 : {mode}   ({time.monotonic() - started:.1f}s)")
        if len(backend.negotiation_log) > 1:
            print("  협상 과정:")
            for line in backend.negotiation_log:
                print(f"    {line}")
    except JudgeError as e:
        print(f"\n연결 실패:\n{e}", file=sys.stderr)
        return 1

    if mode == "none":
        print("\n  경고: 이 서버는 구조화 출력을 강제하지 못합니다.")
        print("  프롬프트만으로 JSON을 요구하게 되어 재시도가 잦아집니다.")
        print("  프록시(LiteLLM 등)를 거치고 있다면 파라미터를 버리고 있을 수 있습니다.")

    # 규약뿐 아니라 모델이 지시를 따르는지도 봐야 한다.
    print("\nkev 에뮬레이션 1회 시도...")
    started = time.monotonic()
    try:
        answers, usage = LLMDecisionBackend(backend).decide(
            {"answer": "국내 출장 식비는 1일 3만원을 상한으로 하며, 숙박비는"}, probe)
    except JudgeError as e:
        print(f"\n판정 실패:\n{e}", file=sys.stderr)
        return 1

    elapsed = time.monotonic() - started
    print(f"  답변이 중간에 끊겼다 : p={answers['truncated'].p:.2f}   (기대: 예, p ≥ 0.9)")
    print(f"  소요            : {elapsed:.1f}s")
    print(f"  토큰            : 입력 {usage.input_tokens:,} / 출력 {usage.output_tokens:,}")
    if answers["truncated"].p < 0.9:
        print("\n  경고: 이 탐침은 '예' 가 정답입니다. 문장이 중간에서 끊긴 답변입니다.")
        print("  모델이 지시를 못 따르고 있거나 확신을 낮게 내고 있을 수 있습니다.")

    if backend.fallbacks:
        print(f"\n  추론이 답에 도달 못 해 {len(backend.fallbacks)}회 폴백했습니다.")
        print("  전체 실행은 --thinking off 로 시작하는 편이 낫습니다.")

    workers = args.workers or settings.DEFAULT_WORKERS
    print(f"\n턴 1건당 kev 요청은 최대 3회다. 1,000턴이면 대략 "
          f"{elapsed * 1000 * 2 / max(workers, 1) / 60:.0f}분 "
          f"(요청 2,000회 가정, 동시 {workers}).")
    return 0


def main(argv=None, backend=None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m ragdiag",
        description="conv_eval 로그를 taxonomy case 로 분류",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--config", help="설정 YAML. configs/env.example.yaml 참고")
    # 설정 파일 없이도 전부 인자로 줄 수 있어야 한다. 부르는 쪽이 자기 설정 하나로
    # 통제하려면 그쪽 스크립트가 값을 읽어 넘기는 형태가 되는데, 그때 키마다
    # 플래그를 만들면 서른 개가 넘고 키가 늘 때마다 또 는다.
    p.add_argument("--set", action="append", metavar="키=값",
                   help="설정 값을 인자로. 예: --set labels.query=configs/q.md "
                        "(목록 키는 여러 번 쓰면 쌓인다). 이름은 "
                        "configs/env.example.yaml 과 같다")

    p.add_argument("--conv-data",
                   help="conv_eval JSON 경로, 또는 records.jsonl (eval.jsonl 경로 — --turns 와 짝)")
    p.add_argument("--turns", metavar="FILE",
                   help="고른 턴 목록. conv-eval.json 이면 {chat_id, turn}, records.jsonl 이면 "
                        "assemble.py select 가 낸 selected.jsonl. 주면 여기 필터를 걸지 않는다")
    p.add_argument("--filter-data", "--filter", dest="filter_data",
                   help="필터 JSON. 없으면 진단 가능한 후속 턴 전부")
    p.add_argument("--output-dir", dest="output_dir",
                   help="산출물을 넣을 디렉터리 (기본 output). 없으면 만든다. 파일명에 끝난 시각이 붙는다")
    p.add_argument("--out", help="결과 파일 경로를 직접 지정. --output-dir 와 시각 스탬프를 무시한다")

    # 아래 기본값은 전부 None 이다. 설정과 CLI 를 구분하기 위해서다 -
    # argparse 기본값을 넣으면 "사용자가 준 것"과 "기본값"을 못 가린다.
    p.add_argument("--check-llm", action="store_true",
                   help="로컬 LLM 서버 점검 — 모델·강제방식·1회 소요시간. "
                        "실행 환경에서 전체를 돌리기 전에 먼저 돌린다")
    p.add_argument("--backend", choices=["local", "cli", "api"],
                   help="local: OpenAI 호환 서버 / cli: claude -p "
                        "(저장소에 없다) / api: Anthropic SDK")
    p.add_argument("--base-url", help="LLM 주소 (또는 $LLM_API_URL)")
    p.add_argument("--api-key", help="(또는 $LLM_API_KEY)")
    p.add_argument("--model", help="생략하면 서버의 /v1/models 에서 자동 탐지")
    p.add_argument("--json-mode",
                   choices=["auto", "json_schema", "guided_json", "json_object", "none"])
    p.add_argument("--thinking", choices=["auto", "on", "off"])
    p.add_argument("--thinking-param", choices=list(THINKING_PARAMS),
                   help="추론을 끄는 파라미터 이름. 기본은 vLLM 의 chat_template_kwargs, "
                        "OpenRouter 는 reasoning")
    p.add_argument("--max-tokens", type=int)
    p.add_argument("--timeout", type=int)

    p.add_argument("--limit", type=int, help="앞에서 N건만 (비용 확인용)")
    p.add_argument("--workers", type=int, help="동시 실행 턴 수")
    p.add_argument("--history-turns", type=int,
                   help="Step 1 에 넘길 이전 질문 개수 상한. 0 이면 제한 없음")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--no-text", action="store_true",
                   help="결과 파일에 질문 · 답변 · 근거 본문을 싣지 않는다 (전달본의 사례 절이 빈다)")
    p.add_argument("--no-progress", action="store_true",
                   help="LLM 단계의 진행 표시를 끈다 (기본은 stderr 에 한 줄)")
    p.add_argument("--dry-run", action="store_true",
                   help="합성 데이터 스모크. 필터까지만 적용하고 LLM 을 부르지 않는다")
    args = p.parse_args(argv)

    # 설정은 계산 전에 읽고 검증한다. 30분 뒤에 키 하나로 죽으면 사이클 하나를 버린다.
    try:
        # --config 를 안 줘도 작업 폴더의 설정을 쓴다. 실행 환경에서는 그 파일이
        # 거기 만들어 두므로, 이러면 실질적으로 필수가 되면서 아무것도 안 깨진다.
        # 없으면 기본값으로 도는 것도 그대로다 - 다만 없다는 사실이 화면에 남는다.
        config_path = args.config or (str(DEFAULT_CONFIG)
                                      if DEFAULT_CONFIG.exists() else None)
        config = apply_overrides(load_config(config_path), args.set)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2
    # 설정한 venv 로 갈아탄다. 계산을 시작하기 전이라야 한다.
    try:
        switch_to_configured_venv(config)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2

    changed = apply_config(config)
    if changed:
        print(f"설정 {config.source} 적용: {', '.join(changed)}", file=sys.stderr)
    for note in config.retired():
        print(f"설정 {note}", file=sys.stderr)

    if args.check_llm:
        return check_llm(args, config)

    conv_data = args.conv_data or config.get("paths.conv_data")

    # 데이터 없는 --dry-run 은 합성 데이터로 도는 스모크다. 여기서 실패하면
    # 환경 문제이지 데이터 문제가 아니다 - 그 둘을 갈라 보는 것이 목적이다.
    synthetic = False
    if not conv_data and args.dry_run:
        synthetic = True
    elif not conv_data:
        print("분석할 로그가 없습니다. --conv-data 로 경로를 주거나, "
              "--dry-run 으로 합성 데이터 스모크를 먼저 돌려보세요.", file=sys.stderr)
        return 2
    elif not Path(conv_data).exists():
        print(f"로그 파일이 없습니다: {conv_data}", file=sys.stderr)
        return 2

    filter_path = args.filter_data or config.get("paths.filter_data")
    turns_path = args.turns or config.get("paths.turns")
    # records.jsonl (eval.jsonl 경로의 사내 lookup 출력) 은 selected.jsonl 과 짝이다.
    # 필터는 ① select 에서 이미 걸었다 — 여기서는 안 받는다.
    records_mode = bool(conv_data) and str(conv_data).endswith(".jsonl")
    if records_mode and not turns_path:
        print("records.jsonl 에는 --turns <selected.jsonl> 이 필요합니다. 턴 번호와 앞 턴 수가 "
              "거기에만 있습니다 (docs/assemble.md).", file=sys.stderr)
        return 2
    if turns_path and filter_path:
        # 둘 다 "어느 턴을 볼지"를 정한다. 같이 주면 어느 쪽이 이겼는지 안 보인다.
        print("--turns 와 --filter-data 는 같이 쓸 수 없습니다. 둘 다 어느 턴을 "
              "볼지 정하는 것이라, 같이 주면 무엇이 적용됐는지 알 수 없습니다.",
              file=sys.stderr)
        return 2

    # --out(파일)이 --output-dir(디렉터리)보다 우선한다. 둘 다 없으면 현재 위치.
    out_dir = args.output_dir or config.get("paths.output_dir") or DEFAULT_OUTPUT_DIR
    out_path = args.out or config.get("paths.out")
    # 파일 이름은 <시각>_<로그>_<필터>. 실행 환경에서는 결과를 가져올 수 없어 이
    # 파일들이 그 자리에 계속 쌓이는데, 이름만 보고 언제 · 어느 로그를 · 어떤 조건으로
    # 돌린 것인지 알 수 있어야 한다. 시각이 앞이라 이름순이 곧 시간순이다.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_name = result_name(stamp, None if synthetic else conv_data, filter_path, turns_path)
    if not out_path:
        out_path = str(Path(out_dir) / f"{run_name}.json")
    if out_dir:
        # 없으면 만든다. 30분 돌린 뒤 디렉터리가 없어서 못 쓰면 그 사이클을 버린다.
        Path(out_dir).mkdir(parents=True, exist_ok=True)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    workers = args.workers or config.get("run.workers")
    limit = args.limit or config.get("run.limit")
    history = args.history_turns if args.history_turns is not None else None

    summary = RunSummary(version=version(),
                         args=" ".join(argv if argv is not None else sys.argv[1:]))
    summary.notes += config.retired()
    timer = Timer().__enter__()

    # 무엇을 읽어 무엇으로 돌리는지. **계산을 시작하기 전에** 찍는다 - 다 돌고
    # 나서 "모델이 그거였네"를 알면 이미 늦었다.
    def origin(flag, key: str, flag_name: str) -> str:
        if flag is not None:
            return flag_name
        if config.get(key) is not None:
            # --set 이나 llm.env_file 로 온 값은 그 사실을 적는다. "설정 X" 로만
            # 찍으면 어디를 고쳐야 하는지가 안 보인다.
            return config.origins.get(key) or f"설정 {key}"
        return "기본값"

    conditions = Conditions()
    # 지금 어느 파이썬으로 도는지. venv 경로는 설정 파일에 적을 수 없다 - 이미
    # 돌고 있는 파이썬 안에서 venv 를 바꿀 수는 없어서다. 대신 여기 찍어두면
    # 다음 사이클에 이 줄을 그대로 복사해서 activate 하면 된다.
    # VIRTUAL_ENV 는 activate 해야 생긴다. venv 의 python 을 경로로 직접 부르면
    # 비어 있어서 "venv 밖"으로 잘못 찍힌다 - prefix 로 본다.
    in_venv = sys.prefix != sys.base_prefix
    want_venv = config.get("paths.venv")
    switched = bool(os.environ.get(_REEXEC_FLAG))
    conditions.add(
        "파이썬", sys.executable,
        "설정 paths.venv 로 갈아탐" if switched else
        ("설정 paths.venv" if want_venv else
         (f"venv {Path(sys.prefix).name}" if in_venv else "시스템 파이썬")),
        "" if (in_venv or want_venv) else "공용 환경을 건드리고 있을 수 있다")
    n_set = sum(1 for o in config.origins.values() if o == "--set")
    conditions.add(
        "설정", config.source if config.source != "(기본값)" or not n_set
        else f"--set {n_set}개",
        "--config" if args.config else
        ("--set 만" if n_set and not config.source.startswith("/")
         and config.source == "(기본값)" else
         "자동 (작업 폴더)" if config.values else f"{DEFAULT_CONFIG} 이 없다"),
        (f"{len(changed)}개 값을 덮어씀" if changed else "덮어쓴 값 없음"))
    conditions.add("로그", str(conv_data) if conv_data else "(합성 데이터)",
                   origin(args.conv_data, "paths.conv_data", "--conv-data"))
    if turns_path:
        conditions.add("턴 목록", str(turns_path),
                       origin(args.turns, "paths.turns", "--turns"),
                       "운영 필터가 고른 것 — 여기 필터는 안 돈다")
    else:
        conditions.add("필터", str(filter_path) if filter_path else "(없음)",
                       origin(args.filter_data, "paths.filter_data", "--filter-data"),
                       "" if filter_path else "진단 가능한 후속 턴 전부")
    conditions.add("출력", out_path,
                   origin(args.out or args.output_dir, "paths.output_dir", "--output-dir"))
    # 캐시·동시는 --dry-run 에서도 적용된다. 백엔드 뒤에 두면 그때 블록이 반쪽이 된다.
    use_cache = not args.no_cache and config.get("paths.cache") is not False
    conditions.add("캐시", str(settings.CACHE_DIR) if use_cache else "(안 씀)",
                   "--no-cache" if args.no_cache else
                   origin(None, "paths.cache", ""))
    conditions.add("동시", str(workers or settings.DEFAULT_WORKERS),
                   origin(args.workers, "run.workers", "--workers"))

    # --- 계약 대조. 분류 전에 한다 -------------------------------------------
    # 여기서 나온 줄들이 실행 환경에서 이쪽으로 돌아오는 포맷 정보의 전부다.
    if synthetic:
        from ragdiag.fixtures.synth import generate

        payload = generate(n=3, seed=0)
        summary.notes.append("합성 데이터로 돌았다. 실데이터로 확인한 것이 아니다.")
        conv_data = _write_temp(payload)
    elif records_mode:
        from ragdiag.assemble import AssembleError, read_jsonl, records_to_payload

        try:
            payload = records_to_payload(read_jsonl(conv_data), read_jsonl(turns_path))
        except AssembleError as e:
            # finish() 는 아래에서 정의된다. 조립 실패는 계약 대조 전이라 요약 없이 끝낸다 -
            # 문장 자체가 사내에서 옮겨 적을 포맷 정보다.
            print(str(e), file=sys.stderr)
            return 2
    else:
        payload = json.loads(Path(conv_data).read_text(encoding="utf-8"))
    summary.input_shape = contracts.shape(payload)
    report = contracts.check_log(payload)
    summary.contract_ok = report.n_ok
    summary.contract_mismatches = report.mismatches
    summary.contract_notes = report.notes

    def finish(status: str, code: int) -> int:
        summary.status = status
        summary.runtime_sec = timer.seconds
        summary.peak_gb = peak_memory_gb()
        text = summary.render()
        print()
        print(text)
        # 화면이 유일한 출력이지만, 손으로 옮겨 적을 때 스크롤을 거슬러 올라가는
        # 것보다 파일을 여는 편이 낫다. 실행 환경 밖으로 나가는 것은 아니다.
        if out_dir:
            try:
                (Path(out_dir) / f"{run_name}_summary.txt").write_text(
                    text + "\n", encoding="utf-8")
            except OSError:
                pass
        return code

    try:
        if records_mode:
            from ragdiag.pipeline import select_records

            selection = select_records(conv_data, turns_path,
                                       history_turns=history, limit=limit)
        elif turns_path:
            selection = select_turns(conv_data, turns_path,
                                     history_turns=history, limit=limit)
        else:
            selection = load_and_select(conv_data, filter_path,
                                        history_turns=history, limit=limit)
    except (OSError, ValueError, KeyError) as e:
        summary.notes.append(f"로그를 읽지 못했다: {type(e).__name__}: {e}")
        return finish("FAILED (입력)", 2)

    print(selection.report, file=sys.stderr)
    summary.metrics.append(("selected", f"{len(selection):,} turns"))
    # 풀 크기는 파싱 시점에 정해진다. 결과 파일을 가지고 나올 수 없으므로 요약에
    # 남긴다 - 상한을 걸지 말지가 이 숫자에 달려 있다.
    summary.metrics.append(("chunks", chunk_metric(selection.cases)))

    if not selection.cases:
        # 첫 단계에서 다 빠졌으면 원인이 필터 조건이 아니라 로그 모양이다.
        # 앞 턴이 곧 "비판받은 답변"이라, 고른 턴만 남기면 판정할 대상이 없다.
        first = selection.steps[0] if selection.steps else None
        if first is not None and first.remaining == 0 and first.dropped:
            summary.notes.append(
                f"후속 턴 {first.dropped}건에 직전 턴이 없다. 고른 턴만 남기지 말고 "
                f"그 앞 턴도 함께 넘길 것 — 앞 턴이 판정 대상인 답변이다.")
        else:
            summary.notes.append("필터를 통과한 턴이 없다. 조건을 확인할 것.")
        return finish("NO DATA", 1)

    if args.dry_run:
        conditions.add("백엔드", "(안 씀)", "--dry-run", "LLM 호출 없음")
        conditions.hint = (f"{config.source} 를 고친다" if config.source != "(기본값)" else
                           "--set 으로 준다" if config.values else
                           "configs/env.example.yaml 을 복사해 --config 로 준다")
        print("\n" + conditions.render(), file=sys.stderr)
        summary.setup = conditions.compact()
        print("\n" + chunk_report(selection.cases), file=sys.stderr)
        print(f"\n분류 대상 {len(selection)}턴 (LLM 호출 없음)", file=sys.stderr)
        for sel, case in zip(selection.selected[:10], selection.cases[:10]):
            print(f"  {case.case_id}  turn {case.turn}  "
                  f"{sel.turn.eval_result} / {sel.turn.emotion_result}",
                  file=sys.stderr)
        return finish("DRY RUN", 0)

    injected = backend is not None
    try:
        backend = backend or make_backend(args, config, trace=conditions)
    except JudgeError as e:
        if not settings.KEV_URL:
            print(conditions.render(), file=sys.stderr)
            print(e, file=sys.stderr)
            summary.notes.append("LLM 백엔드를 만들지 못했다. 위 메시지를 옮겨 적을 것.")
            return finish("FAILED (백엔드)", 2)
        # kev 가 있으면 일반 LLM 없이도 돈다 — 일반 LLM 은 2차 판정(kev 모름 문항)에만 쓰므로
        # 그 단계만 건너뛰고 모름은 바로 검토다. 사내 기본 모양(kev 네 대, LLM 없음)이 이것이다.
        backend = None
        conditions.add("백엔드", "(없음)", "llm 주소 없음", "kev 만으로 돈다 — 2차 판정 건너뜀")
        summary.notes.append("일반 LLM 이 없어 2차 판정(LLM)을 건너뛰었다. kev 모름은 바로 검토다 "
                             "(llm.url 을 채우면 그 문항을 LLM 이 한 번 더 본다).")

    if injected:
        # 백엔드를 밖에서 넣으면 make_backend 를 안 거쳐 이 줄들이 빈다.
        # "무엇으로 돌리는지"가 이 블록의 존재 이유라 비워 둘 수 없다.
        conditions.add("백엔드", type(backend).__name__, "주입됨 (tools/dev_run.py)")
        conditions.add("모델", backend.model, "주입됨")

    conditions.hint = (f"{config.source} 를 고친다" if config.source != "(기본값)" else
                           "--set 으로 준다" if config.values else
                       "configs/env.example.yaml 을 복사해 --config 로 주거나 위 플래그로 덮어쓴다")
    print("\n" + conditions.render(), file=sys.stderr)
    print(f"분류 대상 {len(selection)}턴", file=sys.stderr)

    judge = make_judge(backend, use_cache=use_cache)
    models = judge.models()
    summary.metrics.append(("model", backend.model if backend is not None else "(없음)"))
    # 결정 백엔드(kev). 에뮬레이션이면 확률이 보정돼 있지 않다 - 요약에 그 사실이 남아야
    # 확신/검토를 읽는 사람이 그만큼 깎아 읽는다.
    kind = judge.decision_kind
    decision_note = {"kev": "", "emulated": "kev 에뮬레이션 — 확률 미보정",
                     "scripted": "테스트 대본"}.get(kind, kind)
    servers = getattr(judge.decision, "urls", [])
    conditions.add("판정(kev)", models.get("decision", "(없음)"),
                   f"설정 kev.url {len(servers)}대" if kind == "kev" else "kev.url 비어 있음", decision_note)
    summary.metrics.append(("decision", models.get("decision", "(없음)")
                            + (" (에뮬레이션)" if kind == "emulated" else "")))
    if kind == "emulated":
        summary.notes.append("kev 서버 없이 일반 LLM 으로 범주 판정을 에뮬레이션했다. "
                             "확률이 보정돼 있지 않으므로 확신/검토 구분은 참고치다 (kev.url 을 채울 것).")
    summary.setup = conditions.compact()
    # 결과 파일 머리. 언제 · 무엇을 · 어느 kev 로 돌렸나 — 파일만 들고 나와도 해석이 되게.
    run_info = {"started": datetime.now().isoformat(timespec="seconds"),
                "conv_data": str(conv_data), "filter_data": str(filter_path) if filter_path else None,
                "turns": str(turns_path) if turns_path else None,
                "kev": models["decision"], "kev_kind": kind, "kev_servers": list(servers),
                "threshold": settings.KEV_CONFIDENT, "pass_through": settings.KEV_PASS_THROUGH,
                "second_pass": backend.model if (settings.SECOND_PASS and backend is not None) else "",
                "version": version()}

    # 판정부터 집계까지 features.FEATURES 순서대로 한 번에 돈다. 판정 단계도 지표도
    # 여기서 하나씩 부르지 않는다 - 기능이 늘 때마다 진입점을 고치게 된다.
    ctx = features.RunContext(
        selection=selection,
        turns=[TurnResult(case=c) for c in selection.cases],
        judge=judge,
        workers=workers or settings.DEFAULT_WORKERS,
        backends=judge.all_backends(),
        progress=not args.no_progress,
    )
    # 턴 단위 실행이면 끝난 턴부터 결과 파일에 쌓는다 (10초에 한 번). 중간에 끊겨도
    # (Ctrl+C · 서버 다운) 거기까지의 판정은 남는다 - 30분 돌린 것을 통째로 잃지 않는다.
    ctx.on_turn_done = _checkpointer(selection.owners, ctx.turns, out_path, run_info,
                                     with_text=not args.no_text)
    got, said = features.collect(ctx)
    outcome = build_outcome(selection.owners, ctx.turns, selection.report, run_info,
                            with_text=not args.no_text)

    outcome.save(out_path)
    print(outcome.summary())
    print(f"\n결과: {out_path}", file=sys.stderr)

    summary.metrics += got
    summary.notes += said

    return finish("OK" if not outcome.n_failed else "PARTIAL",
                  1 if outcome.n_failed else 0)


def _write_temp(payload: dict) -> str:
    """합성 데이터를 임시 파일로. 파서가 경로를 받게 되어 있어서다.

    저장소에도 작업 폴더에도 남기지 않는다 - 가짜 데이터가 파일로 남으면
    운영 저장소로 흘러갈 길이 생긴다.
    """
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".json", prefix="ragdiag-smoke-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    atexit.register(lambda: Path(path).unlink(missing_ok=True))
    return path


if __name__ == "__main__":
    raise SystemExit(main())
