"""어느 단계에서 깨졌나.

관측에서 몰려 깨지면 프롬프트·토큰 문제고, 흩어져 깨지면 서버·입력 문제다.
조치가 갈리므로 단계별로 센다.
"""

from collections import Counter

NAME = "failed at"


def process_data(ctx) -> tuple[list, list]:
    if not ctx.outcome.n_failed:
        return [], []

    stages = Counter(r.error.split("]")[0].lstrip("[")
                     for r in ctx.results if r.error and r.error.startswith("["))
    return [(NAME, f"{stage:<14} {n:,}") for stage, n in stages.most_common()], []
