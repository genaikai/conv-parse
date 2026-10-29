"""서비스 자원 부족 응답

모델 자원을 확보하지 못했을 때 서비스 계층이 내보내는 **확정 문구**다. LLM 이
생성한 답이 아니라 정해진 문자열이므로 코드로 판정한다 - 확실하다.

이걸 따로 잡지 않으면 판정자가 "답변이 거절했다"로 읽어 거절(시스템 · 권한 정책)으로
간다. 실제로 그 오분류가 많이 나왔다. 서버 자원 문제를 보안 정책 문제로 세면 고칠 곳을 정반대로 가리킨다 - 한쪽은 인프라 증설이고
다른 쪽은 권한 정책이다.

**판정은 확정 문구 대조 하나다.** 공백 · 줄바꿈을 전부 지운 답변 안에 확정 문구가
(역시 공백을 지운 채로) 들어 있으면 걸린다. 앞뒤에 무엇이 붙었든, 답변이 얼마나
길든 상관없다.

비슷한 문구는 잡지 않는다. 예전에는 보조 표지("서버에 부하" · "잠시 후 다시" …)가 두 개
겹치면 잡았는데, 서버 부하를 주제로 한 짧은 정상 답변까지 여기로 보냈다. 이 규칙은
kev 판정을 건너뛰므로 오탐이 나면 그 턴의 진짜 원인이 통째로 사라진다. 배포마다
문구가 다르면 설정의 service_error.templates 에 줄을 더한다.
"""

import re

from ragdiag import settings

NAME = "service_error"          # 결과 파일 코드 확정 칸의 키


def _squeeze(text: str) -> str:
    """공백 · 탭 · 줄바꿈을 전부 지운다. 확정 문구의 띄어쓰기가 배포마다 조금씩 다르다."""
    return re.sub(r"\s+", "", text)


def check(answer: str) -> tuple[bool, str]:
    """답변이 서비스 자원 부족 안내 문구인가. (걸렸나, 설명)"""
    if not answer.strip():
        return False, "답변이 비어 있음"
    packed = _squeeze(answer)
    for template in settings.SERVICE_ERROR_TEMPLATES:
        if _squeeze(template) in packed:
            return True, f"확정 문구와 일치: {template[:30]}…"
    return False, "확정 문구 없음"
