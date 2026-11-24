"""④ 불만 판정 입력 축약 — kev 가 500(OOM) 을 냈을 때만, 칸별 상한으로 줄여 한 번 더 묻는다.

평소에는 원문을 그대로 보낸다. 미리 줄이면 모든 긴 턴의 판정이 축약된 입력 위에서 이뤄져 분포가
달라지고, 500 은 드물기 때문이다. 발동은 Judge.decide 가 KevHTTPError 를 TOO_LARGE_STATUSES
(500 OOM · 422 한도 초과 · 413 프록시) 로 받았을 때고 (docs/abbrev.md), 어느 칸도 상한을 넘지
않았으면 크기 문제가 아니므로 손대지 않는다.

칸마다 방법이 다르다. 문항이 읽는 신호를 지우는 방법은 쓰지 않는다.

  answer    머리 · 꼬리 보존 (elide). 거절 · 문서없음 문구는 머리에, 끊김은 꼬리에, 언어 · 형식은
            어느 쪽이든 표본이면 된다. LLM 요약은 끊김 · 언어 · 형식 · 거절 문구를 전부 지우므로 쓰지 않는다.
  followup  elide 만, 상한도 높다. 모든 문항의 출발점이라 바꾸면 판정 자체가 바뀐다.
  history   ① assistant 발화를 접는다 (fold) — 6번은 user 발화만 단서로 본다.
            ② 여전히 넘치면 마지막 user 둘은 원문, 그 앞 user 발화를 LLM 이 "무엇을 요구했고 무엇이
               틀렸다 했나" 로 요약 (summarize). 요약 각 줄이 원문과 낱말을 공유해야 받는다 — 지어낸
               단서가 6번을 속이면 안 된다.
            ③ 못 쓰면 앞에서부터 버린다 (drop). 그래도 넘치면 남은 발화를 elide.
  question  LLM 이 지시문(원문 발췌)과 붙여 넣은 자료의 요약으로 분리 (split). 3 · 6 · 7 이 읽는 것은
            지시문이다. 발췌가 아니면(`instruction in question` 실패) elide.

LLM 은 judge.opine 으로만 부른다 — 2차 판정과 같은 백엔드 · 같은 캐시. 백엔드가 없으면 전부
결정적 방법으로 떨어지고 어느 경우에도 멈추지 않는다.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from ragdiag import settings
from ragdiag.backends import Usage
from ragdiag.decide import output_contract

FLAG = "입력 축약"          # turn.flags 의 키. 값은 [{"field", "method", "before", "after"}] (글자 수)
# "입력이 너무 크다" 로 읽는 HTTP 코드. 500 은 kev 가 받아 처리하다 GPU 메모리가 바닥난 것(OOM),
# 422 는 kev 가 state 65,536 토큰 한도를 넘었다고 거절한 것, 413 은 앞단 프록시의 본문 크기 제한.
# 셋 다 "어느 칸도 상한을 안 넘었으면 손대지 않는다" 는 같은 보호를 받는다 — 다른 이유의 422(문항
# 모양 오류 등) 는 거기서 걸러진다. 503 · 502 · 504 는 서버 상태라 줄여도 소용없고, 4xx 나머지는 우리 버그다.
TOO_LARGE_STATUSES = (500, 413, 422)
METHODS = ("elide", "fold", "summarize", "split", "drop")

_FOLD_KEEP = 80            # 접은 assistant 발화에 남기는 앞 글자 수 — 주제만 보이면 된다
_MARKER_RESERVE = 30       # elide 가 중략 표시에 남겨 두는 글자 수


# -- 크기 -----------------------------------------------------------------------

def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def size(value: Any) -> int:
    """글자 수. 목록(history)은 kev 가 받는 JSON 그대로 잰다."""
    return len(_text(value))


def tokens(value: Any) -> int:
    """토큰 추정 — 글자 수 / ABBREV_CHARS_PER_TOKEN, 올림. 실제 토크나이저가 아니라 보수적 어림이다."""
    return math.ceil(size(value) / settings.ABBREV_CHARS_PER_TOKEN)


def _budget(cap_tokens: int) -> int:
    return int(cap_tokens * settings.ABBREV_CHARS_PER_TOKEN)


# -- 결정적 방법 ----------------------------------------------------------------

def elide(text: str, cap_tokens: int, head: float = 0.7) -> str:
    """머리 head 비율 + `…(중략 N자)…` + 꼬리. 결과는 상한 안에 든다."""
    budget = _budget(cap_tokens)
    if len(text) <= budget:
        return text
    room = max(budget - _MARKER_RESERVE, 2)
    h = int(room * head)
    t = room - h
    omitted = len(text) - h - t
    return f"{text[:h]}\n…(중략 {omitted}자)…\n{text[len(text) - t:]}"


def _fold(message: dict) -> dict:
    content = str(message.get("content", ""))
    if message.get("role") != "assistant" or len(content) <= _FOLD_KEEP:
        return message
    return {**message, "content": f"{content[:_FOLD_KEEP]} …(답변 생략 · {len(content)}자)"}


def _words(text: str) -> set[str]:
    return {w for w in re.split(r"[\s\W]+", text) if len(w) >= 2}


# -- LLM 방법 ---------------------------------------------------------------------

_SYSTEM = """\
너는 분류 모델에 넘기기에 너무 긴 입력을 줄인다. 판정은 네가 하지 않는다. 지어내지 말고, 원문에 없는
사실을 더하지 마라. 요구한 출력 모양을 정확히 지켜라.
"""


class _Requests(BaseModel):
    requests: list[str] = Field(description="사용자가 요구한 것과 틀렸다고 지적한 것. 한 줄에 하나. "
                                            "사용자의 표현을 그대로 살리고 assistant 의 답은 적지 않는다")


class _Split(BaseModel):
    instruction: str = Field(description="사용자의 요구 문장. question 에서 **글자 그대로** 발췌한다. 바꿔 쓰지 마라")
    body_summary: str = Field(description="붙여 넣은 자료(메일 · 문서 · 코드 등)가 무엇에 관한 것인지 두세 문장으로")


def _can_ask(judge) -> bool:
    return judge is not None and getattr(judge, "backend", None) is not None


def _summarize_users(older: list[str], judge) -> tuple[Optional[list[str]], Usage]:
    user = "## 앞 대화의 user 발화 (오래된 것부터)\n" + "\n\n".join(f"[{i + 1}] {u}" for i, u in enumerate(older)) \
        + "\n\n이 발화들에서 사용자가 무엇을 요구했고 무엇이 틀렸다고 했는지를 뽑아라."
    parsed, used = judge.opine("abbrev-history", _SYSTEM, user, _Requests, output_contract(_Requests))
    lines = [str(r).strip() for r in parsed.requests if str(r).strip()]
    have = set().union(*(_words(u) for u in older)) if older else set()
    if not lines or any(not (_words(line) & have) for line in lines):
        return None, used                 # 원문과 낱말을 하나도 안 나누는 줄은 지어낸 것으로 본다
    return lines, used


def _split_question(question: str, judge) -> tuple[Optional[str], Usage]:
    user = f"## question\n{question}\n\n지시문을 글자 그대로 발췌하고, 붙여 넣은 자료는 요약하라."
    parsed, used = judge.opine("abbrev-question", _SYSTEM, user, _Split, output_contract(_Split))
    instruction = str(parsed.instruction).strip()
    if not instruction or instruction not in question or len(instruction) >= len(question):
        return None, used
    return f"{instruction}\n\n(첨부 내용 요약) {str(parsed.body_summary).strip()}", used


# -- 칸별 처방 --------------------------------------------------------------------

def _history(messages: list[dict], cap: int, judge) -> tuple[list[dict], str, Usage, int]:
    folded = [_fold(m) for m in messages]
    if tokens(folded) <= cap:
        return folded, "fold", Usage(), 0
    user_at = [i for i, m in enumerate(folded) if m.get("role") == "user"]
    cut = user_at[-2] if len(user_at) >= 2 else (user_at[0] if user_at else 0)
    older, tail = folded[:cut], folded[cut:]
    older_users = [str(m.get("content", "")) for m in older if m.get("role") == "user"]
    usage, calls = Usage(), 0
    if older_users and _can_ask(judge):
        lines, used = _summarize_users(older_users, judge)
        usage.add(used)
        calls += 1
        if lines:
            out = [{"role": "user", "content": "(앞 대화 요약) " + " / ".join(lines)}, *tail]
            if tokens(out) <= cap:
                return out, "summarize", usage, calls
    if tokens(tail) <= cap:
        return tail, "drop", usage, calls
    # 마지막 둘만으로도 넘친다 — 남은 발화를 같은 몫으로 접는다
    share = max(cap // max(len(tail), 1) - 8, 8)            # 8 은 role · 따옴표 등 JSON 몫
    out = [{**m, "content": elide(str(m.get("content", "")), share, head=0.5)} for m in tail]
    return out, "elide", usage, calls


def _question(question: str, cap: int, judge) -> tuple[str, str, Usage, int]:
    if _can_ask(judge):
        rendered, used = _split_question(question, judge)
        if rendered is not None:
            if tokens(rendered) > cap:
                rendered = elide(rendered, cap, head=0.5)
            return rendered, "split", used, 1
        return elide(question, cap, head=0.5), "elide", used, 1
    return elide(question, cap, head=0.5), "elide", Usage(), 0


def _complaint(state: dict, judge) -> tuple[dict, list[dict], Usage, int]:
    out, notes, usage, calls = dict(state), [], Usage(), 0

    def note(field: str, method: str, before: Any, after: Any) -> None:
        notes.append({"field": field, "method": method, "before": size(before), "after": size(after)})

    history = state.get("history") or []
    if tokens(history) > settings.ABBREV_HISTORY_TOKENS:
        out["history"], method, used, n = _history(list(history), settings.ABBREV_HISTORY_TOKENS, judge)
        usage.add(used)
        calls += n
        note("history", method, history, out["history"])
    question = str(state.get("question") or "")
    if tokens(question) > settings.ABBREV_QUESTION_TOKENS:
        out["question"], method, used, n = _question(question, settings.ABBREV_QUESTION_TOKENS, judge)
        usage.add(used)
        calls += n
        note("question", method, question, out["question"])
    answer = str(state.get("answer") or "")
    if tokens(answer) > settings.ABBREV_ANSWER_TOKENS:
        out["answer"] = elide(answer, settings.ABBREV_ANSWER_TOKENS, head=0.7)
        note("answer", "elide", answer, out["answer"])
    followup = str(state.get("followup") or "")
    if tokens(followup) > settings.ABBREV_FOLLOWUP_TOKENS:
        out["followup"] = elide(followup, settings.ABBREV_FOLLOWUP_TOKENS, head=0.5)
        note("followup", "elide", followup, out["followup"])
    return out, notes, usage, calls


# 단계 → 처방. ⑤ · ⑥ 은 아직 없다 — 근거 칸은 발췌 규칙이 달라야 해서 따로 설계한다.
RECIPES = {"complaint": _complaint}


def abbreviate(stage: str, state: Any, judge) -> Optional[tuple[dict, list[dict], Usage, int]]:
    """(줄인 state, 메모, LLM 사용량, LLM 호출 수). 처방이 없는 단계면 None.

    메모가 비어 있으면 어느 칸도 상한을 넘지 않은 것이다 — 호출한 쪽이 "크기 문제가 아니다" 로 읽는다.
    """
    recipe = RECIPES.get(stage)
    if recipe is None or not isinstance(state, dict):
        return None
    return recipe(state, judge)


def describe(notes: list[dict]) -> str:
    """에러 메시지 · 요약용 한 줄 — 'answer elide 12,400→6,000자 · history fold …'."""
    return " · ".join(f"{n['field']} {n['method']} {n['before']:,}→{n['after']:,}자" for n in notes)
