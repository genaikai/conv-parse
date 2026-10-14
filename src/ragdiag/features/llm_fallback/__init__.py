"""판정 LLM 의 응답이 잘려서, 조건을 바꿔 되살린 호출.

살아났어도 다음 실행에서는 처음부터 그 조건으로 도는 게 낫다는 신호다.

예전 이름은 truncated 였다. 검증기 truncated(챗봇 답변이 잘린 것 · case8)와 이름이
겹쳐서 바꿨다 — 저쪽은 출력 JSON 의 checks 에 실리는 이름이라 이쪽을 바꾼다.
"""

from collections import Counter

NAME = "llm_fallback"


def process_data(ctx) -> tuple[list, list]:
    # 백엔드가 둘 이상이면(단계별 모델) 어느 모델이 잘렸는지가 곧 다음 실행의 조치다.
    # 하나로 합치면 --thinking off 를 어느 모델에 걸어야 하는지 알 수 없다.
    many = len(ctx.backends) > 1
    saved = [f"{label} · {b.model}" if many else label
             for b in ctx.backends for label in getattr(b, "fallbacks", [])]
    if not saved:
        return [], []

    metrics = [(NAME, f"{n:,} recovered by {label}")
               for label, n in Counter(saved).most_common()]
    notes = [f"추론이 답에 도달 못 해 {len(saved)}건을 조건을 바꿔 다시 물었다. "
             f"--thinking off 로 다시 돌릴 것."]
    return metrics, notes
