"""④′ 읽기 — 답변이 사람이 읽을 수 있는 글인가. 아니면 case30(생성 붕괴)으로 끝낸다.

코드 규칙(short_circuit/degenerate)은 5555… 나 !!!!… 처럼 오탐이 없는 모양만 잡는다.
토큰 잡탕, 앞은 멀쩡하고 중간부터 깨진 것, 문단이 조금씩 바뀌며 되풀이되는 것,
시스템 프롬프트가 새어 나온 것은 규칙으로 열거할 수 없다 - 예외를 쌓을수록 정상
답변(표 · 코드 · 영문)이 걸리기 시작한다. 그래서 여기서는 LLM 에 **답변만 주고**
"읽을 수 있는 글인가" 하나만 묻는다.

질문 · 불만 · 문서를 주지 않는 이유: 주면 "질문에 맞는 답인가" 를 재기 시작하고,
그러면 부실한 답변까지 붕괴로 세어 case20 · 22 가 통째로 사라진다. 유용한지는
Step 1 · 2 가 본다.

오탐 방어는 인용이다. 읽을 수 없다면 깨진 구절을 답변에서 따오게 하고 코드가 원문과
대조한다 - 못 대면 판정을 무효로 하고 아래 단계로 흘려보낸다 (⑧ 인용 대조와 같은
원리). 이 판정이 틀리면 그 턴의 진짜 원인은 아무 단계에서도 판정받지 못하므로,
확신이 없으면 legible 이라고 프롬프트에 못 박았다.

코드가 잡은 case30 은 신뢰도 high, 여기서 잡은 것은 medium 이다. 대시보드에서 색으로
갈린다.

**판정자가 그렇다고 해도 코드가 두 번 더 본다.** 인용이 코드 블록 안이면 무효(코드의 오류는
코드 검증기의 일), 인용에 붕괴의 흔적(템플릿 토큰 · 자모 조각 · 딴 문자 · 되풀이)이 없어도
무효다. 생각을 끈 약한 모델은 문장이 끊긴 답변이나 지시문이 섞인 답변도 "읽을 수 없다" 고
하는데, 그건 글이다 (docs/design/legibility_step.md 4차).
"""

import re

from ragdiag import settings
from ragdiag.results import Classification
from ragdiag.verify import verify_complaint_quote

from .._shared import call_llm, each_turn

NAME = "legibility"

_FENCE = re.compile(r"```.*?(?:```|$)", re.S)


# 인용 구절에 붕괴의 흔적이 있는가. 판정자(특히 생각을 끈 약한 모델)는 문장 중간에서 끊긴
# 답변이나 이상한 지시문이 섞인 답변도 "읽을 수 없다" 고 하는 일이 있다 - 그건 글이다.
# 붕괴라면 인용 자체에 눈에 보이는 흔적이 있어야 한다: 채팅 템플릿 토큰 · 자모만 있는 조각 ·
# 한국어 답변에 섞인 딴 문자(한자 · 가나 · 키릴) · 같은 낱말의 연달은 되풀이 · 같은 낱말이
# 한 구절에 네 번 이상 · 같은 네 낱말이 답변에 두 번 이상. 하나도 없으면 판정을 무효로 한다.
# 유출의 흔적. "Traceback" · "Error:" 는 넣지 않는다 - 오류를 설명하는 정상 답변에도 나온다.
_LEAK = re.compile(r"<\||<think|\{\{|File \"|\"error\"\s*:|<\/?(?:system|assistant|user)>")
_JAMO_RUN = re.compile(r"[ㄱ-ㅎㅏ-ㅣ]{2,}")
_FOREIGN = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\u0400-\u04ff]")
_SAME_CHAR_RUN = re.compile(r"([가-힣A-Za-zㄱ-ㅎㅏ-ㅣ])\1{3,}")   # 숫자(10000)와 구분선은 제외
_WORD = re.compile(r"[0-9A-Za-z가-힣]{2,}")


_TEMPLATE = re.compile(r"<\||<think|\{\{")        # 정상 답변에는 절대 없는 토큰


