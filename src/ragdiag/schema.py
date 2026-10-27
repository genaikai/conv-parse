"""데이터 구조 정의.

- Case: 분석 단위(대화 한 턴). 중첩 JSON을 flatten한 결과.
- Stage1/2/3 출력: LLM이 채우는 Pydantic 모델. messages.parse()로 스키마가 강제된다.

Pydantic 모델의 필드 순서에 의미가 있다. JSON은 선언 순서대로 생성되므로
reasoning을 먼저, 결론을 나중에 두어야 모델이 근거를 쓴 뒤 판정하게 된다.
Stage2에서 evidence를 verdict보다 앞에 둔 것도 같은 이유 - 인용을 먼저 뽑게 하면
판정이 인용의 결과가 되고, 반대로 두면 인용이 판정의 사후 정당화가 된다.
"""

from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel, Field

Verdict = Literal["sufficient", "partial", "insufficient"]
UsedRag = Literal["used", "ignored", "contradicted"]

Label = Literal[
    "rag_insufficient",                 # 검색된 문서에 답이 없었음 -> 코퍼스/검색 보강 대상
    "rag_partial",                      # 일부만 충족
    "rag_sufficient_generation_failed", # 문서엔 답이 있었으나 생성이 활용 실패
    "rag_sufficient_other",             # 문서도 충분, 활용도 함 -> 깊이/표현 문제
    "out_of_scope",                     # 불만이 형식/스타일 -> rag와 무관
    "unclassified",                     # 불만 성격 판별 실패 -> 수동 검토 대상
]


@dataclass(frozen=True)
class Case:
    """분석 단위. 사용자 메타는 상위 노드에서 상속받는다."""

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
    # 서비스가 들고 있던 요약 맥락. 판정 LLM 에는 안 넘기고 코드 대조에만 쓴다.
    memory: str = ""
    # **이 턴이** 가져온 청크 수 (retrieved_data + tool_output). rag_chunks 에는
    # history_input 으로 넘어온 과거 문서가 섞여 있어서, "이번 턴 검색이 0건이었다"
    # 는 rag_chunks 로는 알 수 없다 - case21(Retrieve 미수행) 이 묻는 것이 그것이다.
    # None 이면 모른다는 뜻이고 라우팅은 rag_chunks 길이로 떨어진다 (옛 경로).
    n_fetched: Optional[int] = None
    # --- v3 에서 더한 것 (docs/design/taxonomy_v3.md "입력") ---
    # history_chat 의 assistant 메시지. 순서대로. ⑥ 일관성과 G2[약속] 대조가 읽는다.
    prior_answers: list[str] = field(default_factory=list)
    # rag_chunks 와 길이가 같다. 청크마다 출처: retrieved · tool:<name> · history_retrieved ·
    # history_tool:<name>. D1/T2 를 가르고 G5[과거근거] 를 붙이는 데 쓴다.
    chunk_sources: list[str] = field(default_factory=list)
    # 이 턴 + history_input 의 도구 호출. [{turn_no, order, name, arguments}]. 순서 보존.
    tool_calls: list[dict] = field(default_factory=list)
    # 도구 결과 본문만 (풀에도 들어 있다). T3 · tool_numbers 검증기가 읽는다.
    tool_outputs: list[str] = field(default_factory=list)
    # 대화에서 비판받은 턴보다 앞선 턴 번호 전부. C1 이 history_chat 과 대조한다.
    prior_turn_nos: list[int] = field(default_factory=list)
    # history_input 이 있었나 · 그 안의 user 메시지 수. 없으면 C1 을 판정하지 않는다.
    history_present: bool = False
    history_turn_count: int = 0

    @property
    def last_query(self) -> str:
        return self.pre_queries[-1] if self.pre_queries else ""

    @property
    def search_sources(self) -> set[str]:
        """검색 도구에서 온 청크의 출처 이름들 (settings.SEARCH_TOOL_NAMES 기준)."""
        from ragdiag import settings
        names = set(settings.SEARCH_TOOL_NAMES)
        out = set()
        for s in self.chunk_sources:
            if s in ("retrieved", "history_retrieved"):
                out.add(s)
            elif s.split(":", 1)[-1] in names:
                out.add(s)
        return out


