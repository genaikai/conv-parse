"""기능 등록부. 여기 적힌 순서대로 실행된다.

**기능은 판정만이 아니다.** 같은 입력을 읽어 결과를 내는 독립 단위면 무엇이든
기능이다 — LLM 판정도, 코드 검증도, 진리표도, 분포 집계도.

판정 기능은 앞 기능이 턴마다 남긴 것을 읽는다. 그래서 **FEATURES 의 순서가 곧 실행
순서**이고, 판정 순서가 적힌 곳은 여기뿐이다. 집계 기능은 판정이 끝난 뒤에 와서
결과를 읽기만 한다.

전에는 지표들이 `__main__.py` 안에 흩어져 있었다. 지표를 하나 더 내려면 진입점을
고쳐야 했는데, 진입점은 기능이 늘어도 손대지 않아야 하는 파일이다.

기능을 만들려면 둘이면 된다:

    cp -r src/<pkg>/features/template src/<pkg>/features/<기능>
    # 아래 FEATURES 에 한 줄 더한다
"""

import queue
import threading
import time

from ragdiag import settings
from ragdiag.progress import Progress

from ._context import RunContext
from ._shared import straggler_limit
from . import (
    arithmetic,
    citation,
    classification,
    complaint_quote,
    dates,
    failures,
    filter_fp,
    format,
    grounding,
    history_quote,
    injection,
    language,
    legibility,
    length,
    llm_fallback,
    observe,
    pii,
    python_syntax,
    quoted_spans,
    request_quote,
    route,
    short_circuit,
    sql_shape,
    sufficiency,
)

__all__ = ["CHECKS", "FEATURES", "RunContext", "collect"]

# 코드 검증기. LLM 없이 문자열만 본다 - 언어가 맞는지, 답변이 끊겼는지, 등식이 맞는지는
# 문자열만 보면 안다. LLM 에 맡기면 비용도 들지만 무엇보다 같은 입력에 다른 답이 나온다.
# 서로의 결과를 읽지 않으므로 이 안의 순서는 판정에 영향이 없다 (출력에 실리는 순서다).
CHECKS = (
    pii,
    quoted_spans,
    python_syntax,
    sql_shape,
    arithmetic,
    dates,
    injection,
    language,          # 이 셋은 관측이 뽑은 요구값을 읽는다 - observe 뒤여야 한다
    format,
    length,
)

JUDGES = (
    short_circuit,     # LLM 전에 case 를 확정하는 규칙들 (규칙끼리의 순서는 그 안의 RULES)
    legibility,        # ④′ 읽을 수 있는 글인가 · LLM (답변만 본다) — 아니면 case30 으로 끝
    observe,           # Step 1 관측 · LLM
    complaint_quote,   # "불만 아님" 의 근거를 후속 발화와 대조
    request_quote,     # 요구의 인용을 이전 질문들과 대조 — 없으면 요구를 지운다
    history_quote,     # "이전 조건을 어겼다" 의 인용을 앞 질문들과 대조 — 없으면 무효
    *CHECKS,           # 코드 검증기
    sufficiency,       # Step 2 충족도 · LLM
    citation,          # 판정자의 인용을 원문과 대조
    grounding,         # Step 3 근거 활용 · LLM
    route,             # 진리표 → case
)

# 집계. 화면에 뜨는 순서다 — 사람이 사이클 사이에 눈으로 대조하므로 순서를 바꾸지 않는다.
# 판정 기능과 갈라 둔 이유는 실행 방식이다 - 판정은 턴 단위로 돌 수 있지만 집계는 전부
# 끝난 뒤 한 번이다.
REPORTS = (
    classification,
    llm_fallback,
    filter_fp,
    failures,
)


FEATURES = JUDGES + REPORTS      # 실행 순서 전체. 문서 · 테스트가 이 이름을 본다


