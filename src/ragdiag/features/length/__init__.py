"""길이 — case11. **재기만 하고 판정하지 않는다.**

다른 검증기는 답이 텍스트 밖에 확정돼 있다. 언어는 스크립트 비율로, 날짜는
달력으로, 파이썬은 파서로 정해진다. 길이는 그런 것이 없다 - 기준이 사용자
머릿속에 있다.

  "세 줄 이내로"   개행 3개? 60자×3? 요점 3개?   사람마다 다르다
  "다섯 문장으로"  한국어 만연체는 149자가 한 문장이다
  "짧게"          기준값이 없다. 정해도 임의값이다

실제로 그랬다. 503건에서 길이를 요구한 20건 전부 ok 가 나왔고, 그중 "세 줄
이내" 요구에 149자 만연체로 답한 것까지 통과했다 - 줄바꿈이 없어 1줄이라서다.
VAGUE_SHORT_MAX_CHARS=400 은 최대 답변이 370자인 데이터에서 한 번도 걸리지
않았다. **임의 상수 하나로 판정 실패를 덮은 것**이다.

그래서 측정만 남기고 판정을 버린다. verdict 는 언제나 undetermined 이고,
detail 에 세 측정값과 요구를 적는다. 라우팅에는 이미 경로가 있다 - 코드 근거가
없으면 case 는 유지하되 신뢰도를 낮춘다. 틀린 ok 를 내는 것보다 낫다.

실데이터에서 분포를 보고 기준을 정하게 되면, 그때 이 detail 만 읽으면 된다.
LLM 을 다시 돌릴 필요가 없다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

from ragdiag.results import Check

from .._shared import run_check

NAME = "length"


def count_sentences(text: str) -> int:
    """마침표 기준. 한국어 만연체는 이 셈으로 한 문장이 된다 - 그래서 이 값으로
    판정하지 않고 사람이 볼 수 있게 적기만 한다."""
    parts = [p for p in re.split(r"(?<=[.!?。])\s+", text.strip()) if p.strip()]
    return len(parts)


@dataclass
class LengthRequest:
    """Step 1이 뽑아내는 길이 요구. 수치가 없으면 kind='vague_short'."""

    kind: Literal["max_chars", "max_sentences", "max_lines", "vague_short"]
    value: Optional[int] = None


def measure_length(answer: str) -> str:
    chars = len(answer.strip())
    lines = len([l for l in answer.splitlines() if l.strip()])
    return f"{chars}자 · {count_sentences(answer)}문장 · {lines}줄"


def check_length(answer: str, requested: Optional[LengthRequest]) -> Check:
    """case11 — 길이 요구를 **재기만 한다.** 위반 판정은 하지 않는다.

    이 모듈의 다른 검증기와 성격이 다르다는 점이 중요하다. 여기서 나온
    undetermined 는 "판정에 실패했다"가 아니라 "코드가 판정할 수 있는 것이
    아니다"라는 뜻이다. case16(말투·어조)이 검증기 없이 관측에만 의존하는 것과
    같은 자리인데, 길이는 숫자가 나온다는 이유로 검증기가 붙어 있었다.
    """
    measured = measure_length(answer)
    if requested is None:
        return Check("length", "not_applicable", f"길이 요구 없음 · {measured}")

    if requested.kind == "vague_short":
        asked = "모호한 짧게 요구"
    elif requested.value is None:
        asked = f"{requested.kind} (값 없음)"
    else:
        asked = f"{requested.kind} ≤ {requested.value}"
    return Check("length", "undetermined", f"요구 {asked} · {measured}",
                 evidence=["길이 기준은 사용자마다 달라 코드로 판정하지 않는다"])


def process_data(ctx) -> tuple[list, list]:
    return run_check(ctx, NAME, lambda t: check_length(
        t.case.llm_ans_on_last_q, _request(t.observation)))


def _request(obs) -> Optional[LengthRequest]:
    """관측이 뽑은 길이 요구. 요구가 없었으면 None - 그러면 not_applicable 이다."""
    if obs.requested_length_kind == "none":
        return None
    return LengthRequest(obs.requested_length_kind, obs.requested_length_value or None)
