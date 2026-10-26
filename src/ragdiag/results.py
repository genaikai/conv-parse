"""턴 하나의 판정 결과. 기능들이 채우고 출력이 읽는다.

기능 여럿이 같은 턴 객체에 자기 결과를 쓴다 — 관측 · 검증기 · 충족도 · 주장 · 후보 ·
분류. 그래서 이 모양들은 어느 한 기능의 것이 아니라 공유 계약이다. 기능끼리는
**이 필드로만** 만난다 (docs/design/taxonomy_v3_plan.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from ragdiag import taxonomy
from ragdiag.backends import Usage
from ragdiag.schema import Case, Claims, Observation
from ragdiag.verify import QuoteCheck

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
class ChunkSupport:
    """③ 충족도 — 청크 하나가 요구에 답하나. p 는 kev 의 P(yes)."""

    chunk_index: int
    p: float
    source: str = ""


@dataclass
class Sufficiency:
    """청크 단위 판정을 코드가 집계한 것. scope 는 own(이 턴) · carried(과거)."""

    scope: str
    need: str
    supports: list[ChunkSupport] = field(default_factory=list)
    verdict: str = "insufficient"            # sufficient · partial · insufficient
    verified: Optional[bool] = None          # ⑦ 2차 검증 결과. 안 돌렸으면 None

    @property
    def evidence(self) -> list[int]:
        from ragdiag import settings
        return [s.chunk_index for s in self.supports if s.p >= settings.CHUNK_EVIDENCE_P]

    @property
    def max_p(self) -> float:
        return max((s.p for s in self.supports), default=0.0)


@dataclass
class ClaimVerdict:
    text: str
    expected_source: str
    verdict: str                              # supported · contradicted · not_found · unverified · tool_ok · tool_mismatch
    p: float = 0.0
    chunk_indices: list[int] = field(default_factory=list)


@dataclass
class Candidate:
    """중재에 올라가는 후보 라벨 하나. 등급의 뜻은 taxonomy_v3.md."""

    label: str
    grade: int
    reason: str
    tags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def order(self) -> int:
        try:
            return taxonomy.ORDER.index(self.label)
        except ValueError:
            return len(taxonomy.ORDER)

    def as_dict(self) -> dict:
        return {"label": self.label, "grade": self.grade, "reason": self.reason,
                "tags": list(self.tags)}


@dataclass
class Classification:
    primary_case: str
    confidence: str
    reason: str
    secondary_cases: list[str] = field(default_factory=list)   # 태그 중 라벨 꼴(`G1`)인 것
    notes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    grade: int = 0
    flags: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)

    def as_dict(self) -> dict:
        payload = taxonomy.describe(self.primary_case)
        payload.update(
            confidence=self.confidence,
            grade=self.grade,
            reason=self.reason,
            tags=list(self.tags),
            secondary_cases=[taxonomy.describe(c) for c in self.secondary_cases],
            flags=list(self.flags),
            events=list(self.events),
            candidates=[c.as_dict() for c in self.candidates],
            notes=self.notes,
        )
        return payload


@dataclass
class TurnResult:
    case: Case
    # ③ 무결성 · 이벤트
    flags: list[str] = field(default_factory=list)          # C1 · C2
    events: list[str] = field(default_factory=list)         # U2
    # ① 읽기 — kev P(읽을 수 없다). 안 돌렸으면 None
    legibility_p: Optional[float] = None
    # ⑤ 관측. 범주는 kev, 텍스트는 LLM. 둘을 합친 것이 observation.
    observation: Optional[Observation] = None
    # 문항 id → 확률 분포 (kev 답 그대로). 신뢰 등급과 출력이 읽는다.
    probabilities: dict[str, Any] = field(default_factory=dict)
    # 요구 확인 (코드) · 조건 인용 대조 (코드)
    request: Optional[QuoteCheck] = None
    history: Optional[QuoteCheck] = None
    # ⑥ 코드 검증기
    checks: dict[str, Check] = field(default_factory=dict)
    # ③ 충족도 — scope 별. "own" · "carried" · "own:need" · "carried:need"
    sufficiency: dict[str, Sufficiency] = field(default_factory=dict)
    # ④ 주장
    claims: Optional[Claims] = None
    claim_verdicts: list[ClaimVerdict] = field(default_factory=list)
    # ⑤ memory 반영: reflected · ignored · contradicted. 안 돌렸으면 None
    memory_use: Optional[str] = None
    memory_p: float = 0.0
    # ⑥ 일관성 — 앞 답변 인덱스 → P(모순)
    consistency: dict[int, float] = field(default_factory=dict)
    # 조건부 인용 — 전달본용
    quotes: list[dict] = field(default_factory=list)
    # 중재
    candidates: list[Candidate] = field(default_factory=list)
    classification: Optional[Classification] = None
    error: Optional[str] = None
    usage: Usage = field(default_factory=Usage)
    n_calls: int = 0           # 일반 LLM 호출
    n_kev_calls: int = 0       # 결정 백엔드 호출

    # ---- 편의 ----
    def content_complaint(self) -> bool:
        obs = self.observation
        return obs is not None and obs.complaint_target in ("content_missing", "content_wrong")

    def doc_question(self) -> bool:
        from ragdiag.schema import DOC_DOMAINS
        obs = self.observation
        return obs is not None and obs.question_domain in DOC_DOMAINS

    def best_sufficiency(self) -> Optional[Sufficiency]:
        """own 이 먼저, 그다음 carried. need 로 좁힌 판정이 있으면 그쪽."""
        for key in ("own:need", "own", "carried:need", "carried"):
            if key in self.sufficiency:
                return self.sufficiency[key]
        return None

    def overall_verdict(self) -> Optional[str]:
        """own 과 carried 를 합친 충족도. 어느 한쪽이라도 sufficient 면 sufficient."""
        if not self.sufficiency:
            return None
        verdicts = [s.verdict for s in self.sufficiency.values()]
        if "sufficient" in verdicts:
            return "sufficient"
        if "partial" in verdicts:
            return "partial"
        return "insufficient"

    def add_candidate(self, label: str, grade: int, reason: str,
                      tags: Optional[list[str]] = None,
                      notes: Optional[list[str]] = None) -> Candidate:
        c = Candidate(label, grade, reason, list(tags or []), list(notes or []))
        self.candidates.append(c)
        return c
