"""conv_eval 포맷 로더.

이전 포맷(data_format_ex.json)과 두 가지가 결정적으로 다르다.

**1. 모든 턴이 들어있다.** 이전에는 불만 턴만 걸러져 있었다. 이제는 대화 전체가 오고,
어느 턴을 볼지는 별도 필터 파일이 정한다. 덕분에 대화 히스토리를 재구성할 수 있어
Stage 1의 대명사 해소가 정확해진다.

**2. 한 턴이 (질문, 답변) 쌍이다.** 이전에는 한 레코드에 "히스토리 + 답변 + 불만"이
같이 있었다. 이제 불만은 **다음 턴의 user_question**이다. 그래서 진단 케이스 하나는
연속한 두 턴의 쌍이 된다:

    turn N   ├─ user_question   사용자가 물은 것
             ├─ retrieved_data  그 질문으로 검색된 문서   ← 충족도 판정 대상
             └─ llm_response    불만을 부른 답변
    turn N+1 └─ user_question   그 답변에 대한 불만       ← 요구를 읽어내는 신호

`retrieved_data`를 turn N에서 가져오는 게 중요하다. 우리가 묻는 건 "비판받은 답변을
만든 문서가 충분했나"이지 "다음 질문으로 검색된 문서"가 아니다.

`llm_eval_result` / `llm_emotion_result`는 **직전 턴의 질문과 답변을 참고해 계산한**
값이다. 그래서 turn 1에는 없고 turn 2부터 존재한다. 이 값이 붙은 턴이 곧 후속 질문이고,
필터는 여기에 거는 것이 자연스럽다.

`trace_matched`는 **그 대화에 턴이 2개 이상 있는지**를 나타낸다. 즉 turns 배열에서
계산할 수 있는 파생값이다. 독립 정보가 아니므로 분포를 세는 건 의미가 없고, 대신
**무결성 검사**로 쓴다 — 선언값과 실제 턴 수가 어긋나면 파일에서 턴이 누락된 것이다.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ragdiag import settings
from ragdiag.schema import Case


_PARA_BREAK = re.compile(r"\n\s*\n")


def split_concatenated(text: str) -> list[str]:
    """청크를 이어붙인 통문자열에서 경계를 복원한다.

    빈 줄(\n\n)을 먼저 시도하고, 그걸로 안 쪼개질 때만 단일 개행으로 내려간다. 순서가
    중요하다 - 청크 내부에도 개행이 있을 수 있으므로, 단일 개행부터 쪼개면 한 청크가
    여러 조각으로 찢어진다. 청크가 단일 개행으로 이어붙여져 있고 내부에도 개행이 있으면
    경계는 원리적으로 복원 불가능하다 - 인용 검증은 전 청크를 훑으므로(verify_evidence)
    잘못 쪼개진 경계는 index_corrected 로 흡수된다.
    """
    parts = [p.strip() for p in _PARA_BREAK.split(text) if p.strip()]
    if len(parts) > 1:
        return parts
    return [p.strip() for p in text.split("\n") if p.strip()]

# history_input 이 없을 때 턴 순서로 자르는 폴백 창. 있으면 안 본다 (pre_queries).
MAX_HISTORY_TURNS = settings.MAX_HISTORY_TURNS


# ---------------------------------------------------------------------------
# 정규화 헬퍼 — 실데이터의 흔한 흠집을 흡수한다
# ---------------------------------------------------------------------------

def _as_bool(value: Any) -> Optional[bool]:
    """trace_matched 가 "True"/"False" 문자열로 온다."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "y", "yes"):
            return True
        if lowered in ("false", "0", "n", "no"):
            return False
    return None


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def parse_retrieved(value: Any) -> list[str]:
    """retrieved_data 를 청크 리스트로.

    관측된 형태: "[]" · '["a", "b"]' (JSON을 담은 문자열) · 실제 리스트 · null.
    JSON 문자열이 정상 형태지만, 이스케이프가 깨진 채 오는 경우도 있어
    파싱 실패 시 통문자열로 취급해 경계를 복원한다(이전 포맷과 같은 처리).
    """
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        text = value.strip()
        if not text or text == "[]":
            return []
        try:
            parsed = json.loads(text)
            items = parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            return split_concatenated(text)
    else:
        return [str(value)]

    chunks = []
    for item in items:
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            text = item.get("text") or item.get("content") or item.get("chunk") or ""
        else:
            text = str(item)
        if text.strip():
            chunks.append(text)
    return chunks


