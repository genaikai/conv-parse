"""몇 건이 분류됐고 몇 건이 깨졌나. LLM 을 몇 번 불렀나."""

from .._shared import top_cases

NAME = "classified"


def process_data(ctx) -> tuple[list, list]:
    metrics = [
        (NAME, f"{len(ctx.results) - ctx.outcome.n_failed:,} ok / "
               f"{ctx.outcome.n_failed:,} failed"),
        ("llm calls", f"{ctx.outcome.n_llm_calls:,}"),
    ]
    metrics += [("", f"{case_id:<14} {n:,}") for case_id, n in top_cases(ctx.outcome)]

    notes = []
    if ctx.outcome.n_failed:
        notes.append(f"분류 실패 {ctx.outcome.n_failed}건. 결과 파일의 error 필드를 볼 것.")
    return metrics, notes
