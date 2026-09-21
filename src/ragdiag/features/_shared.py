"""기능 여럿이 같이 쓰는 것. 기능이 아니므로 이름 앞에 밑줄을 둔다.

둘 이상이 **같은 기준**을 써야 할 때만 여기로 올린다. 한 기능만 쓰는 것은 그 기능
폴더 안에 둔다 — 여기 올려두면 고칠 때 누가 영향받는지 알 수 없다.
"""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor

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
    """
    turns = [t for t in ctx.open_turns() if where is None or where(t)]
    bar = Progress(name, len(turns),
                   enabled=parallel and getattr(ctx, "progress", True))

    def run(turn):
        try:
            fn(turn)
        except Exception as e:
            # 타입명을 남겨서 예상 못 한 예외가 조용히 묻히지 않게 한다.
            turn.error = f"[{name}] {type(e).__name__}: {e}"
        bar.done(ok=turn.error is None)

    if parallel and len(turns) > 1:
        with ThreadPoolExecutor(max_workers=max(1, ctx.workers)) as pool:
            list(pool.map(run, turns))
    else:
        for turn in turns:
            run(turn)
    bar.finish()


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