class Evidence(BaseModel):
    chunk_index: int = Field(description="근거가 있는 청크의 0-기반 인덱스")
    quote: str = Field(description="해당 청크에서 글자 그대로 복사한 문장. 요약·수정 금지")


class SufficiencyJudgment(BaseModel):
    """Stage 2 출력. llm_ans_on_last_q를 보지 않고 문서만으로 채운다."""

    reasoning: str
    evidence: list[Evidence] = Field(
        description="unmet_need를 충족하는 근거. 없으면 빈 배열"
    )
    verdict: Verdict
    missing: str = Field(description="문서에 없어서 답할 수 없었던 것. sufficient면 빈 문자열")


class LegibilityCheck(BaseModel):
    """④′ 출력. 답변 문자열만 보고 "사람이 읽을 수 있는 글인가" 하나만 답한다."""

    reasoning: str = Field(description="어디가 읽을 수 없는지 한두 문장. 읽을 수 있으면 그렇다고만")
    quote: str = Field(
        default="",
        description="읽을 수 없다면 그 구절을 답변에서 **글자 그대로** 따온 것. 읽을 수 있으면 빈 문자열. "
                    "지어낸 구절은 원문 대조에서 걸러지고, 걸러지면 이 판정은 무효가 된다")
    legible: bool = Field(description="사람이 읽고 뜻을 잡을 수 있는 글인가")


class GroundingCheck(BaseModel):
    """Stage 3 출력. verdict가 sufficient일 때만 실행된다."""

    reasoning: str
    answer_used_rag: UsedRag


# ---------------------------------------------------------------------------
# Step 1 관측 스키마  (taxonomy 30개 확장용)
#
# 핵심은 **case를 고르지 않는다**는 점이다.
# 관측 가능한 사실만 내고, case는 코드 검증기(features/)의 결정적 검증과 함께 코드가 도출한다.
#
# 이렇게 두면 taxonomy 를 고쳐도 이 값들은 그대로 재사용된다 — 관측은 taxonomy 와
# 무관한 사실이기 때문이다. 라우팅만 다시 돌리면 된다.
#
# nullable 타입을 쓰지 않고 "none" 센티넬과 빈 문자열을 쓴 이유: 로컬 서빙의
# 구조화 출력 강제가 anyOf(null 허용)를 제대로 처리하지 못하는 경우가 있다.
# 평평한 스칼라만 쓰면 어느 백엔드에서도 안전하다.
# ---------------------------------------------------------------------------

# 오른쪽은 route 가 실제로 보내는 곳이다 (features/route/table.py). 거절 · 인젝션 ·
# 답변 잘림처럼 route 가 먼저 보는 조건에 안 걸렸을 때 기준.
ComplaintTarget = Literal[
    "none",              # 불만이 아니다 — 새 질문이거나 수긍  -> N0 (확률이 등급이 되고
                         #                                        코드 위반이 없을 때. 아니면 미분류)
    "tone",              # 말투·어조·용어가 마음에 안 듦     -> case16
    "format",            # 형식·구성이 마음에 안 듦         -> case12 (요구를 지켰으면 case13)
    "language",          # 요구한 언어가 아님               -> case10 (요구를 지켰으면 case13)
    "length",            # 너무 길다/짧다                   -> case11 (코드가 판정 안 해 늘 medium)
    "content_missing",   # 필요한 정보가 없음               -> question_domain 으로 갈린다. domain 이면
    "content_wrong",     # 담긴 정보가 틀림                    Step 2·3 을 거쳐 case20·21·22·18·17·13
    "no_answer",         # 답이 안 왔거나 끊김              -> 미분류 (case8 잘림은 텍스트로 판정하지 않는다)
    "inconsistency",     # 이전 답변과 다름                 -> 미분류 (case19 는 턴 하나로 판정 불가)
    "other",             #                                  -> out_of_taxonomy
]

