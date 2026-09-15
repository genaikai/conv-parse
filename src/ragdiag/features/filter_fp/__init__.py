"""필터가 넓게 잡아서 들어온 정상 턴.

case0 은 챗봇 지표가 아니라 **필터 지표**다. 필터는 실행 환경에 있어 여기서 못
고치므로, 어떤 eval 라벨에 몰리는지가 그쪽으로 돌아가는 유일한 피드백이다.

0 건이라고 좋은 게 아니다. 필터가 너무 좁아 놓치고 있다는 뜻일 수도 있어서,
필터 리포트와 짝으로 읽어야 한다.
"""

from collections import Counter

NAME = "filter FP"


def process_data(ctx) -> tuple[list, list]:
    # 턴 목록만 받아 판정한 경우(pipeline.judge_cases)에는 필터가 고른 원본이 없다.
    selected = getattr(ctx.selection, "selected", None)
    if not selected:
        return [], []

    normal = [sel for sel, t in zip(selected, ctx.turns)
              if t.classification and t.classification.primary_case == "case0"]
    if not normal:
        return [], []

    share = 100 * len(normal) / max(1, len(ctx.turns))
    metrics = [(NAME, f"{len(normal):,} / {len(ctx.turns):,} ({share:.0f}%) case0")]
    metrics += [("", f"{label[:20]:<20} {n:,}") for label, n
                in Counter(s.turn.eval_result for s in normal).most_common(3)]
    notes = [f"필터 오탐 후보 {len(normal)}건. 챗봇이 아니라 필터를 볼 것."]
    return metrics, notes
