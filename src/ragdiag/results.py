"""턴 하나의 판정 결과. 기능들이 채우고 출력이 읽는다.

기능 여럿이 같은 턴 객체에 자기 결과를 쓴다 — 관측 · 검증기 · 충족도 · 분류. 그래서
이 모양들은 어느 한 기능의 것이 아니라 공유 코드다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from ragdiag import taxonomy
from ragdiag.backends import Usage
from ragdiag.schema import Case, GroundingCheck, Observation, SufficiencyJudgment
from ragdiag.verify import CitationCheck, QuoteCheck

Verdict = Literal["ok", "violated", "not_applicable", "undetermined"]


@dataclass
class Check:
    """코드 검증기 하나의 결과.

    verdict 의 네 값이 서로 다른 뜻이라는 게 중요하다:
      ok              요구를 지켰다
      violated        요구를 어겼다
      not_applicable  그런 요구가 애초에 없었다  (위반 아님)
      undetermined    요구는 있었지만 판정 근거가 부족하다  (조용히 ok로 넘기면 안 된다)
    """

    name: str
    verdict: Verdict
    detail: str = ""
    evidence: list[str] = field(default_factory=list)

    @property
    def violated(self) -> bool:
        return self.verdict == "violated"


@dataclass
class Classification:
    primary_case: str
    confidence: str
    reason: str
    secondary_cases: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        payload = taxonomy.describe(self.primary_case)
        payload.update(
            confidence=self.confidence,
            reason=self.reason,
            secondary_cases=[taxonomy.describe(c) for c in self.secondary_cases],
            notes=self.notes,
        )
        return payload


@dataclass
class TurnResult:
    case: Case
    observation: Optional[Observation] = None
    checks: dict[str, Check] = field(default_factory=dict)
    judgment: Optional[SufficiencyJudgment] = None
    citation: Optional[CitationCheck] = None
    grounding: Optional[GroundingCheck] = None
    # complaint_target="none" 주장의 인용 검증 결과. 그 외에는 None.
    complaint: Optional[QuoteCheck] = None
    classification: Optional[Classification] = None
    error: Optional[str] = None
    usage: Usage = field(default_factory=Usage)
    n_calls: int = 0
