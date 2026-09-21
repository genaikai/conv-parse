"""한 번의 실행이 공유하는 상태. 기능들은 이걸 읽고, 판정 기능은 여기에 쓴다.

기능마다 필요한 것이 조금씩 달라서 인자를 하나씩 받게 하면 기능을 늘릴 때마다
호출부(`__main__.py`)를 고쳐야 한다. 진입점은 기능이 늘어도 손대지 않아야 하는
파일이라, 문맥을 한 덩이로 넘기고 각자 필요한 것만 꺼내 쓰게 한다.

**판정 기능은 앞 기능이 턴마다 남긴 것을 읽는다.** 관측이 있어야 충족도를 묻고,
충족도가 있어야 인용을 대조한다. 그래서 등록부의 순서가 곧 실행 순서다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunContext:
    selection: Any = None       # 고른 턴들. 턴 목록만 받았으면 None
    turns: list = field(default_factory=list)   # 턴마다 TurnResult 하나. 판정 기능이 채운다
    judge: Any = None           # LLM 호출 + 캐시. LLM 을 안 부르는 실행이면 None
    workers: int = 1            # LLM 기능이 동시에 처리하는 턴 수
    backend: Any = None         # 쓴 모델. fallbacks 가 붙어 있을 수 있다
    progress: bool = True       # LLM 단계의 진행을 stderr 에 한 줄로 (--no-progress 로 끈다)
    # 턴 단위 실행(run.mode=turn)에서 턴 하나가 끝날 때마다 불린다. 중간 결과 저장용.
    on_turn_done: Any = None

    def open_turns(self) -> list:
        """case 가 아직 정해지지 않았고 실패하지도 않은 턴. 판정 기능은 이것만 본다."""
        return [t for t in self.turns if t.classification is None and t.error is None]
