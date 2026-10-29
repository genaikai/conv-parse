"""몇 건이 어느 묶음으로 갔고 몇 건이 깨졌나. 어디서 멈췄나. kev 를 몇 번 불렀나."""

from collections import Counter

from ragdiag import taxonomy

from .._shared import bucket_counts

NAME = "classified"


def process_data(ctx) -> tuple[list, list]:
    failed = sum(1 for t in ctx.turns if t.error)
    kev = sum(t.n_kev_calls for t in ctx.turns)
    llm = sum(t.n_calls for t in ctx.turns)
    done = [t for t in ctx.turns if t.verdict]
    metrics = [
        (NAME, f"{len(ctx.turns) - failed:,} ok / {failed:,} failed"),
        ("kev calls", f"{kev:,}" + (f" (emulated by {llm:,} llm calls)" if llm else "")),
    ]
    buckets = bucket_counts(done)
    metrics += [("", f"{taxonomy.name(b):<6} {buckets[b]:,}") for b in taxonomy.BUCKETS if buckets[b]]
    stopped = Counter(t.verdict.stopped_at.split(" · ")[0] for t in done)
    if done:
        metrics.append(("stopped at", "  ".join(f"{s}:{stopped[s]:,}" for s in taxonomy.STEPS if stopped[s])))
    notes = []
    if failed:
        notes.append(f"판정 실패 {failed}건. 결과 파일의 error 필드를 볼 것.")
    review = buckets.get(taxonomy.REVIEW, 0)
    if review:
        notes.append(f"검토 {review}건 — kev 가 확신하지 못한 턴. 결과 파일의 review_at 이 막힌 문항을 센다.")
    missing = sum(1 for t in done if t.flags.get("앞 턴 누락") is True)
    if missing:
        notes.append(f"앞 턴 누락 {missing}건 — 많으면 로그 · 적재 쪽에 먼저 묻고 사용자 행 집계를 보류할 것.")
    return metrics, notes