QuestionDomain = Literal[
    "domain",            # 업무 문서를 찾아야 답할 수 있는 질문 -> 내용 불만이면 Step 2·3
    "general_knowledge", # 상식                            -> case25
    "calculation",       # 수식·날짜·산수                  -> case26
    "code",              # SQL/Python 등                   -> case27
    "tool_usage",        # Excel/Spotfire 등 도구 사용법    -> G6
    "task",              # 번역 · 작문 · 요약 같은 작업 요청 -> 문서 없음. G1/G3
    "technical",         # 반도체 · 공정 기술 질문          -> domain 처럼 근거 판정
    "unclear",           #                                 -> 대개 미분류
]

# 근거(문서 · 도구) 판정이 의미 있는 질문 유형.
DOC_DOMAINS = ("domain", "technical")

LengthRequestKind = Literal[
    "none", "max_chars", "max_sentences", "max_lines", "vague_short"
]

# 챗봇은 이전 질문들을 함께 받아 답한다. 그래서 "그거" 같은 지시어도 앞 질문들로 풀리면
# 문제가 아니다 - 예전에는 "그 문장 하나만으로 알 수 있나" 로 재서, 챗봇이 멀쩡히 풀었을
# 지시어까지 사용자 쪽 문제(U3 태그)로 셌다.
QuestionClarity = Literal[
    "clear",                 # 무엇을 묻는지 안다. 지시어가 있어도 앞 질문들로 풀리면 여기다
    "unresolved_reference",  # 앞 질문들을 봐도 지시 대상이 정해지지 않는다  -> U3 태그
    "vague",                 # 지시어 문제가 아니라 질문 자체가 답을 특정할 수 없다  -> U3 태그
]

FormatRequest = Literal[
    "none", "numbered_list", "bullet_list", "table", "code_block", "json", "prose"
]


class Observation(BaseModel):
    """Step 1 출력 — 관측만 하고 판정하지 않는다.

    필드 순서에 의미가 있다. reasoning 이 먼저 나와야 뒤의 값들이 근거의 결과가 된다.
    """

    reasoning: str = Field(description="불만과 질문을 어떻게 읽었는지 2~3문장")

    # --- 사용자가 원한 것 ---
    resolved_question: str = Field(
        description="대화 맥락을 반영해 대명사와 생략을 모두 푼, 그 자체로 이해되는 질문"
    )
    unmet_need: str = Field(
        description="사용자가 원했는데 받지 못한 것. 사용자가 요구하지 않은 항목을 덧붙이지 말 것"
    )

    # --- 불만의 성격 ---
    complaint_target: ComplaintTarget
    complaint_quote: str = Field(
        default="",
        description="후속 발화에서 그대로 따온 구절. complaint_target 을 그렇게 읽은 근거다. "
                    "특히 'none' 일 때 필수 — 그게 가장 쉬운 답이라 근거 없이 통과시키면 "
                    "애매한 턴이 전부 그리로 샌다. 원문 그대로여야 하고 지어내면 검증에서 걸린다",
    )
    question_domain: QuestionDomain

    # --- 질문 쪽 관측 ---
    question_clarity: QuestionClarity = Field(
        description="마지막 질문이 무엇을 묻는지 분명한가. 챗봇은 이전 질문들을 함께 받는다 — "
                    "지시어가 앞 질문들로 풀리면 clear (unresolved_reference · vague → U3 태그)"
    )
    question_multi_intent: bool = Field(
        description="한 질문에 서로 다른 요구가 둘 이상 섞여 있는가 (복합질문 태그 · G4)"
    )

    # --- 답변 쪽 관측 ---
    answer_refused: bool = Field(
        description="답변이 정책·권한을 이유로 거절했는가 (case28)"
    )
    answer_covers_all_intents: bool = Field(
        description="복합 질문이었다면 답변이 모든 요구를 다뤘는가. "
                    "단일 요구였으면 true (case15)"
    )
    answer_actionable: bool = Field(
        description="답변만 보고 사용자가 다음에 무엇을 할지 알 수 있는가 (case17)"
    )
    # 예전엔 not_needed · used · ignored 셋이었다. 라우팅은 ignored 만 보는데 used 와
    # not_needed 사이에서 실행마다 39% 가 흔들렸다 (Haiku 3회 실측) - 결과에 영향 없는
    # 선택지가 판정자를 흔들 뿐이라 하나로 줄였다.
    answer_ignored_history: bool = Field(
        description="이전 턴에서 명시적으로 정한 조건을 답변이 어겼는가 (case14). "
                    "부실한 답변은 해당하지 않는다"
    )
    history_quote: str = Field(
        default="",
        description="answer_ignored_history 가 true 일 때, 어긴 조건이 적힌 구절을 이전 질문들에서 "
                    "글자 그대로. 그 외에는 빈 문자열. 대조에서 걸러지면 그 주장은 무효다",
    )
    requests_unsupported_output: bool = Field(
        description="챗봇이 낼 수 없는 형태를 요구했는가 — 외부 링크, 이미지·그림 생성, "
                    "파일 첨부 등 (U1)"
    )
    answer_asked_back: bool = Field(
        default=False,
        description="답변이 질문의 뜻을 되물었는가 (U3 와 짝 — 되묻기없음 태그)"
    )

    # --- 명시적 요구 (코드 검증기에 넘길 값) ---
    requested_language: str = Field(
        description='요구한 언어의 ISO 코드(ko/en/ja/zh). 요구가 없으면 빈 문자열'
    )
    requested_length_kind: LengthRequestKind
    requested_length_value: int = Field(
        description="수치 요구의 값. 수치가 없으면 0"
    )
    requested_format: FormatRequest
    requested_quote: str = Field(
        default="",
        description="위 요구가 적힌 구절을 이전 질문들에서 글자 그대로. 요구가 없으면 빈 문자열. "
                    "후속 발화에서 처음 나온 요구는 요구가 아니다 — 대조에서 걸러진다",
    )


