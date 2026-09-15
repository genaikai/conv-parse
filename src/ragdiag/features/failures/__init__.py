"""어느 단계에서 깨졌나.

관측에서 몰려 깨지면 프롬프트·토큰 문제고, 흩어져 깨지면 서버·입력 문제다.
조치가 갈리므로 단계별로 센다.
"""

from collections import Counter

NAME = "failed at"


def process_data(ctx) -> tuple[list, list]:
    stages = Counter(t.error.split("]")[0].lstrip("[")
                     for t in ctx.turns if t.error and t.error.startswith("["))
    # 이름은 첫 줄에만 붙인다. 단계마다 붙이면 둘째 단계부터 등록부의 이름 겹침
    # 검사에 걸려 요약 전체가 죽는다 - 이어지는 줄은 빈 이름이 관례다.
    return [(NAME if i == 0 else "", f"{stage:<14} {n:,}")
            for i, (stage, n) in enumerate(stages.most_common())], []
