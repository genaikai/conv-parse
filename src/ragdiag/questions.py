"""kev 문항 — 범주 판정 전부가 여기 있다 (v4).

kev 는 yes/no(noul) · 택일(choice) 두 유형만 쓰고 보정된 확률을 낸다. 요청 하나에 문항 여러
개를 넣으면 **각각 독립으로** 채점한다 — "1 이 예일 때만 2 를 봐라" 같은 순서는 kev 가 아니라
코드가 읽는다 (features/complaint). 그래서 문항 하나하나가 혼자 읽혀도 뜻이 서야 한다.

**지시문은 판정 기준만 적는다.** 모델이 바뀌어도 기준은 같아야 한다.

TEXT 의 문장이 결과 파일의 키다. 문장을 고치면 결과 키가 바뀌니 여기서만 고친다.
"""

from __future__ import annotations

from typing import Any


def noul(instructions: str, true: str = "", false: str = "") -> dict:
    q: dict[str, Any] = {"type": "noul", "instructions": instructions}
    if true or false:
        q["criteria"] = {"true": true, "false": false}
    return q


def choice(instructions: str, options: dict[str, str | None]) -> dict:
    return {"type": "choice", "instructions": instructions, "criteria": dict(options)}


# ---------------------------------------------------------------------------
# 불만 판정 — state: {history, question, answer, followup}
# 문서 · 도구 결과 · memory 는 주지 않는다. 삽입 순서가 읽는 순서다.
# ---------------------------------------------------------------------------

COMPLAINT: dict[str, dict] = {
    "complains": noul(
        "followup(후속 발화)이 answer(앞 답변)를 문제 삼는가. 가르는 기준은 주제가 바뀌었는가가 "
        "아니라 앞 답변을 문제 삼는가다. 앞 답변을 받아들이고 다음을 묻거나 범위를 넓히는 것, 수긍 · "
        "감사는 아니오다. 범위나 조건을 바로잡는 발화('국내 말고 해외요', '○○라고 했잖아요')와 "
        "답이 틀렸다 · 부족하다 · 엉뚱하다는 지적은 예다. history 는 가리킴('아까 그거')을 풀 때만 쓴다.",
        true="앞 답변을 문제 삼는다", false="문제 삼지 않는다 — 새 질문 · 수긍 · 감사"),
    "refusal": noul(
        "answer 가 정책 · 권한 · 보안을 이유로 답을 거절했고, followup 이 그 거절을 불평하는가. "
        "'자료를 찾지 못했다' · '확인되지 않는다' 는 거절이 아니라 못 찾았다는 안내다. "
        "거절했어도 followup 이 다른 것을 문제 삼으면 아니오다.",
        true="정책·권한 거절이고 사용자가 그걸 불평한다", false="거절이 아니거나 거절을 불평하는 것이 아니다"),
    "illegible": noul(
        "answer 를 사람이 읽고 뜻을 잡을 수 없는가. 부실하거나 짧거나 틀린 답변, 문장 중간에서 끊긴 "
        "답변, 문법이 틀린 코드, 내용이 이상한 답변은 전부 읽을 수 있는 글이다. 무의미한 문자열 · 여러 "
        "언어 토큰이 뒤섞여 문장이 안 되는 것 · 어느 지점부터 깨지는 것 · 같은 문단이 조금씩 바뀌며 "
        "되풀이되는 것 · 스택 트레이스 · 서버 에러 JSON · <think> · 채팅 템플릿 토큰(<|im_start|> 등) · "
        "{{…}} 템플릿이 그대로 나온 것만 읽을 수 없는 것이다. 확신이 없으면 아니오다.",
        true="읽을 수 없다 (붕괴 · 토큰 잡탕 · 내부 유출)", false="읽을 수 있는 글이다"),
    "truncated": noul(
        "answer 가 중간에 끊겼는가. 문장이 끝맺지 못하고 멈춤 · 목록이 번호만 남기고 끝남 · 코드 "
        "블록이 닫히지 않음 · 표가 중간 행에서 끝남이 끊김이다. 짧지만 끝맺은 답, 되묻고 끝난 답은 "
        "아니오다. 끝 부분을 중점적으로 봐라.",
        true="중간에 끊겼다", false="끝까지 썼다"),
    "language": noul(
        "answer 가 question 과 다른 언어로 쓰였는가. question 이 특정 언어로 답하라고 요구했으면 그 "
        "언어가 기준이다. 전문 용어 · 고유명사 · 코드가 섞인 것은 다른 언어가 아니다. 본문의 절반 "
        "이상이 다른 언어이거나, 문단 단위로 언어가 바뀌면 예다.",
        true="질문(또는 요구한) 언어와 다르다", false="같은 언어다"),
    "emotion_only": noul(
        "followup 이 감정 표출(짜증 · 욕설 · 한숨 · '됐어요')뿐이고, 답변의 무엇이 틀렸거나 부족한지 "
        "단서가 하나도 없는가. 감정과 함께 '○○가 아니잖아요' 처럼 가리키는 말이 있으면 아니오다.",
        true="감정 표출뿐, 단서 없음", false="무엇이 문제인지 가리킨다"),
    "new_demand": noul(
        "followup 이 question 과 history 의 user 발화 어디에도 없던 **새 요구**를 하면서, 그것을 안 "
        "했다고 불평하는가. 앞에서 한 요구를 되짚는 것('아까 표로 달라고 했잖아요')은 아니오다. 앞 "
        "질문의 일부를 빠뜨렸다는 지적도 아니오다 — 그 요구는 앞 질문에 있었다.",
        true="앞에 없던 새 요구를 하며 불평한다", false="앞 질문에 있던 것을 문제 삼는다"),
    "no_doc": noul(
        "question 이 사내 문서 · 도구 없이 답할 수 있는 종류인가 — 산수 · 날짜 계산, 코드 작성 · "
        "오류, 번역 · 요약 · 문장 다듬기, 공개된 일반 상식. 회사 규정 · 절차 · 제도 · 공정 · 장비 · "
        "데이터처럼 회사마다 답이 다른 것은 아니오다. 법령을 언급해도 '우리 회사는 어떻게 하나' 면 "
        "아니오다. 애매하면 아니오다.",
        true="문서 · 도구 없이 답할 질문", false="사내 문서나 도구가 있어야 답할 질문"),
}

