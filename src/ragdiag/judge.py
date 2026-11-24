"""판정 오케스트레이션 — 결정 백엔드(kev) 호출과 디스크 캐시.

v4 는 호출이 두 종류다.

  decide    결정 백엔드. 범주 답 — 불만 판정 9문항 · 근거 판정 5문항 · 불만 부분 근거 판정 1문항.
            kev 가 없으면 일반 LLM 이 같은 문항에 JSON 으로 답하는 에뮬레이션으로 떨어진다
            (decide.LLMDecisionBackend).
  opine     일반 LLM. kev 가 모름이라 한 문항 하나를 이유와 함께 다시 묻는다 (second.py). 문장을
            만드는 자리는 이것뿐이고, 답은 결론이 아니라 sure=False 로 남는다.
            ④ 입력 축약(abbrev.py)의 요약도 여기로 간다 — kev 가 500 을 냈을 때만.

캐시가 있는 이유: 리포트 코드를 고칠 때마다 판정을 다시 사는 건 낭비다. 키는 (단계, 모델,
state 전문, 문항 전문) 의 해시라 입력이 한 글자라도 다르면 빗나간다 — 문항 문구를 고치면
저절로 다시 묻는다. v3 의 단계 이름(observe · sufficiency …)과 다르므로 옛 캐시는 안 맞는다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional, Protocol, TypeVar

from pydantic import BaseModel

from ragdiag import abbrev, settings
from ragdiag.backends import JudgeError, Usage
from ragdiag.decide import Answer, DecisionBackend, KevHTTPError, LLMDecisionBackend

T = TypeVar("T", bound=BaseModel)

# 결정 백엔드 단계. 캐시 키의 첫 칸이고 결과 파일 · 요약의 호출 수 집계 축이다.
DECISION_STAGES = ("complaint", "evidence", "complaint_evidence")


class Backend(Protocol):
    model: str

    def complete(
        self, system: str, user: str, out_model: type[T], contract_hint: str = ""
    ) -> tuple[T, Usage]: ...


class Judge:
    """decision 이 None 이면 일반 LLM(backend) 으로 에뮬레이션한다. 둘 다 없으면 못 돈다."""

    def __init__(self, backend: Optional[Backend] = None,
                 cache_dir: Optional[str | Path] = ".cache",
                 decision: Optional[DecisionBackend] = None):
        self.backend = backend
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._decision = decision

    # -- 백엔드 ---------------------------------------------------------------

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
        """이 실행이 쓴 일반 LLM 백엔드. 에뮬레이션일 때만 하나, 아니면 비어 있다."""
        return [self.backend] if self.backend is not None else []

    def models(self) -> dict[str, str]:
        """결과 파일 머리의 run.kev 에 실린다."""
        d = self.decision
        return {"decision": d.model if d is not None else "(없음)"}

    # -- 캐시 -------------------------------------------------------------------

    def _path(self, stage: str, *parts: str) -> Optional[Path]:
        if not self.cache_dir:
            return None
        key = hashlib.sha256("\x00".join([stage, *parts]).encode("utf-8")).hexdigest()[:24]
        return self.cache_dir / f"{stage}-{key}.json"

    # -- 결정 백엔드 ------------------------------------------------------------

    def decide(self, stage: str, state: Any,
               questions: dict[str, dict]) -> tuple[dict[str, Answer], Usage, Optional[dict]]:
        """범주 판정. 캐시 키는 (단계, 모델, state, 문항) 이다.

        셋째 값은 축약 재시도 기록 — kev 가 500 을 내서 입력을 줄여 다시 물었을 때만
        {"abbrev": 메모, "llm_usage": Usage, "llm_calls": n}, 아니면 None (abbrev.py).
        """
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
            # 옛 캐시는 {문항: 답} 그대로, 새 캐시는 {"answers": …, "abbrev": …}
            answers_raw = raw["answers"] if "answers" in raw else raw
            notes = raw.get("abbrev") if "answers" in raw else None
            retry = {"abbrev": notes, "llm_usage": Usage(), "llm_calls": 0} if notes else None
            return {k: Answer(**v) for k, v in answers_raw.items()}, Usage(), retry
        answers, usage, retry = self._decide_with_fallback(backend, stage, state, questions)
        if path:
            payload = {"answers": {k: a.__dict__ for k, a in answers.items()},
                       "abbrev": retry["abbrev"] if retry else []}
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return answers, usage, retry

    def _decide_with_fallback(self, backend, stage: str, state: Any, questions: dict[str, dict]):
        """원문으로 묻고, 크기 때문에 거절되면 입력을 줄여 **한 번** 더 묻는다. 그 외는 그대로 올린다."""
        try:
            answers, usage = backend.decide(state, questions)
            return answers, usage, None
        except KevHTTPError as e:
            if e.status not in abbrev.TOO_LARGE_STATUSES or not settings.ABBREV_ENABLED:
                raise
            shrunk = abbrev.abbreviate(stage, state, self)
            if shrunk is None:
                raise                                   # 이 단계에는 처방이 없다
            small, notes, llm_usage, llm_calls = shrunk
            if not notes:
                raise                                   # 어느 칸도 상한을 안 넘었다 — 크기 문제가 아니다
            try:
                answers, usage = backend.decide(small, questions)
            except KevHTTPError as e2:
                raise JudgeError(f"{e2} — 입력을 축약한 뒤에도 실패 ({abbrev.describe(notes)})") from e2
            return answers, usage, {"abbrev": notes, "llm_usage": llm_usage, "llm_calls": llm_calls}

    # -- 일반 LLM (2차 판정) -----------------------------------------------------

    def opine(self, stage: str, system: str, user: str, out_model: type[T],
              contract_hint: str = "") -> tuple[T, Usage]:
        """일반 LLM 한 번. 캐시 키는 (단계, 모델, 시스템, 사용자 프롬프트) 다."""
        if self.backend is None:
            raise RuntimeError("일반 LLM 백엔드가 없다 — 2차 판정은 llm 설정이 필요하다")
        path = self._path(f"o-{stage}", self.backend.model, system, user)
        if path and path.exists():
            return out_model.model_validate_json(path.read_text(encoding="utf-8")), Usage()
        parsed, usage = self.backend.complete(system, user, out_model, contract_hint)
        if path:
            path.write_text(parsed.model_dump_json(), encoding="utf-8")
        return parsed, usage
