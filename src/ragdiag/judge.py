"""판정 오케스트레이션 — 일반 LLM 호출과 결정 백엔드(kev) 호출, 그리고 디스크 캐시.

두 종류의 호출이 있다.

  complete  일반 LLM. 문장을 만들어야 하는 자리 — 질문 재구성(②b) · 주장 추출(④a) · 인용.
  decide    결정 백엔드. 범주 답 — 읽기 · 관측 12문항 · 충족도 · 2차 검증 · 주장별 판정 ·
            memory · 일관성. kev 가 없으면 일반 LLM 에뮬레이션으로 떨어진다 (decide.py).

캐시가 있는 이유: 리포트 코드를 고칠 때마다 판정을 다시 사는 건 낭비다. 키는 (단계,
모델, 입력 전문) 의 해시라 입력이 한 글자라도 다르면 빗나간다 — 풀이 달라지면 저절로
다시 묻는다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional, Protocol, TypeVar

from pydantic import BaseModel

from ragdiag import prompts
from ragdiag.backends import Usage
from ragdiag.decide import Answer, DecisionBackend, LLMDecisionBackend
from ragdiag.schema import (
    Case,
    Claims,
    GroundingCheck,
    LegibilityCheck,
    Observation,
    ObservationText,
    QuotePair,
    SufficiencyJudgment,
)

T = TypeVar("T", bound=BaseModel)
DEFAULT_MODEL = "claude-opus-5"

# 일반 LLM 단계. 캐시 키의 첫 칸이고 단계별 모델을 고르는 키다. 이름을 바꾸면 캐시가 통째로
# 무효화된다. 앞 넷은 옛 골든셋 러너가 아직 쓴다.
STAGES = ("observe", "sufficiency", "legibility", "grounding",
          "observe_text", "claims", "quotes")

# 결정 백엔드 단계. 캐시 키와 요약의 호출 수 집계에 쓴다.
DECISION_STAGES = ("legibility", "observe", "sufficiency", "verify", "claim",
                   "memory", "consistency")


class Backend(Protocol):
    model: str

    def complete(
        self, system: str, user: str, out_model: type[T], contract_hint: str = ""
    ) -> tuple[T, Usage]: ...


class Judge:
    """단계마다 다른 모델을 쓸 수 있다. decision 이 None 이면 일반 LLM 으로 에뮬레이션한다."""

    def __init__(self, backend: Optional[Backend] = None,
                 cache_dir: Optional[str | Path] = ".cache",
                 per_stage: Optional[dict[str, Backend]] = None,
                 decision: Optional[DecisionBackend] = None):
        self.backend = backend
        self.per_stage = dict(per_stage or {})
        unknown = sorted(set(self.per_stage) - set(STAGES))
        if unknown:
            raise ValueError(f"모르는 판정 단계: {', '.join(unknown)} "
                             f"(가능: {', '.join(STAGES)})")
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._decision = decision

    # -- 백엔드 선택 ----------------------------------------------------------

    def backend_for(self, stage: str) -> Optional[Backend]:
        return self.per_stage.get(stage) or self.backend

    @property
    def decision(self) -> Optional[DecisionBackend]:
        if self._decision is None and self.backend is not None:
            self._decision = LLMDecisionBackend(self.backend)
        return self._decision

    @property
    def decision_kind(self) -> str:
        d = self.decision
        return d.kind if d is not None else "none"

    def all_backends(self) -> list[Backend]:
        seen: set[int] = set()
        out = []
        for backend in [self.backend, *self.per_stage.values()]:
            if backend is not None and id(backend) not in seen:
                seen.add(id(backend))
                out.append(backend)
        return out

    def models(self) -> dict[str, str]:
        """단계 → 모델. 결과 파일의 judged_by 에 실린다."""
        out = {stage: (b.model if (b := self.backend_for(stage)) else DEFAULT_MODEL)
               for stage in STAGES}
        d = self.decision
        out["decision"] = d.model if d is not None else "(없음)"
        return out

    # -- 캐시 -------------------------------------------------------------------

    def _cache_path(self, stage: str, system: str, user: str) -> Optional[Path]:
        """일반 LLM 단계의 캐시 파일. 키에 그 단계의 모델이 들어간다 - 단계 하나의 모델만 바꾸면
        그 단계의 캐시만 무효화되고, 같은 단계라도 모델이 다르면 섞이지 않는다."""
        if not self.cache_dir:
            return None
        backend = self.backend_for(stage)
        model = backend.model if backend else DEFAULT_MODEL
        return self._path(stage, model, system, user)

    def _path(self, stage: str, *parts: str) -> Optional[Path]:
        if not self.cache_dir:
            return None
        key = hashlib.sha256("\x00".join([stage, *parts]).encode("utf-8")).hexdigest()[:24]
        return self.cache_dir / f"{stage}-{key}.json"

    # -- 일반 LLM ---------------------------------------------------------------

    def _call(self, stage: str, system: str, user: str, out_model: type[T]) -> tuple[T, Usage]:
        backend = self.backend_for(stage)
        path = self._cache_path(stage, system, user)
        if path and path.exists():
            return out_model.model_validate_json(path.read_text(encoding="utf-8")), Usage()
        parsed, usage = backend.complete(system, user, out_model, prompts.output_contract(out_model))
        if path:
            path.write_text(parsed.model_dump_json(), encoding="utf-8")
        return parsed, usage

    def observe_text(self, case: Case) -> tuple[ObservationText, Usage]:
        """②b — 질문 재구성 · 요구값 · 조건 인용. 범주는 묻지 않는다."""
        return self._call("observe_text", prompts.OBSERVE_TEXT_SYSTEM,
                          prompts.observe_user_message(case), ObservationText)

    def extract_claims(self, case: Case) -> tuple[Claims, Usage]:
        """④a — 답변의 사실 주장과 기대 출처."""
        return self._call("claims", prompts.CLAIMS_SYSTEM,
                          prompts.claims_user_message(case), Claims)

    def quote_pair(self, answer: str, source: str, what: str) -> tuple[QuotePair, Usage]:
        """조건부 인용 — 어긋나는 두 구절. 전달본용."""
        return self._call("quotes", prompts.QUOTES_SYSTEM,
                          prompts.quotes_user_message(answer, source, what), QuotePair)

    # -- 결정 백엔드 ------------------------------------------------------------

    def decide(self, stage: str, state: Any,
               questions: dict[str, dict]) -> tuple[dict[str, Answer], Usage]:
        """범주 판정. 캐시 키는 (단계, 모델, state, 문항) 이다."""
        if stage not in DECISION_STAGES:
            raise ValueError(f"모르는 결정 단계: {stage} (가능: {', '.join(DECISION_STAGES)})")
        backend = self.decision
        if backend is None:
            raise RuntimeError("결정 백엔드가 없다 — kev 설정이나 일반 LLM 백엔드가 필요하다")
        state_text = json.dumps(state, ensure_ascii=False, sort_keys=True)
        q_text = json.dumps(questions, ensure_ascii=False, sort_keys=True)
        path = self._path(f"d-{stage}", backend.model, state_text, q_text)
        if path and path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            return {k: Answer(**v) for k, v in raw.items()}, Usage()
        answers, usage = backend.decide(state, questions)
        if path:
            path.write_text(json.dumps({k: a.__dict__ for k, a in answers.items()},
                                       ensure_ascii=False), encoding="utf-8")
        return answers, usage

    # -- 옛 단계. 골든셋 러너(__main__ --golden) 가 아직 쓴다 -------------------

    def observe(self, case: Case) -> tuple[Observation, Usage]:
        return self._call("observe", prompts.OBSERVE_SYSTEM,
                          prompts.observe_user_message(case), Observation)

    def judge_sufficiency_from(self, case: Case, obs) -> tuple[SufficiencyJudgment, Usage]:
        return self._call("sufficiency", prompts.SUFFICIENCY_SYSTEM,
                          prompts.sufficiency_user_message(case, obs), SufficiencyJudgment)

    def check_legibility(self, case: Case) -> tuple[LegibilityCheck, Usage]:
        return self._call("legibility", prompts.LEGIBILITY_SYSTEM,
                          prompts.legibility_user_message(case), LegibilityCheck)

    def check_grounding(self, case: Case, question: str = "") -> tuple[GroundingCheck, Usage]:
        return self._call("grounding", prompts.GROUNDING_SYSTEM,
                          prompts.grounding_user_message(case, question), GroundingCheck)
