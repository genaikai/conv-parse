"""기능 하나. 복사해서 쓰는 원본이다.

    cp -r src/<pkg>/features/template src/<pkg>/features/<기능>

그다음 `features/__init__.py` 의 등록부에 한 줄 더한다. 진입점·스키마·출력은 손대지 않는다.

**이 폴더 자체는 지우지 마라.** 새 기능을 기존 기능 하나를 베껴 만들면 그 기능만의 사정까지
따라간다. 원본이 있어야 깨끗한 데서 시작한다.

지켜야 하는 것:

- **`process_data(ctx) -> (metrics, notes)` 로 노출한다.** 등록부가 이 이름으로 부른다.
  낼 것이 없으면 빈 목록 둘을 돌려준다.
- **지표 이름 앞에 `NAME` 을 붙인다.** 여럿의 결과가 한 리포트에 모이므로 접두어가 없으면
  겹친다. 이어 붙이는 줄(`("", ...)`)은 앞 지표에 딸린 것이라 예외다.
- 판정 기능이면 열린 턴(`ctx.open_turns()`)만 보고, 턴마다 `StepResult` 를 `turn.steps` 에
  남기며, 닫을 때는 `turn.close(...)` 또는 `turn.review(...)` 로만 닫는다.
"""

NAME = "template"  # 폴더 이름과 같게 둔다. 지표 접두어로 쓰인다


def process_data(ctx) -> tuple[list, list]:
    """이 기능의 결과를 (지표, 노트) 로 돌려준다.

    ctx 는 `features/_context.py` 의 RunContext — 한 번의 판정이 남긴 것 전부다.
    실데이터의 개별 값·식별자는 넣지 않는다. 세는 것까지다.
    """
    return [], []
