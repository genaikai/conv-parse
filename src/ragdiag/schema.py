"""데이터 구조 정의 — Case 하나뿐이다.

v3 까지 여기 있던 판정 LLM 의 Pydantic 출력 모델(관측 · 충족도 · 주장 · 인용)은 v4 에서 없어졌다.
범주 판정은 전부 kev 문항(questions.py)이고 문장을 만드는 자리가 없다.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Case:
    """분석 단위. 비판받은 답변(turn N)과 그 답변이 볼 수 있었던 것 전부, 그리고 불만(turn N+1).

    사용자 메타는 상위 노드에서 상속받는다. 식별자는 둘 다 싣는다 — turn · event_time 은 불만
    턴(N+1), target_* 는 답변 턴(N). 하나만 실으면 사내 조인이 한 턴 어긋난다.
    """

    case_id: str
    dept: str
    job_grade: str
    job_name: str
    chat_id: str
    turn: int
    pre_queries: list[str]
    llm_ans_on_last_q: str
    current_query: str
    # 비판받은 답변이 볼 수 있었던 문서 전부 (conv.chunk_pool). 그 턴이 가져온
    # retrieved_data · tool_output 에 history_input 으로 넘어온 과거 것까지다.
    rag_chunks: list[str]
    # 서비스가 들고 있던 사용자 정보 (turn N 의 memory + history_input.memory).
    memory: str = ""
    # **이 턴이** 가져온 청크 수 (retrieved_data + tool_output). None 이면 모른다 (옛 경로).
    n_fetched: Optional[int] = None
    # rag_chunks 와 길이가 같다. 청크마다 출처: retrieved · tool[:name] · history_retrieved ·
    # history_tool[:name]. 근거 판정이 네 칸으로 가르는 기준이다.
    chunk_sources: list[str] = field(default_factory=list)
    # 이 턴 + history_input 의 도구 호출. [{turn_no, order, name, arguments}]. 순서 보존.
    tool_calls: list[dict] = field(default_factory=list)
    # 도구 결과 본문만 (풀에도 들어 있다).
    tool_outputs: list[str] = field(default_factory=list)
    # 대화에서 비판받은 턴보다 앞선 턴 번호 전부. 앞 턴 누락 플래그가 history_chat 과 대조한다.
    prior_turn_nos: list[int] = field(default_factory=list)
    # history_input 이 있었나 · 그 안의 user 메시지 수. 없으면(옛 로그) 플래그를 판정하지 않는다.
    history_present: bool = False
    history_turn_count: int = 0
    # --- v4 (docs/design/decision_tree_v4.md) ---
    # 불만 판정에 주는 앞 대화. history_chat 그대로이거나(재구성 0) 턴 순서로 재구성한 것.
    history_messages: list[dict] = field(default_factory=list)   # [{"role", "content"}, …]
    history_reconstructed: int = 0                                 # 재구성했으면 그 턴 수
    event_time: str = ""            # 불만 턴(N+1)
    target_event_time: str = ""     # 답변 턴(N)
    answered_by: str = ""           # 답변 턴의 축
    ask_on: str = ""
    fallback: str = ""

    @property
    def last_query(self) -> str:
        return self.pre_queries[-1] if self.pre_queries else ""

    # 근거 판정의 네 칸. 풀을 출처로 가른다 (conv.chunk_pool_with_sources 의 이름 규칙).
    def _chunks_where(self, keep) -> list[str]:
        return [c for c, s in zip(self.rag_chunks, self.chunk_sources) if keep(s)]

    @property
    def retrieved_chunks(self) -> list[str]:
        return self._chunks_where(lambda s: s == "retrieved")

    @property
    def tool_chunks(self) -> list[str]:
        return self._chunks_where(lambda s: s == "tool" or s.startswith("tool:"))

    @property
    def history_chunks(self) -> list[str]:
        return self._chunks_where(lambda s: s.startswith("history_"))