def parse_tool_output(value: Any) -> list[str]:
    """도구 결과를 청크 리스트로. 두 모양이 온다.

    턴 레벨(`tool_output`)은 통문자열이고, `history_input.tool_output` 은 호출
    단위로 묶인 구조체 배열이다:

        [{"turn_no": 1,
          "tool_calls": [{"name": ..., "arguments": ...}],
          "outputs": ["...", "..."]}]

    **청크로 쓰는 것은 `outputs` 뿐이다.** `tool_calls` 는 무엇을 물었는지지
    무엇이 나왔는지가 아니라 충족도 대조의 대상이 아니고, outputs 와 인덱스로
    짝이 맞는지도 아직 확인되지 않았다 - 짝을 가정해 붙이면 틀린 짝이 근거로
    인용된다.

    `turn_no` 도 안 붙인다. 청크 본문에 머리말을 끼우면 인용 대조(연속 일치
    `match_threshold`)가 보는 문자열이 로그에 없던 것으로 바뀐다.
    """
    if isinstance(value, list) and any(
            isinstance(item, dict) and "outputs" in item for item in value):
        chunks = []
        for entry in value:
            if not isinstance(entry, dict):
                continue
            for out in entry.get("outputs") or []:
                text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
                if text.strip():
                    chunks.append(text)
        return chunks
    return parse_retrieved(value)


def parse_tool_entries(value: Any) -> list[dict]:
    """도구 호출 기록을 호출 단위로 편다. v3 가 T1 · T2 · T3 와 태그에 쓴다.

        [{"turn_no": 1, "tool_calls": [{"name", "arguments"}], "outputs": [...]}]

    반환: [{"turn_no", "order", "name", "arguments", "outputs": [...]}] — 호출 하나가 원소다.
    `order` 는 로그에 적힌 순서(0부터)다. outputs 는 호출과 인덱스로 짝이 맞는지 확인되지
    않았으므로 **엔트리의 outputs 전부**를 그 엔트리의 호출마다 붙인다 - 짝을 가정하지 않는다.
    """
    if not isinstance(value, list):
        return []
    out = []
    order = 0
    for entry in value:
        if not isinstance(entry, dict):
            continue
        calls = entry.get("tool_calls")
        outputs = []
        for o in entry.get("outputs") or []:
            text = o if isinstance(o, str) else json.dumps(o, ensure_ascii=False)
            if text.strip():
                outputs.append(text)
        if not isinstance(calls, list) or not calls:
            if "name" in entry:                  # 호출 하나가 바로 엔트리인 모양
                calls = [entry]
            else:
                continue
        for call in calls:
            if not isinstance(call, dict):
                continue
            args = call.get("arguments")
            if not isinstance(args, str):
                args = json.dumps(args, ensure_ascii=False) if args is not None else ""
            out.append({"turn_no": _as_int(entry.get("turn_no")), "order": order,
                        "name": str(call.get("name") or ""), "arguments": args,
                        "outputs": list(outputs)})
            order += 1
    return out


