"""판정 오케스트레이션.

호출을 3단계로 쪼갠 이유는 prompts.py에, 백엔드 차이는 backends.py에 적어두었다.
여기서는 단계 순서와 건너뛰기 규칙, 디스크 캐시, 케이스 단위 병렬, 그리고
**단계별 모델 선택**만 다룬다.

캐시가 있는 이유: 리포트 코드를 고칠 때마다 판정을 다시 사는 건 낭비다.
CLI 경로는 호출당 $0.05 안팎이라 특히 그렇다.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional, Protocol, TypeVar

from pydantic import BaseModel

from ragdiag import prompts
from ragdiag.backends import Usage
from ragdiag.schema import (
    Case,
    GroundingCheck,
    LegibilityCheck,
    Observation,
    SufficiencyJudgment,
)

T = TypeVar("T", bound=BaseModel)
DEFAULT_MODEL = "claude-opus-5"

# LLM 을 부르는 단계 전부. 캐시 키의 첫 칸이고, 단계별 모델을 고르는 키이기도 하다.
# 이름을 바꾸면 캐시가 통째로 무효화된다.
STAGES = ("observe", "sufficiency", "legibility", "grounding")


class Backend(Protocol):
    model: str

    def complete(
        self, system: str, user: str, out_model: type[T], contract_hint: str = ""
    ) -> tuple[T, Usage]: ...


class Judge:
    """단계마다 다른 모델을 쓸 수 있다.

    per_stage 에 적힌 단계만 그 백엔드로 가고, 나머지는 backend 로 간다. 쓰는 쪽은
    ⑨ 근거 활용처럼 **출력이 닫힌 집합 한 칸뿐인** 단계를 작은 모델로 내려 보는 것이다.

    캐시는 이미 (단계, 모델) 로 갈라져 있어서(_cache_path) 한 단계의 모델만 바꾸면
    그 단계의 캐시만 무효화된다. 나머지 단계는 다시 사지 않는다.
    """

    def __init__(self, backend: Optional[Backend] = None,
                 cache_dir: Optional[str | Path] = ".cache",
                 per_stage: Optional[dict[str, Backend]] = None):
        self.backend = backend
        self.per_stage = dict(per_stage or {})
        # 단계 이름을 틀리면 조용히 아무 일도 안 일어난다 - 기본 모델로 돌아 버리고
        # 결과만 보면 알 수 없다. 이 프로젝트에서 제일 비싼 모양의 결함이라 막는다.
        unknown = sorted(set(self.per_stage) - set(STAGES))
        if unknown:
            raise ValueError(f"모르는 판정 단계: {', '.join(unknown)} "
                             f"(가능: {', '.join(STAGES)})")
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def backend_for(self, stage: str) -> Optional[Backend]:
        return self.per_stage.get(stage) or self.backend

    def all_backends(self) -> list[Backend]:
        """이 실행이 실제로 쓴 백엔드 전부. 폴백 집계가 하나만 보면 절반을 놓친다."""
        seen: set[int] = set()
        out = []
        for backend in [self.backend, *self.per_stage.values()]:
            if backend is not None and id(backend) not in seen:
                seen.add(id(backend))
                out.append(backend)
        return out

    def models(self) -> dict[str, str]:
        """단계 → 그 단계를 판정한 모델. 결과 파일에 그대로 실린다.

        단계마다 모델이 갈리는 순간 "그 실행은 그 모델" 이 깨진다. 실데이터를 가지고
        나올 수 없는 환경에서 판정의 출처가 안 남으면 나중에 해석할 방법이 없다.
        """
        return {stage: (b.model if (b := self.backend_for(stage)) else DEFAULT_MODEL)
                for stage in STAGES}

    def _cache_path(self, stage: str, system: str, user: str) -> Optional[Path]:
        if not self.cache_dir:
            return None
        # backend가 없어도(추적 전용) 캐시 경로는 계산할 수 있어야 한다.
        backend = self.backend_for(stage)
        model = backend.model if backend else DEFAULT_MODEL
        key = hashlib.sha256(
            "\x00".join([stage, model, system, user]).encode("utf-8")
        ).hexdigest()[:24]
        return self.cache_dir / f"{stage}-{key}.json"

    def _call(
        self, stage: str, system: str, user: str, out_model: type[T]
    ) -> tuple[T, Usage]:
        """판정 결과와 **그 호출의** 사용량을 함께 반환한다.

        공유 카운터를 두고 케이스마다 그 차이를 재면 스레드가 섞여서 사용량이
        엉뚱하게 부풀려진다. 호출자가 지역 변수에 쌓게 하면 락도 필요 없다.
        캐시 적중은 실제 호출이 아니므로 빈 Usage를 돌려준다.
        """
        path = self._cache_path(stage, system, user)
        if path and path.exists():
            return out_model.model_validate_json(path.read_text(encoding="utf-8")), Usage()

        parsed, usage = self.backend_for(stage).complete(
            system, user, out_model, prompts.output_contract(out_model)
        )
        if path:
            path.write_text(parsed.model_dump_json(), encoding="utf-8")
        return parsed, usage

    def observe(self, case: Case) -> tuple[Observation, Usage]:
        """Step 1 — case 를 고르지 않고 관측 사실만 낸다."""
        return self._call(
            "observe", prompts.OBSERVE_SYSTEM,
            prompts.observe_user_message(case), Observation,
        )

    def judge_sufficiency_from(
        self, case: Case, obs
    ) -> tuple[SufficiencyJudgment, Usage]:
        """Step 2 - 관측이 뽑은 질문 · 요구로 문서 충족도를 판정한다."""
        return self._call(
            "sufficiency", prompts.SUFFICIENCY_SYSTEM,
            prompts.sufficiency_user_message(case, obs), SufficiencyJudgment,
        )

    def check_legibility(self, case: Case) -> tuple[LegibilityCheck, Usage]:
        return self._call(
            "legibility", prompts.LEGIBILITY_SYSTEM,
            prompts.legibility_user_message(case), LegibilityCheck,
        )

    def check_grounding(self, case: Case, question: str = "") -> tuple[GroundingCheck, Usage]:
        return self._call(
            "grounding", prompts.GROUNDING_SYSTEM,
            prompts.grounding_user_message(case, question), GroundingCheck,
        )
