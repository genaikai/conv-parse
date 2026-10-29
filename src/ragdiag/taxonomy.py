"""분류 체계 v4 — 묶음 다섯 · 단계 넷 · 멈춘 자리마다 고정 문장.

설계는 docs/design/decision_tree_v4.md. 여기는 그 표를 코드로 옮긴 것이고, 결과 파일에
실리는 묶음 이름 · 단계 이름 · 이유 문장의 **원본**이다. 문장을 고치면 결과 파일의 값이
바뀌고, 전달본 · 대시보드가 그 값을 검색하므로 여기서만 고친다.

묶음은 **고치는 사람**이다. 같은 증상도 검색기가 고칠 일과 프롬프트가 고칠 일이 다르고,
증상으로 묶으면 집계가 아무도 지목하지 못한다. 검토는 묶음이 아니라 상태다 — kev 가 확신하지
못해 사람이 봐야 하는 턴이고, 실패율 분모 밖이다.

v3 의 라벨 · 태그 · 등급은 없다. 세부는 데이터를 본 뒤 2단계에서 태그로 더한다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Bucket:
    id: str        # "generation"
    name: str      # "생성" — 결과 파일 · 화면에 쓰는 이름
    owner: str     # 고치는 사람


BUCKETS: dict[str, Bucket] = {b.id: b for b in (
    Bucket("normal", "정상", "필터 (챗봇이 아니다)"),
    Bucket("user", "사용자", "질문 유도 · UI"),
    Bucket("evidence", "근거", "검색기 · 도구 연동 · 문서"),
    Bucket("generation", "생성", "프롬프트 · 모델"),
    Bucket("system", "시스템", "인프라 · 서빙 · 권한 정책"),
    Bucket("review", "검토", "사람"),
)}

REVIEW = "review"


def name(bucket_id: str) -> str:
    return BUCKETS[bucket_id].name


# 단계 이름. 결과 파일의 stopped_at · steps[].step 에 그대로 실린다.
STEP_CODE = "코드 확정"
STEP_COMPLAINT = "불만 판정"
STEP_EVIDENCE = "근거 판정"
STEP_COMPLAINT_EVIDENCE = "불만 부분 근거 판정"
STEPS = (STEP_CODE, STEP_COMPLAINT, STEP_EVIDENCE, STEP_COMPLAINT_EVIDENCE)
# 멈추는 단계가 아니다 — kev 가 모름이라 한 문항을 LLM 에 다시 물은 기록으로, 멈춘 단계 뒤에 선다.
# 그래서 STEPS(stopped_at 의 값) 에는 없다.
STEP_SECOND = "2차 판정 (LLM)"

# 멈춘 자리 → 이유 문장. 키는 "<단계>:<출구>". 같은 결론은 늘 같은 문장이라 검색이 된다.
BECAUSE: dict[str, str] = {
    f"{STEP_CODE}:service_error": "서비스 자원 부족 안내 문구다 — 모델이 답을 만든 적이 없다",
    f"{STEP_CODE}:empty_answer": "답변이 비어 있다 — 판정할 답이 없다",
    f"{STEP_CODE}:degenerate": "같은 글자·기호의 반복뿐이다 — 생성이 무너졌다",

    f"{STEP_COMPLAINT}:complains:no": "후속 발화가 앞 답변을 문제 삼지 않는다 — 필터가 넓게 잡은 턴",
    f"{STEP_COMPLAINT}:refusal:yes": "정책·권한을 이유로 거절했고 사용자가 그 거절을 불평한다",
    f"{STEP_COMPLAINT}:illegible:yes": "답변이 사람이 읽을 수 없는 글이다 (토큰 잡탕 · 깨짐 · 템플릿 토큰)",
    f"{STEP_COMPLAINT}:truncated:yes": "답변이 중간에 끊겼다",
    f"{STEP_COMPLAINT}:language:yes": "답변이 질문과 다른 언어로 쓰였다",
    f"{STEP_COMPLAINT}:emotion_only:yes": "후속 발화가 감정 표출뿐이라 무엇이 틀렸는지 단서가 없다",
    f"{STEP_COMPLAINT}:new_demand:yes": "앞 질문에 없던 새 요구를 하며 그걸 안 했다고 불평한다",
    f"{STEP_COMPLAINT}:no_doc:yes": "문서·도구 없이 답할 질문(계산 · 코드 · 상식)인데 불만이 있다",

    f"{STEP_EVIDENCE}:any:all": "근거에 답이 전부 있었는데 답변이 살리지 못했다",
    f"{STEP_EVIDENCE}:any:none": "근거 어디에도 질문의 답이 없었다",
    f"{STEP_EVIDENCE}:empty": "청크도 도구 결과도 앞 턴 근거도 메모리도 없었다",

    f"{STEP_COMPLAINT_EVIDENCE}:targeted:yes": "근거가 일부였지만 불만이 가리키는 부분은 근거에 있었다",
    f"{STEP_COMPLAINT_EVIDENCE}:targeted:no": "근거가 일부였고 불만이 가리키는 부분이 근거에 없었다",
}


def stopped_at_review(step: str, question_text: str) -> str:
    """검토 턴의 stopped_at — 단계에 막힌 문항까지 붙인다."""
    return f"{step} · {question_text}"


def because_review(step: str, question_text: str, p: float) -> str:
    return f"{question_text} — 확신이 없다 (p {p:.2f})"


def second_pass_text(step: str, question_text: str, kev_p: float, llm: str) -> str:
    """verdict.second_pass 한 항목 — 어느 문항에서 kev 가 얼마였고 LLM 이 뭐라 했나."""
    return f"{step} · {question_text} — kev p {kev_p:.2f}, LLM {llm}"
