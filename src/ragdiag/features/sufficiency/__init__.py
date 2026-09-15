"""Step 2 — 충족도. **문서가 사용자의 요구를 담고 있었나.** 답변의 품질이 아니다.

도메인 질문의 내용 불만일 때만 돈다. 형식 · 언어 · 길이 불만에 문서 충족도를 따지는
건 무의미하고 호출만 쓴다.

챗봇 답변은 주지 않는다. 보여주면 판정자가 답변을 문서의 대리물로 착각한다 - "답변이
부실하니 문서도 부실했겠지". 그러면 "문서에 답이 없었다"(문서를 고친다)와 "문서엔
있는데 답변이 안 썼다"(프롬프트를 고친다)의 갈림길이 사라진다.
"""

from ragdiag.schema import SufficiencyJudgment

from .._shared import call_llm, each_turn

NAME = "sufficiency"

# 내용에 대한 불만일 때만 문서 충족도를 따진다. 형식 불만에 그걸 묻는 건 무의미하다.
CONTENT_COMPLAINTS = {"content_missing", "content_wrong"}


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
        turn.judgment = call_llm(
            turn, ctx.judge.judge_sufficiency_from(turn.case, turn.observation))

    each_turn(ctx, NAME, judge, where=applies, parallel=True)
    return [], []
