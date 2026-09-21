"""기능 등록부. 여기 적힌 순서대로 실행된다.

**기능은 판정만이 아니다.** 같은 입력을 읽어 결과를 내는 독립 단위면 무엇이든
기능이다 — LLM 판정도, 코드 검증도, 진리표도, 분포 집계도.

판정 기능은 앞 기능이 턴마다 남긴 것을 읽는다. 그래서 **FEATURES 의 순서가 곧 실행
순서**이고, 판정 순서가 적힌 곳은 여기뿐이다. 집계 기능은 판정이 끝난 뒤에 와서
결과를 읽기만 한다.

전에는 지표들이 `__main__.py` 안에 흩어져 있었다. 지표를 하나 더 내려면 진입점을
고쳐야 했는데, 진입점은 기능이 늘어도 손대지 않아야 하는 파일이다.

기능을 만들려면 둘이면 된다:

    cp -r src/<pkg>/features/template src/<pkg>/features/<기능>
    # 아래 FEATURES 에 한 줄 더한다
"""

from ._context import RunContext
from . import (
    arithmetic,
    citation,
    classification,
    complaint_quote,
    dates,
    failures,
    filter_fp,
    format,
    grounding,
    history_quote,
    injection,
    language,
    length,
    llm_fallback,
    observe,
    pii,
    python_syntax,
    quoted_spans,
    request_quote,
    route,
    short_circuit,
    sql_shape,
    sufficiency,
)

__all__ = ["CHECKS", "FEATURES", "RunContext", "collect"]

# 코드 검증기. LLM 없이 문자열만 본다 - 언어가 맞는지, 답변이 끊겼는지, 등식이 맞는지는
# 문자열만 보면 안다. LLM 에 맡기면 비용도 들지만 무엇보다 같은 입력에 다른 답이 나온다.
# 서로의 결과를 읽지 않으므로 이 안의 순서는 판정에 영향이 없다 (출력에 실리는 순서다).
CHECKS = (
    pii,
    quoted_spans,
    python_syntax,
    sql_shape,
    arithmetic,
    dates,
    injection,
    language,          # 이 셋은 관측이 뽑은 요구값을 읽는다 - observe 뒤여야 한다
    format,
    length,
)

FEATURES = (
    short_circuit,     # LLM 전에 case 를 확정하는 규칙들 (규칙끼리의 순서는 그 안의 RULES)
    observe,           # Step 1 관측 · LLM
    complaint_quote,   # "불만 아님" 의 근거를 후속 발화와 대조
    request_quote,     # 요구의 인용을 이전 질문들과 대조 — 없으면 요구를 지운다
    history_quote,     # "이전 조건을 어겼다" 의 인용을 앞 질문들과 대조 — 없으면 무효
    *CHECKS,           # 코드 검증기
    sufficiency,       # Step 2 충족도 · LLM
    citation,          # 판정자의 인용을 원문과 대조
    grounding,         # Step 3 근거 활용 · LLM
    route,             # 진리표 → case
    # 여기부터는 집계. 화면에 뜨는 순서다 — 사람이 사이클 사이에 눈으로 대조하므로
    # 순서를 바꾸지 않는다.
    classification,
    llm_fallback,
    filter_fp,
    failures,
)


def collect(ctx: RunContext) -> tuple[list, list]:
    """기능 전부를 순서대로 돌리고 지표와 노트를 합친다."""
    metrics: list = []
    notes: list = []
    seen: set = set()

    for feature in FEATURES:
        got, said = feature.process_data(ctx)
        for name, _ in got:
            # 빈 이름은 앞 지표에 딸린 줄이라 겹침을 보지 않는다.
            if not name:
                continue
            if name in seen:
                # 조용히 두 번 찍으면 같은 것이 두 줄로 보이고, 사람은 어느 쪽을
                # 옮겨 적어야 할지 모른다. 시끄럽게 죽는 쪽이 낫다.
                raise KeyError(
                    f"{feature.NAME} 의 지표 이름이 겹친다: {name}. "
                    f"지표 이름 앞에 NAME 을 붙여라"
                )
            seen.add(name)
        metrics += got
        notes += said
    return metrics, notes
