"""Step 2 — 충족도. **문서가 사용자의 요구를 담고 있었나.** 답변의 품질이 아니다.

도메인 질문의 내용 불만일 때만 돈다. 형식 · 언어 · 길이 불만에 문서 충족도를 따지는
건 무의미하고 호출만 쓴다.

챗봇 답변은 주지 않는다. 보여주면 판정자가 답변을 문서의 대리물로 착각한다 - "답변이
부실하니 문서도 부실했겠지". 그러면 "문서에 답이 없었다"(문서를 고친다)와 "문서엔
있는데 답변이 안 썼다"(프롬프트를 고친다)의 갈림길이 사라진다.
"""

import re

from ragdiag.schema import SufficiencyJudgment

from .._shared import call_llm, each_turn

NAME = "sufficiency"

# 내용에 대한 불만일 때만 문서 충족도를 따진다. 형식 불만에 그걸 묻는 건 무의미하다.
CONTENT_COMPLAINTS = {"content_missing", "content_wrong"}

# unmet_need 의 항목 경계. 쉼표 · 가운뎃점 · 빗금 · "및" · "그리고" · "또는". "과/와" 는 경계로 치지
# 않는다 - "담당 부서의 이름과 내선 번호" 처럼 하나의 요구를 묶는 일이 더 많다(messy eng02 실측).
_ITEM_SPLIT = re.compile(r"\s*(?:,|·|/|、|\b및\b|\b그리고\b|\b또는\b)\s*")
# 질문이 여러 가지를 물었다는 표시. 관측(question_multi_intent)이 없을 때만 쓴다(골든셋).
_MULTI_QUESTION = re.compile(r"각각|,|및|그리고|(?<=[가-힣])(?:과|와)\s+[가-힣]")


def first_item(need: str) -> str:
    items = [x.strip() for x in _ITEM_SPLIT.split(need) if x.strip()]
    return items[0] if items else need


def narrow_need(unmet_need: str, multi_intent: bool) -> str:
    """Step 2 에 넘길 요구. 질문이 한 가지를 물었으면 unmet_need 의 첫 항목만.

    Step 1 은 "정확한 금액이요" 에 절차 · 서류 · 기한을 덧붙이는 버릇이 있고, Step 2 프롬프트의
    "질문에 없는 항목은 빼라" 는 지시는 생각(thinking)을 끈 약한 모델에서 전혀 안 먹혔다
    (부풀림 케이스 18회 중 8회, 지시를 단순하게 바꾸면 0회). 첫 항목만 남기는 코드 한 줄이
    17/18 이고 좁힘 · 반대 상황 14/14 를 그대로 지킨다 - 후속 발화로 좁혀진 요구는 언제나 첫
    항목이었다. 질문이 여러 가지를 물었으면(question_multi_intent) 항목을 전부 남긴다.
    출력 파일과 빈 청크의 missing 에는 원래 unmet_need 가 그대로 간다
    (docs/design/sufficiency_step.md 4차).
    """
    return unmet_need if multi_intent else first_item(unmet_need)


def question_looks_multi(question: str) -> bool:
    """관측 없이 질문 문장만으로 복합 여부를 어림한다 - 골든셋 채점용."""
    return bool(_MULTI_QUESTION.search(question))


def applies(turn) -> bool:
    obs = turn.observation
    return obs.question_domain == "domain" and obs.complaint_target in CONTENT_COMPLAINTS


def process_data(ctx) -> tuple[list, list]:
    def judge(turn):
        if not turn.case.rag_chunks:
            # 판정할 문서가 하나도 없다. verdict 는 물어볼 것 없이 insufficient 이고
            # 인용할 대상도 없다. LLM 을 부르면 호출만 쓰는 게 아니라 없는 문서에서
            # 인용을 지어낼 표면이 생긴다 - citation 이 잡아내지만 잡을 일을 안 만든다.
            turn.judgment = SufficiencyJudgment(
                reasoning="rag_data 가 비어 있어 대조할 문서가 없다.",
                evidence=[], verdict="insufficient", missing=turn.observation.unmet_need)
            return
        obs = turn.observation
        narrowed = obs.model_copy(update={
            "unmet_need": narrow_need(obs.unmet_need, obs.question_multi_intent)})
        turn.judgment = call_llm(turn, ctx.judge.judge_sufficiency_from(turn.case, narrowed))

    each_turn(ctx, NAME, judge, where=applies, parallel=True)
    return [], []
