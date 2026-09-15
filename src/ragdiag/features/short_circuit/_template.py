"""규칙 하나. 복사해서 쓰는 원본이다 — 이름 앞 밑줄은 규칙이 아니라는 표시다.

    cp _template.py <규칙>.py        그다음 __init__.py 의 RULES 에 한 줄 더한다

지켜야 하는 것:

- **코드만 쓴다.** observe 보다 앞이라 관측 · 충족도는 아직 없다. 읽을 수 있는 것은
  turn.case (질문 · 답변 · 불만 · 청크) 뿐이다. 다른 값이 필요하면 Case 에 필드를 더한다
- **걸리지 않았으면 violated 가 아닌 Check 를 돌려준다.** 결과는 걸리든 안 걸리든
  checks[NAME] 으로 출력에 남는다
- CASE 는 taxonomy 에 있는 case 여야 한다 (tests/test_features.py 가 확인한다)
"""

from ragdiag.results import Check

NAME = "template"           # 파일 이름과 같게 둔다. checks 의 키가 된다
CASE = "case0"              # 걸리면 확정할 case
REASON = "무엇에 걸렸는지 한 구절"
NOTES = ()                  # 분류에 함께 실을 주의 사항


def check(turn) -> Check:
    """이 턴이 규칙에 걸리는가.

    ⭐ TODO: 실제 조건을 여기에. 지금은 아무것도 보지 않는다.
    """
    return Check(NAME, "not_applicable", "템플릿 — 아무것도 보지 않는다")
