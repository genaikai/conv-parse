"""백엔드 테스트용 Pydantic 모델. v3 의 판정 모델이 없어져서 여기서 모양만 흉내 낸다.

백엔드가 재는 것은 "스키마를 받아 구조화 출력을 강제하고 JSON 을 꺼내 오나" 다 — 모델이
무엇을 뜻하는지는 상관없다. enum · 중첩 배열 · 평평한 모델 하나씩.
"""

from typing import Literal

from pydantic import BaseModel, Field


class GroundingCheck(BaseModel):
    reasoning: str
    answer_used_rag: Literal["used", "ignored", "contradicted"]


class Nested(BaseModel):
    chunk_index: int = Field(description="청크 인덱스")
    quote: str = Field(description="글자 그대로 복사한 문장")


class WithArray(BaseModel):
    reasoning: str
    evidence: list[Nested]
    verdict: Literal["sufficient", "partial", "insufficient"]
    missing: str


class WithEnum(BaseModel):
    reasoning: str
    complaint_target: Literal["none", "content_missing", "content_wrong", "format"]
