"""case9 — 서비스 자원 부족 응답

모델 자원을 확보하지 못했을 때 서비스 계층이 내보내는 **확정 문구**다. LLM 이
생성한 답이 아니라 정해진 문자열이므로 코드로 판정한다 - 신뢰도 high 다.

이걸 따로 잡지 않으면 판정자가 "답변이 거절했다"로 읽어 case28(보안 정책상
답변 불가)으로 간다. 실제로 그 오분류가 많이 나왔다. 서버 자원 문제를 보안
정책 문제로 세면 고칠 곳을 정반대로 가리킨다 - 한쪽은 인프라 증설이고
다른 쪽은 권한 정책이다.

**판정은 확정 문구 대조 하나다.** 공백 · 줄바꿈을 전부 지운 답변 안에 확정 문구가
(역시 공백을 지운 채로) 들어 있으면 case9 다. 앞뒤에 무엇이 붙었든, 답변이 얼마나
길든 상관없다.

비슷한 문구는 잡지 않는다. 예전에는 보조 표지("서버에 부하" · "잠시 후 다시" …)가 두 개
겹치면 잡았는데, 서버 부하를 주제로 한 짧은 정상 답변까지 case9 로 보냈다. case9 는
LLM 판정을 건너뛰므로 오탐이 나면 그 턴의 진짜 원인이 통째로 사라진다. 배포마다
문구가 다르면 설정의 service_error.templates 에 줄을 더한다.
"""

import re

from ragdiag import settings
from ragdiag.results import Check

NAME = "service_error"          # 결과가 checks["service_error"] 로 남는다
CASE = "case9"
REASON = "서비스 자원 부족 안내 문구"
NOTES = (
    "모델이 답을 만든 적이 없다. 검색·생성 품질 집계에서 분리할 것.",
    "LLM 판정을 돌리지 않았다 — 관측·충족도·근거 활용이 모두 비어 있다.",
)

def _squeeze(text: str) -> str:
    """공백 · 탭 · 줄바꿈을 전부 지운다. 확정 문구의 띄어쓰기가 배포마다 조금씩 다르다."""
    return re.sub(r"\s+", "", text)


def check_service_error(answer: str) -> Check:
    """답변이 서비스 자원 부족 안내 문구인가."""
    if not answer.strip():
        return Check("service_error", "not_applicable", "답변이 비어 있음")

    packed = _squeeze(answer)
    for template in settings.SERVICE_ERROR_TEMPLATES:
        if _squeeze(template) in packed:
            return Check("service_error", "violated",
                         f"서비스 자원 부족 확정 문구와 일치: {template[:30]}…")
    return Check("service_error", "ok", "확정 문구 없음")


def check(turn) -> Check:
    return check_service_error(turn.case.llm_ans_on_last_q)
