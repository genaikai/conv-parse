"""몇 건이 분류됐고 몇 건이 깨졌나. LLM 을 몇 번 불렀나."""

from .._shared import top_cases

NAME = "classified"


def process_data(ctx) -> tuple[list, list]:
    failed = sum(1 for t in ctx.turns if t.error)
    calls = sum(t.n_calls for t in ctx.turns)
    metrics = [
        (NAME, f"{len(ctx.turns) - failed:,} ok / {failed:,} failed"),
        ("llm calls", f"{calls:,}"),
    ]
    metrics += [("", f"{case_id:<14} {n:,}") for case_id, n in top_cases(ctx.turns)]

    notes = []
    if failed:
        notes.append(f"분류 실패 {failed}건. 결과 파일의 error 필드를 볼 것.")
    return metrics, notes