# 문항 id → (예일 때 묶음, 아니오일 때 묶음). None 은 "다음 문항으로".
COMPLAINT_ROUTE: dict[str, tuple[str | None, str | None]] = {
    "complains": (None, "normal"),
    "refusal": ("system", None),
    "illegible": ("system", None),
    "truncated": ("system", None),
    "language": ("generation", None),
    "emotion_only": ("user", None),
    "new_demand": ("user", None),
    "no_doc": ("generation", None),
}

# ---------------------------------------------------------------------------
# 근거 판정 — state: {question, <칸 이름> …}. 답변 · 후속 발화는 주지 않는다.
# ---------------------------------------------------------------------------

SLOTS: tuple[tuple[str, str], ...] = (
    ("retrieved", "이번 턴 검색 청크"),
    ("tool", "이번 턴 도구 결과"),
    ("history", "앞 턴 근거"),
    ("memory", "메모리"),
)
SLOT_NAME = dict(SLOTS)

_SLOT_RULE = ("question 의 **일부라도** 답하는 내용이 있으면 예. 주제만 같고 묻는 것에는 답하지 "
              "않는 내용은 아니오.")

EVIDENCE_SLOT: dict[str, dict] = {
    f"in_{slot}": noul(f"{korean} 안에 question 에 답하는 내용이 있는가. {_SLOT_RULE}",
                       true=f"{korean}에 답(의 일부)이 있다", false=f"{korean}에 답이 없다")
    for slot, korean in SLOTS
}

EVIDENCE_ANY: dict[str, dict] = {
    "any": choice(
        "네 칸(이번 턴 검색 청크 · 이번 턴 도구 결과 · 앞 턴 근거 · 메모리)을 합쳐서 보면, question "
        "이 묻는 것에 답하는 내용이 얼마나 있는가. question 이 여럿을 물으면 그 전부를 기준으로 "
        "한다. 주제만 같은 내용은 답이 아니다.",
        {"all": "질문이 묻는 것 전부에 답하는 내용이 네 칸을 합쳐 있다",
         "partial": "일부에만 답하는 내용이 있다",
         "none": "답하는 내용이 없다"}),
}

# ---------------------------------------------------------------------------
# 불만 부분 근거 판정 — state: {question, followup, <칸 이름> …}. 근거가 일부일 때만.
# ---------------------------------------------------------------------------

COMPLAINT_EVIDENCE: dict[str, dict] = {
    "targeted": noul(
        "followup 이 문제 삼는 부분(question 의 어느 쪽을 틀렸다 · 빠뜨렸다고 하는가)을 먼저 잡고, "
        "**그 부분**에 답하는 내용이 네 칸 어디엔가 있는가. 다른 부분의 근거가 있는 것은 상관없다.",
        true="불만이 가리키는 부분의 답이 근거에 있다", false="그 부분의 답은 근거에 없다"),
}

# 문항 id → 결과 파일의 키 문장.
TEXT: dict[str, str] = {
    "complains": "후속 발화가 답변을 문제 삼는다",
    "refusal": "정책·권한 거절이고 그걸 불평한다",
    "illegible": "답변이 읽을 수 없는 글이다",
    "truncated": "답변이 중간에 끊겼다",
    "language": "답변이 질문과 다른 언어다",
    "emotion_only": "후속 발화가 감정 표출뿐이다",
    "new_demand": "앞 질문에 없던 새 요구를 하며 불평한다",
    "no_doc": "문서·도구 없이 답할 질문이다",
    **{f"in_{slot}": f"{korean}에 답이 있다" for slot, korean in SLOTS},
    "any": "근거 전체에 답이 있다",
    "targeted": "불만이 가리키는 부분에 답이 근거에 있다",
}

# 빈 칸의 문항은 묻지 않는다. 결과 파일에 이 문자열이 답 자리에 실린다.
SKIPPED = "비어 있어 묻지 않음"
