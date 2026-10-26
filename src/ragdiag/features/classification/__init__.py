"""몇 건이 분류됐고 몇 건이 깨졌나. LLM · kev 를 몇 번 불렀나. 등급 · 플래그 · 이벤트는 몇 건인가."""

from collections import Counter

from .._shared import top_cases

NAME = "classified"


def process_data(ctx) -> tuple[list, list]:
    failed = sum(1 for t in ctx.turns if t.error)
    calls = sum(t.n_calls for t in ctx.turns)
    kev = sum(t.n_kev_calls for t in ctx.turns)
    done = [t for t in ctx.turns if t.classification]
    metrics = [
        (NAME, f"{len(ctx.turns) - failed:,} ok / {failed:,} failed"),
        ("llm calls", f"{calls:,}"),
        ("kev calls", f"{kev:,}"),
    ]
    metrics += [("", f"{case_id:<14} {n:,}") for case_id, n in top_cases(ctx.turns)]

    grades = Counter(t.classification.grade for t in done)
    if done:
        metrics.append(("grade", "  ".join(f"{g}:{grades[g]:,}" for g in (4, 3, 2, 1, 0) if grades[g])))
    flags = Counter(f for t in done for f in t.classification.flags)
    events = Counter(e for t in done for e in t.classification.events)
    if flags:
        metrics.append(("integrity", "  ".join(f"{k}:{n:,}" for k, n in sorted(flags.items()))))
    if events:
        metrics.append(("events", "  ".join(f"{k}:{n:,}" for k, n in sorted(events.items()))))

    notes = []
    if failed:
        notes.append(f"분류 실패 {failed}건. 결과 파일의 error 필드를 볼 것.")
    if flags.get("C1"):
        notes.append(f"C1(앞 턴 누락) {flags['C1']}건 — 그 턴들은 G2 를 판정하지 않았다. "
                     "많으면 로그 · 적재 쪽에 먼저 묻고 G2 집계를 보류할 것.")
    low = grades[1] + grades[0]
    if low:
        notes.append(f"등급 1 · 0 이 {low}건 — 표본 검토 대상. 다른 등급과 같은 무게로 집계하지 말 것.")
    return metrics, notes