def quote_looks_broken(answer: str, quote: str) -> bool:
    if _LEAK.search(quote) or _JAMO_RUN.search(quote) or _SAME_CHAR_RUN.search(quote):
        return True
    if _TEMPLATE.search(answer):
        return True                                   # 인용이 짧아도 답변에 템플릿 토큰이 있으면 붕괴다
    foreign = len(_FOREIGN.findall(quote))
    if foreign >= 2:
        return True
    tokens = quote.split()
    if any(tokens[i] == tokens[i + 1] == tokens[i + 2] for i in range(len(tokens) - 2)):
        return True                                   # "the the the" · "을 을 을"
    pair = any(tokens[i] == tokens[i + 1] for i in range(len(tokens) - 1))
    if pair and (foreign or _JAMO_RUN.search(quote)):
        return True                                   # "附 the of of"
    words = _WORD.findall(quote)
    for i in range(max(1, len(words) - 7)):        # 여덟 낱말 창 안에서만 - 긴 글은 같은 말을 되풀이하기 마련이다
        window = words[i:i + 8]
        counts: dict = {}
        stems: dict = {}
        for w in window:
            counts[w] = counts.get(w, 0) + 1
            stems[w[:2]] = stems.get(w[:2], 0) + 1
        if any(n >= 4 for n in counts.values()) or any(n >= 4 for n in stems.values()):
            return True                               # "팀장은 팀장이 팀장에게 팀장을" · "정산되는 정산의 정산을 정산"
    body = _WORD.findall(answer)
    windows = {}
    for i in range(len(body) - 3):
        key = tuple(body[i:i + 4])
        windows[key] = windows.get(key, 0) + 1
    return any(n >= 2 for n in windows.values())      # 문단이 조금씩 바뀌며 되풀이


def inside_code_block(answer: str, quote: str) -> bool:
    """인용이 코드 블록 안에 있는가. 코드는 문법이 틀리거나 도중에 끝나도 붕괴가 아니다 -
    그건 python_syntax · sql_shape 가 본다. 판정자가 열린 괄호나 GROUP BY 로 끝난 SQL 을
    붕괴로 읽는 일이 있어(messy code02 · 읽기 골든셋 ok48) 코드로 막는다."""
    needle = re.sub(r"\s+", "", quote)
    if not needle:
        return False
    return any(needle in re.sub(r"\s+", "", m.group(0)) for m in _FENCE.finditer(answer))


def process_data(ctx) -> tuple[list, list]:
    if not settings.LEGIBILITY:
        return [], []

    def judge(turn):
        answer = turn.case.llm_ans_on_last_q
        if not answer.strip():
            return                                   # 빈 답변은 읽기의 문제가 아니다
        check = call_llm(turn, ctx.judge.check_legibility(turn.case))
        turn.legibility = check
        if check.legible:
            return
        # 답변 안의 구절인지 대조한다. 짧은 발화용 규칙이지만 여기서도 맞는 기준이다 -
        # 답변 전체를 따왔으면 받고, 조각이면 4자 이상이어야 하고, 말을 바꾸면 안 받는다.
        turn.legibility_quote = verify_complaint_quote(check.quote, answer)
        if (not turn.legibility_quote.verified or inside_code_block(answer, check.quote)
                or not quote_looks_broken(answer, check.quote)):
            return                               # 무효 - 결과 파일의 legibility 에 남는다
        turn.classification = Classification(
            primary_case="case30",
            confidence="medium",                     # 코드가 잡은 것(high)과 갈라 둔다
            reason=f"읽을 수 없는 답변 — {check.reasoning}",
            secondary_cases=[],
            notes=["LLM 이 답변만 보고 판정했다. 관측·충족도·근거 활용은 돌지 않았다.",
                   "모델이 답을 만들다 무너졌다. 검색·생성 품질이 아니라 모델·서빙 쪽 문제다."])

    each_turn(ctx, NAME, judge, parallel=True)
    return [], []
