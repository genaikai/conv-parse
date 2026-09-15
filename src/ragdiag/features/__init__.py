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
from . import classification, classify, failures, filter_fp, llm_fallback

__all__ = ["FEATURES", "RunContext", "collect"]

FEATURES = (
    classify,          # [임시] 지금의 판정 순서를 통째로
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
