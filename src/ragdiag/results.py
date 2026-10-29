"""턴 하나의 판정 결과. 기능들이 채우고 출력이 읽는다 (v4).

기능 넷(코드 확정 · 불만 판정 · 근거 판정 · 불만 부분 근거 판정)이 같은 턴 객체에 자기
칸(StepResult)을 남기고, 닫을 때 Verdict 를 쓴다. 기능끼리는 **이 필드로만** 만난다.

StepResult.answers 의 키는 문항 **id** 다. 결과 파일에 실을 때 output 이 questions.TEXT 의
문장으로 바꾼다 — 문장은 사람이 읽는 것이고, 코드는 id 로 찾는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ragdiag import questions, settings, taxonomy
from ragdiag.backends import Usage
from ragdiag.decide import Answer
from ragdiag.schema import Case

YES = "예"
NO = "아니오"
UNSURE = "모름"

# choice 문항의 선택지 → 결과 파일에 쓰는 말.
CHOICE_TEXT = {"all": "전부", "partial": "일부", "none": "없음"}


def read_noul(answer: Answer) -> str:
    """P(예) 를 세 갈래로. 임계 하나(settings.KEV_CONFIDENT)로 예/아니오를 가르고 사이는 모름."""
    # 1 - 0.9 는 0.0999… 라 p=0.1 이 모름으로 샌다. 소수 여섯째 자리에서 맞춘다.
    p = round(answer.p, 6)
    if p >= round(settings.KEV_CONFIDENT, 6):
        return YES
    if p <= round(1 - settings.KEV_CONFIDENT, 6):
        return NO
    return UNSURE


def read_choice(answer: Answer) -> str:
    """최빈 선택지의 p 가 임계 이상이면 그 선택지 id, 아니면 모름."""
    if answer.choice and answer.p >= settings.KEV_CONFIDENT:
        return answer.choice
    return UNSURE


def answer_payload(answer: Answer) -> dict:
    """결과 파일의 답 한 칸 — {"answer": 말, "p": 확률}."""
    if answer.type == "noul":
        return {"answer": read_noul(answer), "p": round(answer.p, 3)}
    picked = read_choice(answer)
    return {"answer": CHOICE_TEXT.get(picked, picked), "p": round(answer.p, 3)}


@dataclass
class StepResult:
    step: str                                   # taxonomy.STEP_*
    rules: Optional[dict[str, str]] = None      # 코드 확정: 규칙 id → 예 · 아니오 · 보지 않음
    answers: Optional[dict[str, Any]] = None    # kev 단계: 문항 id → answer_payload 또는 SKIPPED


@dataclass
class Verdict:
    bucket: str            # taxonomy.BUCKETS 의 id
    sure: bool             # 검토면 False
    stopped_at: str        # 단계 이름. 검토면 "단계 · 문항 문장"
    because: str           # taxonomy.BECAUSE 의 고정 문장 또는 because_review
    where: list[str] = field(default_factory=list)   # 근거 판정을 지난 턴만. 칸 이름(한국어)


@dataclass
class TurnResult:
    case: Case
    steps: list[StepResult] = field(default_factory=list)
    verdict: Optional[Verdict] = None
    flags: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    usage: Usage = field(default_factory=Usage)
    n_calls: int = 0           # 일반 LLM 호출 (kev 에뮬레이션일 때만 0 이 아니다)
    n_kev_calls: int = 0       # 결정 백엔드 요청

    @property
    def is_open(self) -> bool:
        """아직 묶음이 정해지지 않았고 실패하지도 않았다. 판정 기능은 이런 턴만 본다."""
        return self.verdict is None and self.error is None

    def close(self, bucket: str, step: str, because: str,
              where: Optional[list[str]] = None) -> None:
        self.verdict = Verdict(bucket=bucket, sure=True, stopped_at=step, because=because,
                               where=list(where or []))

    def review(self, step: str, question_id: str, p: float) -> None:
        """모름 — 그 문항에서 멈추고 검토로 닫는다. 막힌 자리가 stopped_at 에 남는다."""
        text = questions.TEXT[question_id]
        self.verdict = Verdict(bucket=taxonomy.REVIEW, sure=False,
                               stopped_at=taxonomy.stopped_at_review(step, text),
                               because=taxonomy.because_review(step, text, p), where=[])
