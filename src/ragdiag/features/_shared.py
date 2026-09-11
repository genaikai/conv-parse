"""기능 여럿이 같이 쓰는 것. 기능이 아니므로 이름 앞에 밑줄을 둔다.

둘 이상이 **같은 기준**을 써야 할 때만 여기로 올린다. 한 기능만 쓰는 것은 그 기능
폴더 안에 둔다 — 여기 올려두면 고칠 때 누가 영향받는지 알 수 없다.
"""

from collections import Counter


def top_cases(outcome, limit: int = 5):
    """상위 case 몇 개. 지표 이름은 사이클 사이에 바뀌지 않아야 한다."""
    counts = Counter(r.classification.primary_case
                     for r in outcome.results if r.classification)
    return counts.most_common(limit)