@dataclass(frozen=True)
class HistoryInput:
    """서비스가 이 턴을 답할 때 모델에 **실제로 넣은 입력**. 직전 턴까지다.

    이게 있으면 **턴 레코드 하나가 자족적이다** - 과거를 알려고 다른 턴의 레코드를
    열 필요가 없다. 같은 이름의 키가 턴 레벨에도 있고 여기에도 있는데, 한 레코드
    안의 두 자리다: 턴 레벨이 이 턴 것이고 여기가 ~N-1 것이다. **둘은 겹치지
    않는다** - 그래서 청크 풀은 둘을 더하면 되고, 턴들을 따로 순회하면 같은 것을
    두 번 넣는다.

    `present` 를 따로 두는 이유는 "키가 없다"(옛 로그 · 골든셋)와 "있는데 비었다"
    (맥락 없이 답한 첫 턴)가 다른 사실이라서다. 전자면 턴 순서 추정으로 떨어져야
    하고 후자면 추정하면 안 된다 - 서비스가 정말 아무것도 안 넣은 것이다.
    """

    present: bool = False
    queries: list[str] = field(default_factory=list)
    # assistant 메시지. 순서대로.
    answers: list[str] = field(default_factory=list)
    # user · assistant 를 섞어 원래 순서대로. v4 불만 판정이 이걸 받는다.
    messages: list[dict] = field(default_factory=list)
    retrieved: list[str] = field(default_factory=list)
    tool_output: list[str] = field(default_factory=list)
    # 호출 단위 기록 (parse_tool_entries). 청크 출처와 T 묶음이 쓴다.
    tool_calls: list[dict] = field(default_factory=list)
    memory: str = ""


def parse_history_input(value: Any) -> HistoryInput:
    """`history_input` 을 우리가 쓰는 네 갈래로 가른다.

    `history_chat` 은 role/content 메시지 배열이다. user 만 뽑은 것이 `pre_queries` 를
    대신하고, user · assistant 를 원래 순서대로 둔 `messages` 가 불만 판정의 history 다.
    """
    if not isinstance(value, dict):
        return HistoryInput()
    queries = []
    answers = []
    messages = []
    for message in value.get("history_chat") or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "")).strip().lower()
        content = message.get("content")
        if not (isinstance(content, str) and content.strip()):
            continue
        if role == "user":
            queries.append(content)
        elif role == "assistant":
            answers.append(content)
        else:
            continue
        messages.append({"role": role, "content": content})
    return HistoryInput(
        present=True,
        queries=queries,
        answers=answers,
        messages=messages,
        retrieved=parse_retrieved(value.get("retrieved_data")),
        tool_output=parse_tool_output(value.get("tool_output")),
        tool_calls=parse_tool_entries(value.get("tool_output")),
        memory=value.get("memory") or "",
    )


