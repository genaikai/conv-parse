"""한 번의 판정이 남긴 것. 기능들은 이걸 읽어 지표를 낸다.

기능마다 필요한 것이 조금씩 달라서 인자를 하나씩 받게 하면 기능을 늘릴 때마다
호출부(`__main__.py`)를 고쳐야 한다. 진입점은 기능이 늘어도 손대지 않아야 하는
파일이라, 문맥을 한 덩이로 넘기고 각자 필요한 것만 꺼내 쓰게 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RunContext:
    selection: Any          # 고른 턴들
    results: list           # 턴마다의 판정 결과
    outcome: Any            # 합쳐진 결과 (n_failed, n_llm_calls, results)
    backend: Any            # 쓴 모델. fallbacks 가 붙어 있을 수 있다
