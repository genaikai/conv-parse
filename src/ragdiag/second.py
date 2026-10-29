"""2차 판정 (LLM) — kev 가 모름이라 한 문항 **하나**를 일반 LLM 에 다시 묻는다.

kev 뒤에 선다. 앞에 두면(LLM 이 요약을 쓰고 kev 가 그걸 채점) LLM 의 실수가 kev 의 확신으로
바뀌어 아무도 안 본다. 뒤에 두면 LLM 이 틀려도 `sure=False` 안에 남아 사람이 본다
(docs/design/decision_tree_v4.md "모름 줄이기").

입력은 그 단계가 kev 에 준 state 그대로와 그 문항의 지시문 · 선택지, 그리고 kev 의 p. 출력은
이유 문장 먼저, 답은 문항의 선택지 또는 모름. LLM 이 답하면 호출한 단계가 그 답으로 트리를
이어 돌리고, 모름이면 지금처럼 검토다. 어느 쪽이든 steps 에 "2차 판정 (LLM)" 이 하나 선다.

일반 LLM 백엔드가 없거나 settings.SECOND_PASS 가 꺼져 있으면 아무것도 안 하고 None 이다.
"""

from __future__ import annotations

import json
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, create_model

from ragdiag import settings, taxonomy
from ragdiag.decide import Answer, output_contract
from ragdiag.results import DECIMALS, NO, UNSURE, YES, CHOICE_TEXT, StepResult

SYSTEM = """\
너는 분류 모델이 확신하지 못한 문항 하나를 다시 판정한다. 주어진 상태(state)만 근거로 한다.
먼저 reasoning 에 판단의 근거를 두세 문장으로 적어라 — 상태의 어느 부분이 기준의 어느 조건에
맞거나 안 맞는지. 그 다음 answer 를 고른다. 문항의 지시문과 선택지 설명이 기준이다.
상태에 근거가 없어 어느 쪽도 고를 수 없을 때만 "모름" 이다. 분류 모델의 확률은 참고일 뿐
따르지 마라.
"""


def build_model(question: dict) -> type[BaseModel]:
    """문항 유형대로 답 선택지를 만든다 — yes/no 는 예/아니오, 택일은 선택지 id. 모름은 늘 있다."""
    if question["type"] == "noul":
        options: tuple[str, ...] = (YES, NO, UNSURE)
    else:
        options = (*question["criteria"].keys(), UNSURE)
    return create_model(                                                 # type: ignore[call-overload]
        "SecondOpinion",
        reasoning=(str, Field(description="판단의 근거 두세 문장. 상태의 어느 부분이 기준의 어느 조건에 맞나")),
        answer=(Literal[options], Field(description="선택지 이름 그대로")),   # type: ignore[valid-type]
    )


def _criteria_lines(question: dict) -> list[str]:
    crit = question.get("criteria")
    if question["type"] == "noul":
        if isinstance(crit, dict):
            return [f"  - {YES}: {crit.get('true', '')}", f"  - {NO}: {crit.get('false', '')}"]
        return [f"  - {YES} / {NO}"]
    return [f"  - {k}: {v or ''}" for k, v in (crit or {}).items()]


def user_text(state: Any, qid: str, question: dict, kev_p: float) -> str:
    state_text = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False, indent=1)
    lines = [f"## 상태\n{state_text}", "", f"## 문항 [{qid}]", question.get("instructions", ""),
             *_criteria_lines(question), f"  - {UNSURE}: 상태만으로는 어느 쪽도 고를 수 없다", "",
             f"분류 모델은 이 문항에 확신이 없었다 (p {kev_p:.2f})."]
    return "\n".join(lines)


def available(ctx) -> bool:
    judge = getattr(ctx, "judge", None)
    return bool(settings.SECOND_PASS and judge is not None and getattr(judge, "backend", None) is not None)


def _word(question: dict, answer: str) -> str:
    """결과 파일에 쓰는 말 — 택일은 전부/일부/없음."""
    return answer if question["type"] == "noul" else CHOICE_TEXT.get(answer, answer)


def ask(turn, ctx, step: str, qid: str, question: dict, state: Any,
        kev_answer: Answer) -> Optional[str]:
    """LLM 의 답(예 · 아니오 · 선택지 id) 또는 None(모름 · 못 물음). 기록은 여기서 남긴다."""
    if not available(ctx):
        return None
    model = build_model(question)
    text = user_text(state, qid, question, kev_answer.p)
    parsed, used = ctx.judge.opine(f"second-{qid}", SYSTEM, text, model, output_contract(model))
    turn.usage.add(used)
    turn.n_calls += bool(used.input_tokens or used.output_tokens)
    answer = str(parsed.answer)
    reasoning = str(parsed.reasoning).strip()
    turn.steps.append(StepResult(step=taxonomy.STEP_SECOND, answers={
        qid: {"kev_p": round(kev_answer.p, DECIMALS), "answer": _word(question, answer), "이유": reasoning}}))
    turn.second.append({"step": step, "qid": qid, "kev_p": kev_answer.p, "llm": _word(question, answer)})
    return None if answer == UNSURE else answer
