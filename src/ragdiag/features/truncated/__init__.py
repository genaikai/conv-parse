"""잘려서 조건을 바꿔 되살린 호출.

살아났어도 다음 실행에서는 처음부터 그 조건으로 도는 게 낫다는 신호다.
"""

from collections import Counter

NAME = "truncated"


def process_data(ctx) -> tuple[list, list]:
    saved = getattr(ctx.backend, "fallbacks", [])
    if not saved:
        return [], []

    metrics = [(NAME, f"{n:,} recovered by {label}")
               for label, n in Counter(saved).most_common()]
    notes = [f"추론이 답에 도달 못 해 {len(saved)}건을 조건을 바꿔 다시 물었다. "
             f"--thinking off 로 다시 돌릴 것."]
    return metrics, notes
