"""서비스가 실제로 끌고 간 맥락이 우리 추정과 얼마나 어긋나나.

2026-10 에 로그가 `carried_turn_nos` 와 `tool_output` 을 주기 시작했다. 그전까지
우리는 **턴 순서로 최근 3개**를 추정해 맥락으로 썼고, 문서는 그 턴의
`retrieved_data` 만 봤다. 둘 다 추정이었고 이제 사실이 있다.

그래서 이 지표가 재는 것은 **그전 판정을 얼마나 믿을 수 있나**다.

  어긋남이 작다   추정이 대체로 맞았다. 지난 집계가 그대로 선다
  어긋남이 크다   case14 · case20 · case22 · case24 를 다시 봐야 한다

두 갈래로 틀린다. 추정이 **넓으면**(챗봇이 못 본 턴을 우리가 봤으면) 못 본 조건을
어겼다고 case14 를 내고, **좁으면** 어긴 조건을 놓친다. 넓은 쪽이 오탐이라 더 나쁘다.

`tool_output` 은 비율만 센다. 그 값이 크면 청크 풀이 통째로 달라졌다는 뜻이고,
문서가 늘면 case20(문서에 없었다)이 case22(있었는데 안 썼다)로 옮겨 간다 —
**고칠 곳이 정반대로 바뀐다.**

풀 크기는 여기서 안 센다. 세려면 `conv.chunk_pool` 을 불러야 하는데 그쪽은 입력
계층이고 `features/` 는 코어다 (tests/test_boundary.py). 규칙을 베껴 오면 둘이
갈라진다 - 풀이 커지는지는 결과 파일의 `chunk_data` 길이로 본다.
"""

from ragdiag import settings

NAME = "carried"


def _estimate(turns, answered_turn: int, window: int) -> set[int]:
    """carried 가 없을 때 우리가 쓰던 추정 - 턴 순서로 최근 window 개."""
    prior = sorted(t for t in turns if t < answered_turn)
    return set(prior[-window:] if window > 0 else prior)


def measure(conversations, window: int = 0) -> dict:
    """대화들을 훑어 어긋남을 센다. 판정 결과가 아니라 로그만 본다."""
    window = window or settings.MAX_HISTORY_TURNS
    seen = wider = narrower = same = 0
    carried_total = 0
    with_tool = turns_total = 0

    for conv in conversations:
        numbers = [t.turn for t in conv.turns]
        for turn in conv.turns:
            turns_total += 1
            if turn.tool_output:
                with_tool += 1
            if not turn.carried_turn_nos:
                continue
            seen += 1
            carried_total += len(turn.carried_turn_nos)
            actual = set(turn.carried_turn_nos)
            guess = _estimate(numbers, turn.turn, window)
            if guess == actual:
                same += 1
            elif guess - actual:
                # 챗봇이 못 본 턴을 우리가 봤다. 오탐이 나는 쪽이다.
                wider += 1
            else:
                narrower += 1
    return {"seen": seen, "same": same, "wider": wider, "narrower": narrower,
            "carried_total": carried_total,
            "with_tool": with_tool, "turns": turns_total, "window": window}


def render(stat: dict) -> list[tuple[str, str]]:
    if not stat["turns"]:
        return []
    out = []
    if stat["seen"]:
        off = stat["wider"] + stat["narrower"]
        mean = stat["carried_total"] / stat["seen"]
        out.append((NAME,
                    f"평균 {mean:.1f}턴 · 추정({stat['window']}턴)과 어긋남 "
                    f"{100 * off / stat['seen']:.0f}%"))
        if off:
            out.append(("", f"{'우리가 더 넓게 봄':<20} {stat['wider']:,}   "
                            f"(못 본 조건을 어겼다고 할 수 있다)"))
            out.append(("", f"{'우리가 더 좁게 봄':<20} {stat['narrower']:,}"))
    else:
        # 필드가 아예 없는 로그다. 조용히 넘어가면 "어긋남 0%" 로 읽힌다.
        out.append((NAME, f"carried_turn_nos 없음 — 턴 순서 {stat['window']}개로 추정 중"))
    share = 100 * stat["with_tool"] / stat["turns"]
    out.append(("", f"{'tool_output 있는 턴':<20} {stat['with_tool']:,} ({share:.0f}%)"))
    return out


def process_data(ctx) -> tuple[list, list]:
    convs = {}
    for turn in ctx.turns:
        conv = getattr(turn, "conversation", None)
        if conv is not None:
            convs.setdefault(id(conv), conv)
    selected = getattr(ctx.selection, "selected", None)
    for sel in selected or []:
        conv = getattr(sel, "conversation", None)
        if conv is not None:
            convs.setdefault(id(conv), conv)
    if not convs:
        return [], []

    stat = measure(list(convs.values()))
    notes = []
    if stat["seen"] and stat["wider"]:
        notes.append(
            f"우리 추정이 챗봇보다 넓었던 턴 {stat['wider']}건 — "
            f"case14(맥락 상실) 오탐을 의심할 것.")
    return render(stat), notes