def _as_questions(value: Any) -> list[str]:
    """prev_question 은 str 로도 list 로도 온다 (실행 환경 2026-09-01, 16,141건)."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item.strip()]
    return []


def _normalize_alternatives(raw: Any) -> list[dict]:
    """대안 목록의 키 오타를 흡수한다.

    실제로 관측된 것: " probability"(앞 공백), "lable"(label 오타).
    이런 걸 그대로 두면 확률 기반 필터가 조용히 빈 값을 읽는다.
    """
    if not isinstance(raw, list):
        return []
    fixed = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entry = {}
        for key, value in item.items():
            clean = key.strip()
            if clean == "lable":
                clean = "label"
            entry[clean] = value
        fixed.append({
            "label": entry.get("label", ""),
            "name": entry.get("name", ""),
            "probability": _as_float(entry.get("probability")) or 0.0,
        })
    return fixed


# ---------------------------------------------------------------------------
# 자료구조
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UserMeta:
    """사용자 식별자는 **로그에 없다** (2026-10, user_id · db_login_id 삭제).

    남은 것은 조직 속성뿐이다. 그래서 집계는 부서 · 직급 축으로만 돌고, "같은 사람이
    반복해서 겪는 실패" 는 셀 수 없다. 대화 식별자가 전역 유일하다는 것이 확인되어
    Case 식별은 그쪽으로 넘겼다 (`to_case`).
    """

    dept: str
    job_grade: str
    job_name: str


@dataclass(frozen=True)
class Turn:
    turn: int
    event_time: str
    user_question: str
    llm_response: str
    retrieved: list[str]
    # 도구 결과. **문서 검색 결과와 같은 성격이고 답변 생성에 들어간다** - 그래서
    # retrieved 와 같은 층에 두고 청크 풀에 함께 넣는다. 이것만 빼고 보면 도구
    # 결과를 제대로 쓴 답변이 case22(생성 실패) 로, 그 인용이 case24(지어낸 인용)
    # 로 집계된다. 둘 다 조용히 틀린다.
    tool_output: list[str]
    # 서비스가 이 턴을 답할 때 **실제로 끌고 들어간** 앞 턴 번호들. 자기 턴은 없다.
    # 전에는 턴 순서로 최근 3개를 우리가 추정했다 - 이건 추정이 아니라 사실이다.
    # history_input 이 있으면 **내용까지** 사실이라 이 번호들로 할 일이 없다. 남은
    # 쓰임은 둘이다: history_input 없는 옛 로그에서 scope 를 자르는 것과,
    # features/carried 가 "그전 추정이 얼마나 맞았나" 를 세는 것.
    carried_turn_nos: list[int]
    carried_turn_count: Optional[int]
    # 서비스가 들고 있던 요약 맥락. **판정 LLM 에는 넘기지 않는다** - 다른 LLM 이 쓴
    # 해석이라 넘기면 우리 관측이 그쪽으로 끌려간다. 앞에서 정한 조건이 원문 턴 대신
    # 여기 남아 있을 수 있어서 history_quote 대조 대상에만 더한다.
    memory: str
    prev_questions: list[str]
    trace_matched: Optional[bool]
    # 이 턴이 직전 턴과 어떤 관계인지에 대한 기존 분류. 필터가 거는 대상.
    eval_result: str
    eval_score: Optional[float]
    eval_score_top1: Optional[float]
    eval_alternatives: list[dict] = field(default_factory=list)
    emotion_result: str = ""
    emotion_score: Optional[float] = None
    emotion_score_top1: Optional[float] = None
    emotion_alternatives: list[dict] = field(default_factory=list)
    # 모델에 실제로 들어간 ~N-1 턴의 입력. pre_queries 재구성과 청크 풀이 여기 기댄다.
    history: HistoryInput = field(default_factory=HistoryInput)
    # **이 턴의** 도구 호출 기록 (턴 레벨 `tool_calls` 가 있는 로그만). 없으면 빈 목록이고
    # 이 턴의 tool_output 은 이름 없는 "tool" 출처가 된다.
    tool_calls: list[dict] = field(default_factory=list)
    # 라우팅 계열 넷. **판정에는 안 쓴다** - 어느 플랫폼에서 묻고 어디가 답했는지는
    # 실패의 원인이 아니라 실패가 일어난 자리다. 값의 모양을 회수하려고 받아만 둔다.
    # answered_by 가 집계 축이 될 수 있는데, 실제 값을 보고 정할 일이다. fallback 은
    # 모델이 스스로 다른 서비스로 넘겼다 돌아온 것이라 자원 부족(I1)과 무관하다.
    ask_on: str = ""
    answered_by: str = ""
    route_intent: str = ""
    fallback: str = ""

    @property
    def is_followup(self) -> bool:
        """직전 턴에 이어진 질문인가 — turn ≥ 2.

        전에는 eval_result 가 있나로 봤다. eval 이 비어서 오는 입력(eval.jsonl)이 생겨
        턴 번호로 바꿨다. 직전 턴이 실제로 있는지는 쓰는 쪽이 turn_at 으로 따로 본다.
        """
        return self.turn >= 2


@dataclass(frozen=True)
class Conversation:
    chat_id: str
    user: UserMeta
    turns: list[Turn]

    @property
    def declared_multi_turn(self) -> Optional[bool]:
        """turns 가 선언한 trace_matched. 턴들이 서로 다른 값을 가지면 None."""
        flags = {t.trace_matched for t in self.turns if t.trace_matched is not None}
        return flags.pop() if len(flags) == 1 else None

    @property
    def actual_multi_turn(self) -> bool:
        return len(self.turns) >= 2

    def turn_at(self, number: int) -> Optional[Turn]:
        for t in self.turns:
            if t.turn == number:
                return t
        return None


# ---------------------------------------------------------------------------
# 파싱
# ---------------------------------------------------------------------------

def _as_turn_nos(value: Any) -> list[int]:
    """carried_turn_nos. 문자열 "[1, 2]" 로 오는 경우까지 받는다 — 이 로그의
    retrieved_data 가 이미 그렇게 온 전례가 있어서다. 정수가 아닌 항목은 버린다."""
    if isinstance(value, str):
        try:
            value = json.loads(value.strip() or "[]")
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


# 턴 시각의 키. 배포마다 event_time 이기도 request_time 이기도 하다 — 같은 뜻이고 앞이 이긴다.
EVENT_TIME_KEYS = ("event_time", "request_time")


def event_time_of(raw: dict) -> str:
    """턴 레코드의 시각. event_time 이 없거나 비면 request_time."""
    return raw.get("event_time") or raw.get("request_time") or ""


def _parse_turn(raw: dict) -> Turn:
    return Turn(
        turn=int(raw.get("turn", -1)),
        event_time=event_time_of(raw),
        user_question=raw.get("user_question") or "",
        llm_response=raw.get("llm_response") or "",
        retrieved=parse_retrieved(raw.get("retrieved_data")),
        tool_output=parse_tool_output(raw.get("tool_output")),
        carried_turn_nos=_as_turn_nos(raw.get("carried_turn_nos")),
        carried_turn_count=_as_int(raw.get("carried_turn_count")),
        memory=raw.get("memory") or "",
        prev_questions=_as_questions(raw.get("prev_question")),
        trace_matched=_as_bool(raw.get("trace_matched")),
        history=parse_history_input(raw.get("history_input")),
        tool_calls=parse_tool_entries(raw.get("tool_calls")),
        ask_on=raw.get("ask_on") or "",
        answered_by=raw.get("answered_by") or "",
        route_intent=raw.get("route_intent") or "",
        fallback=raw.get("fallback") or "",
        eval_result=raw.get("llm_eval_result") or "",
        eval_score=_as_float(raw.get("llm_eval_score")),
        eval_score_top1=_as_float(raw.get("llm_eval_score_top1")),
        eval_alternatives=_normalize_alternatives(raw.get("llm_eval_alternatives")),
        emotion_result=raw.get("llm_emotion_result") or "",
        emotion_score=_as_float(raw.get("llm_emotion_score")),
        emotion_score_top1=_as_float(raw.get("llm_emotion_score_top1")),
        emotion_alternatives=_normalize_alternatives(raw.get("llm_emotion_alternatives")),
    )


def parse_conversations(raw: dict) -> list[Conversation]:
    conversations: list[Conversation] = []
    for position, user_raw in enumerate(raw.get("users", [])):
        user = UserMeta(
            dept=user_raw.get("db_dept_name") or "unknown",
            job_grade=user_raw.get("job_grade") or "unknown",
            job_name=user_raw.get("db_job_name") or "unknown",
        )
        for index, conv_raw in enumerate(user_raw.get("conversations", [])):
            # chat_id 가 빠져 있는 대화가 실제로 있다. 케이스 식별자가
            # 겹치지 않도록 배열 위치로 채운다 - 사용자 식별자가 없어진 뒤로는
            # 이것이 두 대화를 가를 유일한 값이다.
            chat_id = conv_raw.get("chat_id") or f"u{position}#{index}"
            turns = sorted(
                (_parse_turn(t) for t in conv_raw.get("turns", [])),
                key=lambda t: t.turn,
            )
            conversations.append(Conversation(chat_id, user, turns))
    return conversations


def load_conversations(path: str | Path) -> list[Conversation]:
    return parse_conversations(json.loads(Path(path).read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# 진단 케이스로 변환
# ---------------------------------------------------------------------------

def to_case(
    conv: Conversation,
    followup_turn: int,
    history_turns: Optional[int] = None,
) -> Optional[Case]:
    """후속 턴 번호를 받아 진단 케이스를 만든다.

    followup_turn 이 불만이 표현된 턴이고, 그 직전 턴이 비판받은 답변이다.
    직전 턴이 없으면(첫 턴을 지목한 경우) 판정할 대상이 없으므로 None.

    history_turns 는 Step 1 에 넘길 이전 질문의 개수 상한이다. 잘라내더라도
    **비판받은 답변을 부른 질문은 항상 포함된다** — 그게 마지막 항목이다.

    **맥락의 경계는 로그가 정한다.** 비판받은 답변의 `carried_turn_nos` 가 서비스가
    그 답변에 실제로 넣은 앞 턴들이다. 그 값이 있으면 그걸 쓰고, 없으면(옛 로그 ·
    골든셋) 전처럼 턴 순서로 자른다. 추정과 사실이 어긋나면 판정이 조용히 틀린다 -
    챗봇이 못 본 턴에서 "앞에서 정한 조건" 을 찾아 case14 를 내는 식이다.
    """
    # 기본 인자는 def 시점에 굳는다. 설정을 나중에 적용해도 안 먹으므로
    # None 으로 받고 여기서 푼다.
    if history_turns is None:
        history_turns = settings.MAX_HISTORY_TURNS
    followup = conv.turn_at(followup_turn)
    if followup is None:
        return None
    prior = [t for t in conv.turns if t.turn < followup_turn]
    if not prior:
        return None
    answered = prior[-1]

    # scope 는 **옛 로그용 폴백**이다. history_input 이 있으면 pre_queries 도
    # chunk_pool 도 answered 레코드 하나로 끝나서 여기를 안 본다.
    carried = set(answered.carried_turn_nos)
    if carried:
        # 답변을 부른 질문은 그 목록에 없어도 반드시 들어간다 - 그 질문이 없으면
        # 무엇에 대한 답인지 자체를 알 수 없다.
        scope = [t for t in prior if t.turn in carried or t is answered]
    else:
        scope = prior[-history_turns:] if history_turns > 0 else prior

    case_id = f"{conv.chat_id}:{followup_turn}"
    sourced = chunk_pool_with_sources(answered, scope)
    n_fetched = len(answered.retrieved) + len(answered.tool_output)

    tool_calls = [*answered.tool_calls,
                  *[c for c in answered.history.tool_calls]]
    tool_outputs = list(answered.tool_output) + list(answered.history.tool_output)
    # v4 — 불만 판정의 history. history_chat 이 있으면 그대로(사실은 자르지 않는다), 비었고
    # 앞 턴이 있으면 최근 3턴을 재구성한다 (docs/design/decision_tree_v4.md "history 규칙").
    if answered.history.messages:
        history_messages, reconstructed = list(answered.history.messages), 0
    else:
        history_messages = reconstruct_history(prior, answered)
        reconstructed = sum(1 for m in history_messages if m["role"] == "user")
    return Case(
        case_id=case_id,
        dept=conv.user.dept,
        job_grade=conv.user.job_grade,
        job_name=conv.user.job_name,
        chat_id=conv.chat_id,
        turn=followup_turn,
        # 마지막 항목이 비판받은 답변을 부른 질문이다.
        pre_queries=pre_queries(answered, scope),
        llm_ans_on_last_q=answered.llm_response,
        current_query=followup.user_question,
        rag_chunks=[c for c, _ in sourced],
        chunk_sources=[s for _, s in sourced],
        n_fetched=n_fetched,
        # history_quote 대조 대상. 앞에서 정한 조건이 원문 턴 대신 요약에만
        # 남아 있을 수 있는데, 그래도 챗봇은 그 조건을 본 것이다.
        memory=memory_pool(answered),
        tool_calls=tool_calls,
        tool_outputs=tool_outputs,
        prior_turn_nos=[t.turn for t in prior],
        history_present=answered.history.present,
        history_turn_count=len(answered.history.queries),
        history_messages=history_messages,
        history_reconstructed=reconstructed,
        event_time=followup.event_time,
        target_event_time=answered.event_time,
        answered_by=answered.answered_by,
        ask_on=answered.ask_on,
        fallback=answered.fallback,
    )


# 재구성 상한. history_chat 이 비었을 때만 쓴다 — 사실(history_chat)은 자르지 않는다.
RECONSTRUCT_TURNS = 3


def reconstruct_history(prior: list[Turn], answered: Turn,
                        limit: int = RECONSTRUCT_TURNS) -> list[dict]:
    """history_chat 이 비었을 때 턴 순서로 앞 대화를 되살린다. 턴마다 user → assistant.

    `carried_turn_nos` 가 있으면 그 턴들(서비스가 넣었다고 적은 것), 없으면 answered 앞의 최근
    턴들. 어느 쪽이든 최근 `limit` 개만 — 이건 추정이라 넓게 틀리면 "못 본 조건을 어겼다" 가
    된다. 재구성은 "사용자가 전에 그 요구를 했나"(불만 판정 7) 를 위한 것이고, 모델이 그걸
    봤는지는 앞 턴 누락 플래그가 따로 말한다.
    """
    before = [t for t in prior if t is not answered]
    carried = set(answered.carried_turn_nos)
    if carried:
        before = [t for t in before if t.turn in carried]
    if limit > 0:
        before = before[-limit:]
    out: list[dict] = []
    for t in before:
        if t.user_question:
            out.append({"role": "user", "content": t.user_question})
        if t.llm_response:
            out.append({"role": "assistant", "content": t.llm_response})
    return out


def pre_queries(answered: Turn, scope: list[Turn]) -> list[str]:
    """Step 1 에 넘길 이전 질문들. **마지막 항목이 비판받은 답변을 부른 질문이다.**

    세 갈래이고 위에서부터 이긴다. 위로 갈수록 사실에 가깝다.

        1. history_input.history_chat   모델에 실제로 들어간 질문들
        2. prev_question                서비스가 적어 준 앞 질문들
        3. 턴 순서 재구성                우리 추정 (옛 로그 · 골든셋)

    1·2 는 **직전 턴까지**라서 비판받은 답변을 부른 질문이 들어 있지 않다. 따로
    붙인다 - 그게 없으면 무엇에 대한 답인지 자체를 알 수 없고, `pre_queries[-1]`
    을 보는 pii 검증기도 무너진다. 3 은 scope 에 그 턴이 이미 들어 있다.

    3 을 남겨 두는 이유는 골든셋이다. 픽스처에는 두 필드가 다 없어서, 2단으로
    끊으면 골든셋이 통째로 빈 맥락으로 돌고 회귀가 난다.

    1·2 에는 `history_turns` 상한을 걸지 않는다. 상한은 추정이 넓게 틀리는 것을
    막으려고 둔 것인데, 이 둘은 추정이 아니라 챗봇이 실제로 본 것이다. 사실을
    자르면 못 본 턴 대신 **본 턴**을 지우게 된다.
    """
    carried = answered.history.queries or answered.prev_questions
    if carried:
        tail = [answered.user_question] if answered.user_question else []
        return [*carried, *tail]
    return [t.user_question for t in scope if t.user_question]


def memory_pool(answered: Turn) -> str:
    """history_quote 코드 대조 대상. 판정 LLM 에는 안 넘긴다.

    턴의 `memory` 와 `history_input.memory` 를 합친다. 둘 다 "챗봇이 본 요약 맥락"
    이고, 이 값은 분석 대상이 아니라 **대조 대상**이라 넓을수록 안전하다 - 넓으면
    "앞에서 정한 조건을 챗봇이 봤다"를 더 많이 인정하게 되고, 그 방향은 case14
    오탐을 줄인다. 중복은 부분 일치라 해롭지 않다.
    """
    parts = [p for p in (answered.memory, answered.history.memory) if p.strip()]
    if len(parts) == 2 and parts[1] in parts[0]:
        return parts[0]
    return "\n".join(parts)


def chunk_pool(answered: Turn, scope: list[Turn]) -> list[str]:
    """비판받은 답변이 **실제로 볼 수 있었던 문서 전부.**

    새 포맷에서는 `answered` **레코드 하나로 끝난다.** 과거가 통째로 그 턴의
    `history_input` 안에 있어서 다른 턴의 레코드를 열 일이 없다. 한 레코드 안의
    네 자리를 더하는 것이고, 네 자리는 서로 겹치지 않는다.

        이 턴 자신      retrieved_data              tool_output
        history_input   .retrieved_data             .tool_output (outputs)

    **이 턴 것을 먼저 넣는다.** 충족도 판정의 본령이 그 문서이고 과거 쪽은 보조라,
    순서가 곧 중요도다.

    `scope` 를 도는 아래 가지는 `history_input` 이 **없을 때만** 탄다 (옛 로그 ·
    골든셋). 둘 다 타면 같은 도구 결과가 두 번 들어가고, 중복 청크는 인용 대조에서
    `index_corrected` 를 양산한다.

    과거 턴의 `retrieved_data` 가 풀에 들어오는 것은 2026-10 의 전제가 뒤집힌
    것이다. 전에는 "서비스가 넘기지 않는다"고 적혀 있었는데 `history_input` 이
    넘긴다. 이 집합이 넓어지면 **case20(문서에 없었다)이 case22(있었는데 안 썼다)로
    옮겨 간다** - 고칠 곳이 문서팀에서 생성 쪽으로 바뀐다.

    상한은 두지 않는다. Step 2 골든셋이 문서 10~15개 기준이라 풀이 그보다 한참
    커지면 약한 모델이 무너질 수 있는데, **실데이터에서 실제로 커지는지를 아직
    모른다.** 첫 실행의 `carried` 지표가 평균·최대를 찍으므로 그 숫자를 보고
    필요하면 그때 넣는다.
    """
    return [c for c, _ in chunk_pool_with_sources(answered, scope)]


def _tool_source(prefix: str, calls: list[dict], outputs: list[str]) -> list[str]:
    """도구 결과마다 출처 이름. 호출 기록이 하나의 이름뿐이면 그 이름, 아니면 이름 없이."""
    names = sorted({c.get("name", "") for c in calls if c.get("name")})
    tag = f"{prefix}:{names[0]}" if len(names) == 1 else prefix
    return [tag] * len(outputs)


def chunk_pool_with_sources(answered: Turn, scope: list[Turn]) -> list[tuple[str, str]]:
    """청크와 출처의 쌍. 순서는 chunk_pool 과 같다 - 이 턴 것이 먼저.

    출처: retrieved · tool[:name] · history_retrieved · history_tool[:name]. v3 가 D1 과 T2 를
    가르고(검색 도구 결과인가 업무 도구 결과인가) G5[과거근거] 를 붙이는 데 쓴다.
    history_input.tool_output 은 엔트리 단위로 outputs 가 묶여 있어 엔트리마다 이름을 붙인다.
    """
    out: list[tuple[str, str]] = [(c, "retrieved") for c in answered.retrieved]
    out += zip(answered.tool_output,
               _tool_source("tool", answered.tool_calls, answered.tool_output))
    if answered.history.present:
        out += [(c, "history_retrieved") for c in answered.history.retrieved]
        # 엔트리 단위로 이름을 붙인다. parse_tool_entries 가 엔트리의 outputs 를 호출마다
        # 복제해 두었으므로 여기서는 호출 기록을 엔트리로 되묶는다.
        seen: set[int] = set()
        sourced_outputs: list[tuple[str, str]] = []
        for call in answered.history.tool_calls:
            key = id(call["outputs"]) if call.get("outputs") else None
            if key is None or key in seen:
                continue
            seen.add(key)
            same = [c for c in answered.history.tool_calls if c.get("outputs") is call["outputs"]]
            sourced_outputs += zip(call["outputs"],
                                   _tool_source("history_tool", same, call["outputs"]))
        named = {text for text, _ in sourced_outputs}
        out += sourced_outputs
        out += [(c, "history_tool") for c in answered.history.tool_output if c not in named]
        return out
    for turn in scope:
        if turn is answered:
            continue
        out += zip(turn.tool_output, _tool_source("history_tool", turn.tool_calls, turn.tool_output))
    return out