# ---------------------------------------------------------------------------
# v3 — 일반 LLM 이 만드는 텍스트 (범주 판정은 kev 가 한다: ragdiag/questions.py)
# ---------------------------------------------------------------------------

class ObservationText(BaseModel):
    """②b 텍스트 관측. 범주는 묻지 않는다 — 문장을 만들어야 하는 칸만."""

    reasoning: str = Field(description="불만과 질문을 어떻게 읽었는지 1~2문장")
    resolved_question: str = Field(
        description="대화 맥락을 반영해 대명사와 생략을 모두 푼, 그 자체로 이해되는 질문")
    unmet_need: str = Field(
        description="사용자가 원했는데 받지 못한 것. 사용자가 요구하지 않은 항목을 덧붙이지 말 것. "
                    "불만이 없으면 빈 문자열")
    requested_language: str = Field(
        default="", description="요구한 언어의 ISO 코드(ko/en/ja/zh). 요구가 없으면 빈 문자열")
    requested_length_value: int = Field(default=0, description="수치 길이 요구의 값. 없으면 0")
    history_quote: str = Field(
        default="",
        description="마지막 질문보다 앞의 질문들에 범위를 좁히는 조건(지역 · 기간 · 대상 · 직급 · "
                    "단위)이 적혀 있으면 그 구절을 글자 그대로. 없으면 빈 문자열")


ClaimSource = Literal["doc", "tool", "general"]


class Claim(BaseModel):
    text: str = Field(description="답변에서 글자 그대로 따온 사실 주장 한 문장")
    expected_source: ClaimSource = Field(
        description="이 주장이 어디서 왔어야 하나 — doc(업무 문서) · tool(도구 결과) · general(일반 지식)")


class Claims(BaseModel):
    """④a 주장 추출. 숫자 · 날짜 · 조건 · 절차가 들어간 문장을 주장으로 뽑는다."""

    reasoning: str = Field(description="무엇을 주장으로 봤는지 한 문장")
    claims: list[Claim] = Field(description="없으면 빈 배열")


class QuotePair(BaseModel):
    """조건부 인용 — 어긋나는 두 구절. 전달본용이고 판정을 바꾸지 않는다."""

    answer_quote: str = Field(description="답변에서 글자 그대로")
    source_quote: str = Field(description="근거(문서 · memory · 앞 답변)에서 글자 그대로")
