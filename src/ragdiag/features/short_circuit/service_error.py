"""case9 — 서비스 자원 부족 응답

모델 자원을 확보하지 못했을 때 서비스 계층이 내보내는 **확정 문구**다. LLM 이
생성한 답이 아니라 정해진 문자열이므로 코드로 판정한다 - 신뢰도 high 다.

이걸 따로 잡지 않으면 판정자가 "답변이 거절했다"로 읽어 case28(보안 정책상
답변 불가)으로 간다. 실제로 그 오분류가 많이 나왔다. 서버 자원 문제를 보안
정책 문제로 세면 고칠 곳을 정반대로 가리킨다 - 한쪽은 인프라 증설이고
다른 쪽은 권한 정책이다.

문구는 배포마다 다르므로 아래 목록에 줄을 추가해 쓴다. 공백 차이는 무시한다.
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

SERVICE_ERROR_TEMPLATES = settings.SERVICE_ERROR_TEMPLATES

# 템플릿이 조금 바뀌어도 놓치지 않도록 두는 보조 표지. 단독으로는 쓰지 않고
# 두 개 이상 겹칠 때만 인정한다 - "서버" 한 단어로 잡으면 서버 관련 질문에
# 정상적으로 답한 것까지 오탐한다.
_SERVICE_ERROR_MARKERS = settings.SERVICE_ERROR_MARKERS

# 확정 문구는 짧고, 그 문구가 답변의 전부다. 길면 서버 장애를 '주제로' 답한
# 정상 답변일 가능성이 높다. 길이로 한 번 더 거른다.
MAX_SERVICE_ERROR_LEN = settings.SERVICE_ERROR_MAX_CHARS


def _squeeze(text: str) -> str:
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

    if len(packed) > settings.SERVICE_ERROR_MAX_CHARS:
        return Check("service_error", "ok",
                     f"확정 문구 없음 · 답변이 길어({len(packed)}자) 안내 문구가 아님")

    hits = [m for m in settings.SERVICE_ERROR_MARKERS if _squeeze(m) in packed]
    if len(hits) >= 2:
        return Check("service_error", "violated",
                     f"확정 문구는 아니나 표지 {len(hits)}개 일치: {', '.join(hits)}")

    return Check("service_error", "ok", "서비스 안내 문구 아님")


def check(turn) -> Check:
    return check_service_error(turn.case.llm_ans_on_last_q)