def collect(ctx: RunContext) -> tuple[list, list]:
    """기능 전부를 순서대로 돌리고 지표와 노트를 합친다.

    두 실행 방식이 있다 (settings.RUN_MODE).

      stage  판정 기능을 하나씩, 매 기능이 턴 전부를 돈다. 단계 경계마다 제일 느린 턴을
             기다린다 - 낙오자 규칙(_shared.each_turn)이 그 대기를 끊는다.
      turn   턴 하나가 판정 기능 전부를 끝까지 간다. 느린 턴이 다른 턴을 막지 않고, 끝난
             턴부터 ctx.on_turn_done 으로 넘겨 중간 결과를 저장할 수 있다. 낙오자 규칙은
             턴 전체 소요 시간에 건다.

    집계 기능은 어느 방식이든 판정이 전부 끝난 뒤 한 번 돈다.
    """
    metrics: list = []
    notes: list = []
    seen: set = set()

    if settings.RUN_MODE == "turn":
        _judge_per_turn(ctx)
        # FEATURES 에서 판정 기능을 뺀 나머지. 테스트가 FEATURES 를 갈아끼우기도 한다.
        pending = [f for f in FEATURES if f not in JUDGES]
    else:
        pending = FEATURES

    for feature in pending:
        got, said = feature.process_data(ctx)
        for name, _ in got:
            # 빈 이름은 앞 지표에 딸린 줄이라 겹침을 보지 않는다.
            if not name:
                continue
            if name in seen:
                # 조용히 두 번 찍으면 같은 것이 두 줄로 보이고, 사람은 어느 쪽을
                # 옮겨 적어야 할지 모른다. 시끄럽게 죽는 쪽이 낫다.
                raise KeyError(
                    f"{feature.NAME} 의 지표 이름이 겹친다: {name}. "
                    f"지표 이름 앞에 NAME 을 붙여라"
                )
            seen.add(name)
        metrics += got
        notes += said
    return metrics, notes


def _judge_per_turn(ctx: RunContext) -> None:
    """턴 하나가 판정 기능 전부를 끝까지 간다. 데몬 워커 ctx.workers 개.

    기능은 그대로 쓴다 - 턴 하나짜리 RunContext 를 만들어 넘기면 each_turn 이 그 한 턴만
    돈다. 그래서 판정 기능 쪽은 한 줄도 안 바뀐다.

    낙오자 규칙은 턴 전체 소요 시간에 건다. 절반(8건 이상)이 끝난 뒤 중앙값의 배수를 넘겨도
    안 끝나는 턴은 그 턴이 지금 머무는 기능 이름으로 닫는다 - failures 집계가 그 이름을 센다.
    """
    turns = list(ctx.open_turns())
    bar = Progress("judge", len(turns), enabled=getattr(ctx, "progress", True))
    on_done = getattr(ctx, "on_turn_done", None)

    todo: queue.Queue = queue.Queue()
    for turn in turns:
        todo.put(turn)
    lock = threading.Lock()
    changed = threading.Condition(lock)
    started: dict[int, float] = {}
    stage: dict[int, str] = {}              # id(turn) -> 지금 머무는 기능
    finished: dict[int, float] = {}
    abandoned: set[int] = set()

    def worker():
        while True:
            try:
                turn = todo.get_nowait()
            except queue.Empty:
                return
            with lock:
                started[id(turn)] = time.monotonic()
            one = RunContext(selection=ctx.selection, turns=[turn], judge=ctx.judge,
                             workers=1, backend=ctx.backend, progress=False)
            for feature in JUDGES:
                with lock:
                    if id(turn) in abandoned:
                        break                # 이미 닫혔다 - 늦은 결과는 버려진다
                    stage[id(turn)] = feature.NAME
                if turn.classification is not None or turn.error is not None:
                    break                    # 앞 기능이 닫았다 (short_circuit · legibility · 실패)
                feature.process_data(one)
            with changed:
                if id(turn) not in abandoned:
                    finished[id(turn)] = time.monotonic() - started[id(turn)]
                    bar.done(ok=turn.error is None)
                    if on_done is not None:
                        on_done(turn)
                changed.notify_all()

    for _ in range(max(1, min(ctx.workers, len(turns)))):
        threading.Thread(target=worker, daemon=True, name="judge-worker").start()

    with changed:
        while len(finished) + len(abandoned) < len(turns):
            changed.wait(timeout=1.0)
            limit = straggler_limit(list(finished.values()), len(turns))
            if limit is None:
                continue
            now = time.monotonic()
            for turn in turns:
                key = id(turn)
                if key in finished or key in abandoned or key not in started:
                    continue
                waited = now - started[key]
                if waited > limit:
                    turn.error = (f"[{stage.get(key, 'judge')}] 낙오 — 턴 전체 {waited:.0f}초째 "
                                  f"(기준 {limit:.0f}초). 재실행하면 이 턴만 다시 묻는다")
                    abandoned.add(key)
                    bar.abandon()
                    if on_done is not None:
                        on_done(turn)
    bar.finish()
