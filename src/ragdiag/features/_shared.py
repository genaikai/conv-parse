"""기능 여럿이 같이 쓰는 것. 기능이 아니므로 이름 앞에 밑줄을 둔다.

둘 이상이 **같은 기준**을 써야 할 때만 여기로 올린다. 한 기능만 쓰는 것은 그 기능
폴더 안에 둔다 — 여기 올려두면 고칠 때 누가 영향받는지 알 수 없다.
"""

import queue
import statistics
import threading
import time
from collections import Counter

from ragdiag import settings
from ragdiag.progress import Progress


def top_cases(turns, limit: int = 5):
    """상위 case 몇 개. 지표 이름은 사이클 사이에 바뀌지 않아야 한다."""
    counts = Counter(t.classification.primary_case for t in turns if t.classification)
    return counts.most_common(limit)


def each_turn(ctx, name, fn, *, where=None, parallel=False) -> None:
    """열린 턴 중 where 에 맞는 턴마다 fn(turn) 을 돌린다.

    턴 하나의 실패가 나머지를 날리면 안 된다. 실패한 턴은 그 자리에서 닫는다
    (error="[이름] 예외") — 뒤 기능은 건너뛰고, 이름이 남아서 어느 단계에서 몰려
    깨졌는지 셀 수 있다. failures 기능이 이 접두어를 읽는다.

    parallel 은 LLM 을 부르는 기능만 켠다. 턴 하나는 한 스레드만 만지므로 락이
    필요 없다.

    진행 표시도 parallel 인 기능에만 붙인다 - 코드 검증기는 눈 깜빡할 새에 끝나서
    줄만 깜빡이고, 정작 수십 분이 걸리는 것은 LLM 을 부르는 셋뿐이다.

    **낙오자는 기다리지 않는다.** 단계별 실행이라 턴 하나가 안 오면 그 단계가 못 끝나고
    다음 단계가 통째로 기다린다. HTTP 타임아웃(기본 600초)은 그 예산이 아니라 사실상 무한
    대기다. 그래서 그 단계에서 이미 끝난 턴들의 소요 시간을 보고, 절반이 끝난 뒤부터
    중앙값의 몇 배(settings.STRAGGLER_FACTOR)를 넘겨도 안 오는 턴은 에러로 닫고 넘어간다
    - 서버가 전반적으로 느린 날은 기준이 같이 늘고, 하나만 튀는 날은 빨리 포기한다.
    닫힌 턴의 늦은 응답은 버려진다 (그 턴은 이미 error 라 뒤 기능이 건너뛰고, 출력에는
    error 만 실린다). 재실행하면 성공한 호출은 캐시에서 나오고 그 턴만 다시 묻는다.
    """
    turns = [t for t in ctx.open_turns() if where is None or where(t)]
    bar = Progress(name, len(turns),
                   enabled=parallel and getattr(ctx, "progress", True))

    def run(turn):
        try:
            fn(turn)
        except Exception as e:
            # 타입명을 남겨서 예상 못 한 예외가 조용히 묻히지 않게 한다. 낙오로 이미
            # 닫힌 턴이면 그 사유를 지우지 않는다 - 늦게 온 응답의 예외는 뒷이야기다.
            if turn.error is None:
                turn.error = f"[{name}] {type(e).__name__}: {e}"
        bar.done(ok=turn.error is None)

    if parallel and len(turns) > 1:
        _run_parallel(name, run, turns, max(1, ctx.workers), bar)
    else:
        for turn in turns:
            run(turn)
    bar.finish()


# 낙오 판정을 시작하려면 끝난 턴이 이만큼은 있어야 한다 - 중앙값이 믿을 만해지는 수.
_MIN_DONE_FOR_MEDIAN = 8


def straggler_limit(durations: list[float], total: int) -> float | None:
    """지금 기다려 줄 최대 초. 아직 판단할 근거가 없으면 None.

    절반 이상(그리고 8건 이상)이 끝났을 때부터, 중앙값 × 배수와 최소 초 중 큰 쪽이다.
    배수가 0 이면 끈다 - 그러면 HTTP 타임아웃만 남는다.
    """
    factor = settings.STRAGGLER_FACTOR
    if not factor or len(durations) < max(_MIN_DONE_FOR_MEDIAN, total / 2):
        return None
    return max(factor * statistics.median(durations), settings.STRAGGLER_MIN_SEC)


def _run_parallel(name, run, turns, workers: int, bar: Progress) -> None:
    """데몬 스레드 풀. ThreadPoolExecutor 를 안 쓰는 이유는 종료다 - 그쪽 스레드는 인터프리터가
    끝날 때 join 되어, 포기한 턴의 HTTP 호출이 끝날 때까지 프로세스가 안 죽는다. 데몬이면
    결과를 쓰고 바로 끝난다."""
    todo: queue.Queue = queue.Queue()
    for turn in turns:
        todo.put(turn)
    lock = threading.Lock()
    started: dict[int, float] = {}          # id(turn) -> 시작 시각
    finished: dict[int, float] = {}         # id(turn) -> 소요 초
    abandoned: set[int] = set()
    changed = threading.Condition(lock)

    def worker():
        while True:
            try:
                turn = todo.get_nowait()
            except queue.Empty:
                return
            with lock:
                started[id(turn)] = time.monotonic()
            run(turn)
            with changed:
                finished[id(turn)] = time.monotonic() - started[id(turn)]
                changed.notify_all()

    for _ in range(min(workers, len(turns))):
        threading.Thread(target=worker, daemon=True, name=f"{name}-worker").start()

    with changed:
        while len(finished) + len(abandoned) < len(turns):
            changed.wait(timeout=1.0)
            limit = straggler_limit([d for k, d in finished.items() if k not in abandoned],
                                    len(turns))
            if limit is None:
                continue
            now = time.monotonic()
            for turn in turns:
                key = id(turn)
                if key in finished or key in abandoned or key not in started:
                    continue
                waited = now - started[key]
                if waited > limit:
                    turn.error = (f"[{name}] 낙오 — {waited:.0f}초째 응답 없음 "
                                  f"(이 단계 기준 {limit:.0f}초). 재실행하면 이 턴만 다시 묻는다")
                    abandoned.add(key)
                    bar.abandon()


def call_llm(turn, pair):
    """(결과, 사용량) 을 받아 사용량을 그 턴에 쌓고 결과만 돌려준다.

    캐시 적중은 사용량이 0 이라 호출로 세지 않는다. 공유 카운터에 쌓으면 스레드가
    섞여 사용량이 부풀려지므로 턴 객체에 쌓는다.
    """
    value, used = pair
    turn.usage.add(used)
    turn.n_calls += bool(used.input_tokens or used.output_tokens or used.cost_usd)
    return value


def run_check(ctx, name, check) -> tuple[list, list]:
    """코드 검증기 하나를 열린 턴마다 돌려 turn.checks[name] 에 남긴다."""
    each_turn(ctx, name, lambda t: t.checks.__setitem__(name, check(t)))
    return [], []
