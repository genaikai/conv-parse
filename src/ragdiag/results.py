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
LEAN_NO = "아니오 (기울기)"     # 확신은 없지만 아니오 쪽으로 기울어 다음 문항으로 넘긴 답

# 확률의 반올림 자리. 판정(read_*)과 결과 파일(answer_payload)이 같은 자리를 쓴다.
DECIMALS = 3

# choice 문항의 선택지 → 결과 파일에 쓰는 말.
CHOICE_TEXT = {"all": "전부", "partial": "일부", "none": "없음"}


def read_noul(answer: Answer) -> str:
    """P(예) 를 세 갈래로. 임계 하나(settings.KEV_CONFIDENT)로 예/아니오를 가르고 사이는 모름."""
    # 판정과 표시가 같은 자리에서 반올림한다 — 결과 파일에 0.9 로 보이는 값은 예여야 한다.
    # (1 - 0.9 는 0.0999… 라 반올림 없이는 p=0.1 이 모름으로 샌다.)
    p = round(answer.p, DECIMALS)
    if p >= round(settings.KEV_CONFIDENT, DECIMALS):
        return YES
    if p <= round(1 - settings.KEV_CONFIDENT, DECIMALS):
        return NO
    return UNSURE


def read_gate(answer: Answer) -> str:
    """"아니오 → 다음 문항" 인 문항의 읽기. 예는 결론이라 임계 그대로, 아니오는 기울기면 된다.

    결론을 내는 답은 되돌릴 수 없고, 다음 문항으로 넘기는 답은 뒤에서 또 본다. 그래서 P(예) 가
    KEV_PASS_THROUGH 이하면 확신이 없어도 LEAN_NO 로 넘긴다. 예 쪽으로 기운 사이는 여전히 모름이다.
    불만 판정 2~8 에만 쓴다 — 1 은 아니오가 정상(결론)이고, 근거 판정 · 불만 부분은 양쪽 다 결론이다.
    """
    verdict = read_noul(answer)
    if verdict == UNSURE and round(answer.p, DECIMALS) <= round(settings.KEV_PASS_THROUGH, DECIMALS):
        return LEAN_NO
    return verdict


def read_choice(answer: Answer) -> str:
    """최빈 선택지의 p 가 임계 이상이면 그 선택지 id, 아니면 모름."""
    if answer.choice and round(answer.p, DECIMALS) >= round(settings.KEV_CONFIDENT, DECIMALS):
        return answer.choice
    return UNSURE


def answer_payload(answer: Answer, reader=read_noul) -> dict:
    """결과 파일의 답 한 칸 — {"answer": 말, "p": 확률}. reader 는 noul 을 읽는 규칙(read_noul · read_gate).

    p 는 **보인 답의 확신**이다. "아니오 0.95" 가 확신 있는 아니오로 읽혀야 한다 — P(예) 를 그대로
    실으면 아니오 행마다 0.05 가 찍혀 확신 없음처럼 보인다. 모름일 때만 P(예) 그대로 — 어느 쪽으로
    기울었는지가 검토자에게 단서다. 기울기로 넘긴 아니오는 말로 구별되고 p 는 아니오의 확신이다.
    """
    if answer.type == "noul":
        verdict = reader(answer)
        p = answer.p if verdict == UNSURE else max(answer.p, 1 - answer.p)
        return {"answer": verdict, "p": round(p, DECIMALS)}
    picked = read_choice(answer)
    return {"answer": CHOICE_TEXT.get(picked, picked), "p": round(answer.p, DECIMALS)}


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
    second_pass: str = ""  # 2차 판정이 있었으면 "단계 · 문항 — kev p 0.62, LLM 아니오" (여럿이면 " / ")


@dataclass
class TurnResult:
    case: Case
    steps: list[StepResult] = field(default_factory=list)
    verdict: Optional[Verdict] = None
    flags: dict[str, Any] = field(default_factory=dict)
    # 2차 판정 기록 — {step, qid, kev_p, llm}. 하나라도 있으면 이 턴은 sure=False 다.
    second: list[dict] = field(default_factory=list)
    error: Optional[str] = None
    usage: Usage = field(default_factory=Usage)
    n_calls: int = 0           # 일반 LLM 호출 (kev 에뮬레이션일 때만 0 이 아니다)
    n_kev_calls: int = 0       # 결정 백엔드 요청

    @property
    def is_open(self) -> bool:
        """아직 묶음이 정해지지 않았고 실패하지도 않았다. 판정 기능은 이런 턴만 본다."""
        return self.verdict is None and self.error is None

    def second_pass_text(self) -> str:
        return " / ".join(taxonomy.second_pass_text(s["step"], questions.TEXT[s["qid"]], s["kev_p"], s["llm"])
                          for s in self.second)

    def close(self, bucket: str, step: str, because: str,
              where: Optional[list[str]] = None) -> None:
        # 2차 판정을 거친 턴은 묶음을 받아도 확신이 아니다 — kev 가 모름이라 한 사실은 안 지워진다.
        self.verdict = Verdict(bucket=bucket, sure=not self.second, stopped_at=step, because=because,
                               where=list(where or []), second_pass=self.second_pass_text())

    def review(self, step: str, question_id: str, p: float) -> None:
        """모름 — 그 문항에서 멈추고 검토로 닫는다. 막힌 자리가 stopped_at 에 남는다."""
        text = questions.TEXT[question_id]
        self.verdict = Verdict(bucket=taxonomy.REVIEW, sure=False,
                               stopped_at=taxonomy.stopped_at_review(step, text),
                               because=taxonomy.because_review(step, text, p), where=[],
                               second_pass=self.second_pass_text())
