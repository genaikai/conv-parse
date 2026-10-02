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

# Step 1 에 넘길 이전 질문의 최대 개수.
# 대명사 해소에 필요한 것은 보통 직전 2~3턴이다. 그보다 오래된 질문은 노이즈에
# 가깝고, resolved_question 을 엉뚱한 주제로 끌고 갈 수 있다. 긴 대화(필터에
# "51턴 이상" 구간이 있다)에서는 입력 토큰도 턴 수에 비례해 늘어난다.
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
    request_time: str
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
    # 끌려온 것은 그 턴들의 질문 · 답변 · tool_output 이고 retrieved_data 는 아니다.
    carried_turn_nos: list[int]
    carried_turn_count: Optional[int]
    # 서비스가 들고 있던 요약 맥락. **판정 LLM 에는 넘기지 않는다** - 다른 LLM 이 쓴
    # 해석이라 넘기면 우리 관측이 그쪽으로 끌려간다. 앞에서 정한 조건이 원문 턴 대신
    # 여기 남아 있을 수 있어서 history_quote 대조 대상에만 더한다.
    memory: str
    prev_question: str
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

    @property
    def is_followup(self) -> bool:
        """직전 턴에 이어진 질문인가. turn 1은 eval_result 가 비어 있다."""
        return bool(self.eval_result)


@dataclass(frozen=True)
class Conversation:
    conversation_id: str
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


def _parse_turn(raw: dict) -> Turn:
    return Turn(
        turn=int(raw.get("turn", -1)),
        request_time=raw.get("request_time") or "",
        user_question=raw.get("user_question") or "",
        llm_response=raw.get("llm_response") or "",
        retrieved=parse_retrieved(raw.get("retrieved_data")),
        tool_output=parse_retrieved(raw.get("tool_output")),
        carried_turn_nos=_as_turn_nos(raw.get("carried_turn_nos")),
        carried_turn_count=_as_int(raw.get("carried_turn_count")),
        memory=raw.get("memory") or "",
        prev_question=raw.get("prev_question") or "",
        trace_matched=_as_bool(raw.get("trace_matched")),
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
            # conversation_id 가 빠져 있는 대화가 실제로 있다. 케이스 식별자가
            # 겹치지 않도록 배열 위치로 채운다 - 사용자 식별자가 없어진 뒤로는
            # 이것이 두 대화를 가를 유일한 값이다.
            conv_id = conv_raw.get("conversation_id") or f"u{position}#{index}"
            turns = sorted(
                (_parse_turn(t) for t in conv_raw.get("turns", [])),
                key=lambda t: t.turn,
            )
            conversations.append(Conversation(conv_id, user, turns))
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

    carried = set(answered.carried_turn_nos)
    if carried:
        # 답변을 부른 질문은 끌려온 목록에 없어도 반드시 들어간다 - 그 질문이
        # 없으면 무엇에 대한 답인지 자체를 알 수 없다.
        scope = [t for t in prior if t.turn in carried or t is answered]
    else:
        scope = prior[-history_turns:] if history_turns > 0 else prior

    return Case(
        case_id=f"{conv.conversation_id}:{followup_turn}",
        dept=conv.user.dept,
        job_grade=conv.user.job_grade,
        job_name=conv.user.job_name,
        conversation_id=conv.conversation_id,
        turn=followup_turn,
        # 마지막 항목이 비판받은 답변을 부른 질문이다.
        pre_queries=[t.user_question for t in scope if t.user_question],
        llm_ans_on_last_q=answered.llm_response,
        current_query=followup.user_question,
        rag_chunks=chunk_pool(answered, scope),
        # history_quote 대조 대상. 앞에서 정한 조건이 원문 턴 대신 요약에만
        # 남아 있을 수 있는데, 그래도 챗봇은 그 조건을 본 것이다.
        memory=answered.memory,
    )


def chunk_pool(answered: Turn, scope: list[Turn], cap: Optional[int] = None) -> list[str]:
    """비판받은 답변이 **실제로 볼 수 있었던 문서 전부.**

    세 갈래다. 끌려온 턴에서 오는 것은 `tool_output` 뿐이다 - 그 턴들의
    `retrieved_data` 는 서비스가 넘기지 않는다.

        비판받은 턴   retrieved_data + tool_output
        끌려온 턴들   tool_output

    **턴 N 것을 먼저 넣는다.** 상한에 걸려 잘려도 비판받은 답변의 문서는 남아야
    한다 - 그게 충족도 판정의 본령이고, 끌려온 턴 쪽은 보조다.
    """
    if cap is None:
        cap = settings.MAX_RAG_CHUNKS
    pool = list(answered.retrieved) + list(answered.tool_output)
    for turn in scope:
        if turn is answered:
            continue
        pool += turn.tool_output
    return pool[:cap] if cap > 0 else pool
