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
    classification,
    code_rules,
    complaint,
    evidence,
    failures,
    filter_fp,
    integrity,
    llm_fallback,
)

__all__ = ["FEATURES", "JUDGES", "REPORTS", "RunContext", "collect"]

# 판정 순서 — 결정 트리 (docs/design/decision_tree_v4.md). 앞 기능이 닫은 턴은 뒤로 안 간다.
JUDGES = (
    integrity,         # 플래그 열 — 멈추지 않음
    code_rules,        # 코드 확정 — 자원 부족 문구 · 빈 답변 · 붕괴 → 시스템
    complaint,         # 불만 판정 — kev 8문항 → 정상 · 시스템 · 생성 · 사용자
    evidence,          # 근거 판정 — kev 5문항 → 생성 · 근거, 일부면 열어 둠
)

# 집계. 화면에 뜨는 순서다 — 사람이 사이클 사이에 눈으로 대조하므로 순서를 바꾸지 않는다.
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
                             workers=1, backends=ctx.backends, progress=False)
            for feature in JUDGES:
                with lock:
                    if id(turn) in abandoned:
                        break                # 이미 닫혔다 - 늦은 결과는 버려진다
                    stage[id(turn)] = feature.NAME
                if not turn.is_open:
                    break                    # 앞 기능이 닫았다 (코드 확정 · 불만 판정 · 실패)
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
