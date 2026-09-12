"""판정 결과를 읽어 지표를 내는 기능들. 하나가 폴더 하나고, 이 파일이 등록부다.

**기능은 판정만이 아니다.** 같은 입력을 읽어 지표를 내는 독립 단위면 무엇이든 기능이다 —
여기 넷도 검출이 아니라 집계다(몇 건 깨졌나, 어디에 몰렸나).

`pipeline.py` 는 로그 → 필터 → Case → 판정 의 **순서 있는 단계**를 맡고, 여기는
그 결과를 **여러 각도로 읽는** 일을 맡는다. 성격이 달라서 가른다.

전에는 이 지표들이 `__main__.py` 안에 흩어져 있었다. 지표를 하나 더 내려면 진입점을
고쳐야 했는데, 진입점은 기능이 늘어도 손대지 않아야 하는 파일이다.

기능을 만들려면 둘이면 된다:

    cp -r src/<pkg>/features/template src/<pkg>/features/<기능>
    # 아래 FEATURES 에 한 줄 더한다
"""

from ._context import RunContext
from . import classification, failures, filter_fp, truncated

__all__ = ["FEATURES", "RunContext", "collect"]

# 화면에 뜨는 순서다. 사람이 사이클 사이에 눈으로 대조하므로 순서를 바꾸지 않는다.
FEATURES = (
    classification,
    truncated,
    filter_fp,
    failures,
)


def collect(ctx: RunContext) -> tuple[list, list]:
    """기능 전부를 돌리고 지표와 노트를 순서대로 합친다."""
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
