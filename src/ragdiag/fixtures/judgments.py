# -*- coding: utf-8 -*-
"""Step 2·3 골든셋 — 충족도 판정과 근거 활용.

지금까지 직접 채점한 것은 Step 1(관측)뿐이었다. 충족도와 근거 활용은 회귀셋 23건으로
**간접 확인**만 됐다. 층이 다른 검증은 서로를 대체하지 못한다 — 실제로 관측 골든셋이
98%일 때 회귀셋은 15/23 이었고, 반대로 회귀셋이 통과해도 판정 자체의 정확도는 모른다.

충족도(Step 2)에서 재는 것:
  verdict          sufficient / partial / insufficient
  cited_chunks     어느 청크에서 인용을 뽑았는가 (근거를 제대로 짚었는지)
  citation_holds   그 인용이 원문 대조를 통과하는가 (지어내지 않았는지)

근거 활용(Step 3)에서 재는 것:
  used / ignored / contradicted

Step 2 는 챗봇 답변을 보지 않고, Step 3 은 히스토리를 보지 않는다. 실제 파이프라인과
같은 입력만 준다 — 여기서 더 주면 측정이 실전보다 후해진다.
"""

RULES = [
    "국내 출장 식비는 1일 3만원을 상한으로 한다.",
    "국내 출장 숙박비는 1박 8만원을 상한으로 한다.",
    "출장비는 출장 종료 후 5영업일 이내에 정산한다.",
]
LEAVE = [
    "연차유급휴가 신청은 사전에 그룹웨어를 통해 제출한다.",
    "연차 사용 시 팀장의 승인을 받아야 한다.",
    "연차는 반차 단위로도 사용할 수 있다.",
]

# ---------------------------------------------------------------------------
# Step 2 — 충족도 판정
# ---------------------------------------------------------------------------

SUFFICIENCY = [
    dict(
        id="suf01", note="답이 청크에 명확히 있음",
        question="국내 출장 식비의 1일 상한 금액은 얼마인가?",
        unmet_need="국내 출장 식비의 1일 상한 금액",
        chunks=RULES,
        expect_verdict="sufficient", expect_cited={0},
    ),
    dict(
        id="suf02", note="near-miss — 주제는 같고 물어본 것은 없음",
        question="해외 출장 미주 지역의 1일 숙박비 상한은 얼마인가?",
        unmet_need="미주 지역 1일 숙박비 상한 금액",
        chunks=["해외 출장비 정산은 출장 종료 후 5영업일 이내에 제출한다.",
                "숙박비는 실비 정산을 원칙으로 한다.",
                "출장 신청은 출발 7일 전까지 팀장 승인을 받는다."],
        expect_verdict="insufficient",
    ),
    dict(
        id="suf03", note="요구 둘 중 하나만 있음",
        question="국내 출장 식비와 교통비 상한이 각각 얼마인가?",
        unmet_need="국내 출장 식비 상한과 교통비 상한",
        chunks=RULES,
        expect_verdict="partial", expect_cited={0},
    ),
    dict(
        id="suf04", note="distractor — 그럴듯한 인접 문서",
        question="중국 출장 시 비자 수수료를 회사가 지원하는가?",
        unmet_need="비자 수수료의 회사 지원 여부",
        chunks=["해외 출장 시 항공료와 숙박비는 회사가 부담한다.",
                "여권 발급 비용은 개인 부담을 원칙으로 한다.",
                "출장 중 현지 교통비는 실비 정산 대상이다."],
        expect_verdict="insufficient",
    ),
    dict(
        id="suf05", note="leakage probe — 상식으로 아는 답, 문서엔 없음",
        question="근속 1년 미만 근로자에게도 연차가 발생하는가? 사규 근거는?",
        unmet_need="1년 미만 근속자의 연차 발생 요건에 대한 업무 규정",
        chunks=LEAVE,
        expect_verdict="insufficient",
    ),
    dict(
        id="suf06", note="leakage probe — 부가세율",
        question="우리 회사 세금계산서 발행 시 적용 세율은?",
        unmet_need="업무 문서 기준의 적용 세율",
        chunks=["세금계산서는 거래일이 속하는 달의 다음 달 10일까지 발행한다.",
                "세금계산서 발행은 재무팀 승인 후 진행한다."],
        expect_verdict="insufficient",
    ),
    dict(
        id="suf07", note="관련 서술은 있으나 구체성이 못 미침",
        question="미사용 연차를 이월할 수 있는 예외 조건은?",
        unmet_need="연차 이월이 가능한 구체적 예외 조건",
        chunks=["미사용 연차는 발생일로부터 1년이 경과하면 소멸함을 원칙으로 한다.",
                "다만 회사의 귀책사유로 사용하지 못한 경우 예외를 둘 수 있다."],
        # "회사의 귀책사유" 를 구체적 예외 조건 하나로 읽으면 sufficient 도 변호 가능하다
        # (Haiku 3회 중 1회). 어느 쪽이든 case20 이 아니냐만 갈리므로 둘 다 받는다.
        expect_verdict="partial", accept={"partial", "sufficient"}, expect_cited={1},
    ),
    dict(
        id="suf08", note="검색 결과가 아예 없음",
        question="실행 환경 헬스장 이용 시간은?",
        unmet_need="실행 환경 헬스장 운영 시간",
        chunks=[],
        expect_verdict="insufficient",
    ),
    dict(
        id="suf09", note="여러 청크에 나뉘어 있지만 온전히 있음",
        question="국내 출장 식비와 숙박비 상한이 각각 얼마인가?",
        unmet_need="국내 출장 식비 상한과 숙박비 상한",
        chunks=RULES,
        expect_verdict="sufficient", expect_cited={0, 1},
    ),
    dict(
        id="suf10", note="숫자가 비슷한 다른 항목이 있어 혼동하기 쉬움",
        question="국내 출장 교통비 상한은 얼마인가?",
        unmet_need="국내 출장 교통비의 상한 금액",
        chunks=RULES,     # 식비 3만 · 숙박비 8만은 있지만 교통비는 없다
        expect_verdict="insufficient",
    ),
]

# ---------------------------------------------------------------------------
# 실제 문서 모양의 케이스 (suf11~)
#
# 위 10건은 청크가 전부 한 문장 27자라 실제 로그와 거리가 멀다. 아래는 공개 법령 원문
# (public_docs.DOCS · 조 단위 200~1800자 · 항/호/표 포함)과, 형식 위험을 넣기 위해 만든
# 가상 청크(PSEUDO)로 채운다. 어느 쪽인지 source 에 적는다.
#
# 필드
#   category   무엇을 재는 케이스인가 (아래 표)
#   accept     기대 verdict 를 넓힌 집합. 정답이 애매한 케이스에만 두고 이유를 주석으로
#   inflated   unmet_need 가 질문보다 넓다(Step 1 부풀림을 흉내). 질문 기준 정답을 expect 에 둔다
#
#   clear       답이 청크에 온전히 있음 · 위치와 형식을 흩음
#   partial     요구 여러 부분 중 일부만 있음
#   nearmiss    주제는 같고 물어본 항목은 없음 (인접 항목 · 상위 규정 참조만 있음)
#   leakage     공개 지식으로 아는 답인데 청크엔 없음
#   inflated    unmet_need 부풀림 — 질문만 보면 sufficient
#   format      표 · 따옴표 · 백슬래시 · 하드랩 · 중복 청크
#   conflict    신구 규정이 같이 검색됨
#   position    청크 6개 중 뒤쪽에 답
# ---------------------------------------------------------------------------

from ragdiag.fixtures.public_docs import DOCS as D  # noqa: E402

_PDF_WRAP = (
    # PDF 텍스트 추출처럼 40자 안팎에서 줄이 끊기고 항 사이 빈 줄이 없는 형태 (여비16 원문)
    "제16조(일비·숙박비·식비의 지급) ① 국내 여행자의 일비(日費)·숙박비 및\n"
    "식비는 별표 2에 따라 지급하고, 국외 여행자의 경우는 별표 4에 따라\n"
    "지급한다. 다만, 공무의 형편이나 그 밖의 부득이한 사유로 숙박비의 상한액\n"
    "및 지급받은 식비(국내 여행의 경우 식비는 제외한다)를 초과하여 여비를\n"
    "지출하였을 때에는 국내 여행의 경우에는 숙박비 상한액의 10분의 3을, 국외\n"
    "여행의 경우에는 숙박비 및 식비의 2분의 1을 넘지 아니하는 범위에서 여비를\n"
    "추가로 지급할 수 있다.  <개정 2011.2.9.> ② 제1항 단서에 따라\n"
    "여비를 추가로 지급받으려는 공무원은 여행을 마친 날의 다음 날부터 기산하여\n"
    "1주일 이내(국외 여행의 경우에는 2주일 이내를 말한다)에 정부구매카드 또는\n"
    "신용카드를 사용하고 받은 매출전표에 세부 사용내용이 명시된 증거자료를\n"
    "갖추어 회계 관계 공무원에게 정산을 신청하여야 한다.  <개정 2011.2.9.> ③\n"
    "일비는 여행일수에 따라 지급하되, 공용차량을 이용하는 경우 등 인사혁신처장이\n"
    "정하는 바에 따라 여행을 하는 경우에는 일비의 2분의 1을 지급한다.  <개정\n"
    "2013.3.23., 2014.11.19.> ④ 숙박비는 숙박하는 밤의 수에 따라 지급한다.\n"
    "다만, 수로여행과 항공여행에는 숙박비를 지급하지 아니하되, 천재지변이나 그\n"
    "밖의 부득이한 사유로 육지에서 숙박할 필요가 있는 경우에는 숙박비를\n"
    "지급한다. ⑤ 식비는 여행일수에 따라 지급한다. 다만, 수로여행과 항공여행에는\n"
    "따로 식비가 필요한 경우에만 식비를 지급한다. ⑥ 삭제  <2012.1.6.>\n"
    "[전문개정 2010.11.10.]"
)

PSEUDO = {
    # 별표 2 국내 여비 지급표를 흉내 낸 마크다운 표. 숫자가 "100,000원" 꼴이다.
    "별표2": (
        "[별표 2] 국내 여비 지급표 (제10조부터 제13조까지 및 제16조제1항 관련)\n\n"
        "| 구분 | 철도운임 | 선박운임 | 항공운임 | 자동차운임 | 일비(1일당) | 숙박비(1야당) | 식비(1일당) |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| 제1호 해당자 | 실비(특실) | 실비(1등급) | 실비 | 실비 | 25,000원 | 실비 | 25,000원 |\n"
        "| 제2호 해당자 | 실비(일반실) | 실비(2등급) | 실비 | 실비 | 25,000원 | 실비(상한액: 서울특별시 100,000원, 광역시 80,000원, 그 밖의 지역 70,000원) | 25,000원 |\n\n"
        "비고\n"
        "1. 숙박비 상한액은 1야(夜)당 금액이며, 상한액을 초과하여 지출한 경우 제16조제1항 단서에 따른다.\n"
        "2. 일비는 출장일수에 따라 지급하되, 공용차량 이용 시 2분의 1을 지급한다."
    ),
    # 사내 시스템 안내문 — 큰따옴표 · 백슬래시 경로 · 꺾쇠가 섞여 JSON 인용을 깨기 쉽다
    "정산시스템": (
        "## 출장비 정산 신청 방법 (e-여비 시스템)\n\n"
        "1. e-여비 > \"출장관리\" > \"정산신청\" 메뉴로 들어간다.\n"
        "2. 출장번호를 선택하고 \"증빙 첨부\" 버튼으로 매출전표 스캔본(PDF, 10MB 이하)을 올린다.\n"
        "3. 숙박비 증빙 양식은 공유폴더 \\\\fs01\\총무\\여비\\숙박비_증빙양식_v3.xlsx 를 쓴다. 구버전(v2)은 반려된다.\n"
        "4. 정산 신청 기한은 귀임일 다음 날부터 7일(국외 14일)이며, 기한이 지나면 <기한경과> 상태로 잠긴다.\n"
        "5. 잠긴 건은 부서장 승인 후 회계팀(내선 2210)에 해제를 요청한다."
    ),
    # 헤더 + 불릿 FAQ
    "FAQ": (
        "# 휴가 FAQ\n\n"
        "- **Q. 반차는 어떻게 계산하나요?**\n"
        "  - A. 반일 연가 2회를 연가 1일로 계산합니다. 오전 반차는 09:00~13:00, 오후 반차는 13:00~18:00 입니다.\n"
        "- **Q. 연가를 미리 당겨 쓸 수 있나요?**\n"
        "  - A. 재직기간별 한도 안에서 다음 재직기간의 연가를 미리 사용할 수 있습니다. 4년 이상 재직자는 최대 10일입니다.\n"
        "- **Q. 병가 진단서는 언제 내야 하나요?**\n"
        "  - A. 병가 일수가 7일 이상이면 의사의 진단서를 첨부해야 합니다.\n"
        "- **Q. 지각·조퇴·외출은 연가에서 빠지나요?**\n"
        "  - A. 질병·부상 외의 사유로 인한 지각·조퇴·외출은 누계 8시간을 연가 1일로 계산합니다."
    ),
    "식비_구버전": (
        "출장비 지급 기준 (2022.1.1. 시행, 폐지)\n"
        "제5조(식비) 국내 출장 식비는 1일 20,000원을 정액으로 지급한다.\n"
        "제6조(일비) 국내 출장 일비는 1일 20,000원으로 한다."
    ),
    "식비_신버전": (
        "출장비 지급 기준 (2024.3.1. 개정 시행)\n"
        "제5조(식비) 국내 출장 식비는 1일 25,000원을 정액으로 지급한다. <개정 2024.2.15.>\n"
        "제6조(일비) 국내 출장 일비는 1일 25,000원으로 한다. <개정 2024.2.15.>\n"
        "부칙 이 기준은 2024년 3월 1일부터 시행하며, 종전 기준(2022.1.1. 시행)은 폐지한다."
    ),
    "PDF랩": _PDF_WRAP,
}

SUFFICIENCY += [
    # ---- clear -----------------------------------------------------------
    dict(
        id="suf11", category="clear", source="public",
        note="답이 세 번째 청크 한 문장에 명확히 있음 (근무지 내 출장 4시간 이상 2만원)",
        question="근무지 내 국내 출장에서 출장 여행시간이 4시간 이상이면 여비를 얼마 받는가?",
        unmet_need="근무지 내 국내 출장 시 여행시간 4시간 이상인 경우의 여비 금액",
        chunks=[D["여비16"], D["여비17"], D["여비18"], D["여비10"]],
        expect_verdict="sufficient", expect_cited={2},
    ),
    dict(
        id="suf12", category="clear", source="public",
        note="답이 마크다운 표 안에 있음 (재직 3년 이상 4년 미만 → 연가 14일)",
        question="재직기간이 3년 이상 4년 미만인 공무원의 연가 일수는 며칠인가?",
        unmet_need="재직기간 3년 이상 4년 미만 공무원의 연간 연가 일수",
        chunks=[D["복무14"], D["복무16"], D["복무17"], D["복무15"], D["복무18"]],
        expect_verdict="sufficient", expect_cited={3},
    ),
    dict(
        id="suf13", category="clear", source="public",
        note="1800자 청크의 ②항에 답 (쌍둥이 출산휴가 120일)",
        question="쌍둥이를 임신한 공무원의 출산휴가는 며칠인가?",
        unmet_need="한 번에 둘 이상의 자녀를 임신한 경우 출산휴가 일수",
        chunks=[D["복무19"], D["복무20"], D["복무18"]],
        expect_verdict="sufficient", expect_cited={1},
    ),
    dict(
        id="suf14", category="clear", source="public",
        note="비슷한 제목의 조가 넷 (연가계획 · 연가 사용의 권장 · 연가의 저축 · 10일 연속) — 저축 3년",
        question="남은 연가를 저축해서 이월할 수 있는 최대 기간은 몇 년인가?",
        unmet_need="미사용 연가의 이월·저축 가능 최대 기간",
        chunks=[D["복무16"], D["복무17"], D["복무16의3"], D["복무15"]],
        expect_verdict="sufficient", expect_cited={2},
    ),
    dict(
        id="suf15", category="clear", source="public",
        note="답이 800자 청크의 ②항 괄호 안에 있음 (국외 여행 추가 여비 정산 2주일 이내)",
        question="국외 출장 후 숙박비 초과분을 추가로 받으려면 정산 신청을 언제까지 해야 하는가?",
        unmet_need="국외 여행 시 추가 여비 정산 신청 기한",
        chunks=[D["여비8의2"], D["여비16"], D["여비12"]],
        # 여비8의2 ② 에도 "국외 여행자는 2주일 이내" 정산 조항이 있다. 어느 쪽을 인용해도 답이다.
        expect_verdict="sufficient", expect_cited={0, 1},
    ),
    dict(
        id="suf16", category="clear", source="public",
        note="답(일비 2분의 1)이 있는데 옆 청크에 '공용차량 이용 시 1만원 감액'이라는 비슷한 문장이 있음",
        question="공용차량을 이용해 출장 가면 일비는 어떻게 되는가?",
        unmet_need="공용차량 이용 출장 시 일비 지급 기준",
        chunks=[D["여비17"], D["여비18"], D["여비16"]],
        # 여비18 ① 도 "공용차량을 이용하는 경우 … 1만원을 감액" 이라 근무지 내 출장에 한해 답이 된다.
        # 질문이 근무지 내 · 외를 가르지 않아 "어느 규정이 적용되는지 알 수 없다" 는 partial 도
        # 변호 가능하다 (Haiku 가 그렇게 추론했다). 둘 다 받는다.
        expect_verdict="sufficient", accept={"sufficient", "partial"}, expect_cited={1, 2},
    ),
    dict(
        id="suf17", category="clear", source="public",
        note="요구 두 부분이 같은 청크 ①·② 항에 나뉘어 있음 (근무지 내 출장 금액 + 거리 기준 12km)",
        question="근무지 내 출장은 어디까지를 말하고, 여비는 얼마인가?",
        unmet_need="근무지 내 국내 출장의 범위(거리 기준)와 지급 여비 금액",
        chunks=[D["여비10"], D["여비18"], D["여비17"]],
        expect_verdict="sufficient", expect_cited={1},
    ),
    dict(
        id="suf18", category="clear", source="public",
        note="연차 촉진 통보 시기 — 호(1. 2.) 안에 답",
        question="회사가 연차 사용 촉진을 하려면 미사용 휴가 일수를 언제까지 알려줘야 하는가?",
        unmet_need="연차 사용 촉진 시 미사용 휴가 일수 통지 시기",
        chunks=[D["근기60"], D["근기62"], D["근기61"]],
        expect_verdict="sufficient", expect_cited={2},
    ),
    dict(
        id="suf19", category="clear", source="public",
        note="content_wrong 형 요구 — 사용자가 60일이라 믿는데 문서엔 90일",
        question="출산휴가는 60일이 맞는가?",
        unmet_need="출산휴가의 정확한 일수 (60일이 맞는지 정정)",
        chunks=[D["복무18"], D["복무20"], D["복무19"]],
        expect_verdict="sufficient", expect_cited={1},
    ),
    # ---- partial ---------------------------------------------------------
    dict(
        id="suf20", category="partial", source="public",
        note="출산휴가 일수는 있고 경조사휴가(배우자 출산) 일수는 별표 2로 넘겨져 없음",
        question="본인 출산휴가와 배우자 출산휴가는 각각 며칠인가?",
        unmet_need="본인 출산휴가 일수와 배우자 출산 시 경조사휴가 일수",
        chunks=[D["복무20"], D["복무19"], D["복무14"]],
        expect_verdict="partial", expect_cited={0},
    ),
    dict(
        id="suf21", category="partial", source="public",
        note="병가 한도(연 60일)와 진단서 기준(7일 이상)은 있고 병가 중 급여 지급률은 없음",
        question="병가는 1년에 며칠까지 가능하고, 진단서는 언제부터 필요하며, 병가 기간 급여는 얼마나 나오는가?",
        unmet_need="연간 병가 한도, 진단서 첨부 기준, 병가 기간 중 급여 지급률",
        chunks=[D["복무17"], D["복무18"], D["복무19"]],
        expect_verdict="partial", expect_cited={1},
    ),
    dict(
        id="suf22", category="partial", source="public",
        note="사망 시 유족 여비의 종류는 있고 금액은 별표 · 다른 조 참조로만 있음",
        question="공무원이 국외 출장 중 사망하면 유족에게 어떤 여비가 얼마나 지급되는가?",
        unmet_need="국외 출장 중 사망 시 유족에게 지급되는 여비의 종류와 금액",
        chunks=[D["여비26"], D["여비12"], D["여비8의2"]],
        # 종류(여비 · 시신 운구비 · 2명 이내 · 7일 범위)는 있고 금액은 별표 1 참조뿐이라 partial 이 정답.
        # 다만 "7일 범위에서 제2호가목 해당자의 여비" 를 금액 기준으로 읽으면 sufficient 도 가능하다.
        expect_verdict="partial", accept={"partial", "sufficient"}, expect_cited={0},
    ),
    # ---- nearmiss --------------------------------------------------------
    dict(
        id="suf23", category="nearmiss", source="public",
        note="숙박비 조항은 길게 있지만 국외 숙박비 상한 금액은 '별표 4에 따라' 뿐",
        question="미주 지역 출장 시 1일 숙박비 상한은 얼마인가?",
        unmet_need="국외(미주) 출장 시 1일 숙박비 상한 금액",
        chunks=[D["여비16"], D["여비12"], D["여비17"]],
        expect_verdict="insufficient",
    ),
    dict(
        id="suf24", category="nearmiss", source="public",
        note="근무지 '내' 출장 금액(2만원/1만원)이 있어 근무지 '외' 일비로 착각하기 쉬움",
        question="근무지 밖으로 나가는 국내 출장의 일비는 하루 얼마인가?",
        unmet_need="근무지 외 국내 출장의 1일 일비 금액",
        chunks=[D["여비18"], D["여비17"], D["여비10"]],
        expect_verdict="insufficient",
    ),
    dict(
        id="suf25", category="nearmiss", source="public",
        note="경조사휴가는 '별표 2의 기준에 따른다'는 문장만 있고 일수는 없음",
        question="본인 결혼 시 경조사휴가는 며칠인가?",
        unmet_need="본인 결혼 경조사휴가 일수",
        chunks=[D["복무20"], D["복무14"], D["복무16"]],
        expect_verdict="insufficient",
    ),
    dict(
        id="suf26", category="nearmiss", source="public",
        note="'육아시간 1일 1시간'이 있어 육아휴직 기간으로 새기 쉬움",
        question="육아휴직은 최대 몇 년까지 쓸 수 있는가?",
        unmet_need="육아휴직 최대 사용 기간",
        chunks=[D["복무20"], D["근기74"], D["복무15"]],
        expect_verdict="insufficient",
    ),
    dict(
        id="suf27", category="nearmiss", source="public",
        note="해고 관련 조가 여섯이지만 해고예고수당의 통상임금 '산정 방법'은 없음",
        question="해고예고수당을 계산할 때 통상임금은 어떻게 산정하는가?",
        unmet_need="해고예고수당 산정 시 통상임금 계산 방법",
        chunks=[D["근기23"], D["근기24"], D["근기25"], D["근기26"], D["근기27"], D["근기28"]],
        # 근기26 에 "30일분 이상의 통상임금" 이 있어 이를 '기준'으로 읽으면 partial 도 변호 가능하다.
        expect_verdict="insufficient", accept={"insufficient", "partial"},
    ),
    # ---- leakage ---------------------------------------------------------
    dict(
        id="suf28", category="leakage", source="public",
        note="주 40시간은 누구나 아는 답 — 제50조는 빼고 휴게 · 휴일 · 가산수당만 줌",
        question="법정 근로시간은 주 몇 시간인가?",
        unmet_need="1주 법정 근로시간 상한",
        chunks=[D["근기54"], D["근기55"], D["근기56"]],
        expect_verdict="insufficient",
    ),
    dict(
        id="suf29", category="leakage", source="public",
        note="연장근로 가산 50%는 상식 — 제56조는 빼고 근로시간 · 연장 한도 · 휴게만 줌",
        question="연장근로 수당은 통상임금의 몇 퍼센트를 가산하는가?",
        unmet_need="연장근로 가산수당 비율",
        chunks=[D["근기50"], D["근기53"], D["근기54"]],
        expect_verdict="insufficient",
    ),
    dict(
        id="suf30", category="leakage", source="public",
        note="점심시간 12~13시는 상식 — 제9조는 빼고 근무시간 변경 · 시간외 · 현업만 줌",
        question="공무원 점심시간은 몇 시부터 몇 시까지인가?",
        unmet_need="공무원 점심시간의 시작과 끝 시각",
        chunks=[D["복무11"], D["복무14"], D["복무19"]],
        expect_verdict="insufficient",
    ),
    dict(
        id="suf31", category="leakage", source="public",
        note="연차 15일은 상식 — 근로기준법 제60조는 빼고 공무원 복무규정 연가표만 줌 (다른 제도)",
        question="1년간 80% 이상 출근한 근로자의 연차 유급휴가는 며칠인가?",
        unmet_need="근로기준법상 1년 80% 이상 출근 근로자의 연차 일수",
        chunks=[D["복무15"], D["복무16"], D["근기61"]],
        # 복무15 의 표는 공무원 재직기간별 연가라 근로기준법 연차와 다르다. 표의 숫자를 답으로 끌어오면 오답.
        expect_verdict="insufficient",
    ),
    # ---- inflated --------------------------------------------------------
    dict(
        id="suf32", category="inflated", source="public", inflated=True,
        note="질문은 금액 하나인데 unmet_need 에 절차 · 서류 · 기한이 덧붙음",
        question="근무지 내 출장인데 4시간 안 걸리면 얼마 받아요?",
        unmet_need="근무지 내 국내 출장 4시간 미만 시 여비 금액과 그 지급 절차, 신청 서류, 정산 기한",
        chunks=[D["여비18"], D["여비16"]],
        expect_verdict="sufficient", expect_cited={0},
    ),
    dict(
        id="suf33", category="inflated", source="public", inflated=True,
        note="질문은 연가 일수 하나인데 unmet_need 에 신청 방법 · 반차 가능 여부가 덧붙음",
        question="3년차면 연가 며칠이에요?",
        unmet_need="재직 3년차 공무원의 연가 일수, 연가 신청 방법, 반차 사용 가능 여부",
        chunks=[D["복무15"], D["복무17"]],
        expect_verdict="sufficient", expect_cited={0},
    ),
    dict(
        id="suf34", category="inflated", source="public", inflated=True,
        note="질문은 저축 기간인데 unmet_need 에 신청 서식이 덧붙음 (서식은 문서에 없음)",
        question="저축연가는 몇 년까지 이월돼요?",
        unmet_need="저축연가 이월 한도 기간, 소멸 시 보상비 처리, 저축 신청 서식",
        chunks=[D["복무16의3"], D["복무16"]],
        expect_verdict="sufficient", expect_cited={0},
    ),
    # ---- format ----------------------------------------------------------
    dict(
        id="suf35", category="format", source="pseudo",
        note="마크다운 표 셀 안에 '100,000원' 꼴 숫자 — 사용자는 '십만원'이라 물음",
        question="국내 출장 시 서울 숙박비 상한이 십만원인가?",
        unmet_need="국내 출장 서울특별시 지역 1박 숙박비 상한 금액",
        chunks=[D["여비16"], PSEUDO["별표2"], D["여비10"]],
        expect_verdict="sufficient", expect_cited={1},
    ),
    dict(
        id="suf36", category="format", source="pseudo",
        note="청크에 큰따옴표 · 백슬래시 경로 · 꺾쇠 — 인용을 JSON 에 담다 깨지기 쉬움",
        question="숙박비 증빙 양식 파일은 어디에 있는가?",
        unmet_need="숙박비 증빙 양식 파일의 위치(경로)",
        chunks=[D["여비8의2"], PSEUDO["정산시스템"]],
        expect_verdict="sufficient", expect_cited={1},
    ),
    dict(
        id="suf37", category="format", source="pseudo",
        note="헤더 + 중첩 불릿 FAQ — 굵은 글씨 · 들여쓰기가 인용에 섞이기 쉬움",
        question="오후 반차는 몇 시부터인가?",
        unmet_need="오후 반차의 시작 시각",
        chunks=[D["복무16"], PSEUDO["FAQ"], D["복무17"]],
        expect_verdict="sufficient", expect_cited={1},
    ),
    dict(
        id="suf38", category="format", source="public",
        note="PDF 추출처럼 40자마다 줄이 끊긴 청크 — 인용이 줄바꿈을 건너야 함 (수로여행 숙박비)",
        question="배로 이동하는 출장에서도 숙박비가 나오는가?",
        unmet_need="수로여행 시 숙박비 지급 여부",
        chunks=[D["여비17"], PSEUDO["PDF랩"], D["여비10"]],
        expect_verdict="sufficient", expect_cited={1},
    ),
    dict(
        id="suf39", category="format", source="public",
        note="같은 조가 두 번 검색됨(하나는 앞부분만) — 어느 쪽을 인용해도 됨",
        question="병가가 7일 이상이면 무엇을 내야 하는가?",
        unmet_need="병가 7일 이상 시 제출 서류",
        chunks=[D["복무18"], D["복무19"], D["복무18"][:260]],
        expect_verdict="sufficient", expect_cited={0, 2},
    ),
    # ---- conflict --------------------------------------------------------
    dict(
        id="suf40", category="conflict", source="pseudo",
        note="구버전(2만원, 폐지)과 신버전(2만5천원)이 같이 검색됨",
        question="지금 국내 출장 식비는 하루 얼마인가?",
        unmet_need="현행 국내 출장 1일 식비 금액",
        chunks=[PSEUDO["식비_구버전"], D["여비16"], PSEUDO["식비_신버전"]],
        # 답은 문서에 있다(신버전 25,000원). 두 값이 충돌한다는 이유로 partial 을 내는 것도 변호 가능하다.
        expect_verdict="sufficient", accept={"sufficient", "partial"}, expect_cited={2},
    ),
    # ---- position --------------------------------------------------------
    dict(
        id="suf41", category="position", source="public",
        note="청크 6개 중 마지막에 답 (해고 예고 30일 전)",
        question="근로자를 해고하려면 며칠 전에 예고해야 하는가?",
        unmet_need="해고 예고 기간",
        chunks=[D["근기23"], D["근기24"], D["근기25"], D["근기27"], D["근기28"], D["근기26"]],
        expect_verdict="sufficient", expect_cited={5},
    ),
    dict(
        id="suf42", category="position", source="public",
        note="청크 6개 중 다섯 번째, 긴 조(1400자)의 ⑦항에 답 (임신 12주 이내 근로시간 단축 2시간)",
        question="임신 초기에 근로시간을 줄여 달라고 할 수 있는가? 하루 몇 시간?",
        unmet_need="임신 12주 이내 근로자의 근로시간 단축 가능 여부와 단축 시간",
        chunks=[D["근기50"], D["근기53"], D["근기54"], D["근기60"], D["근기74"], D["근기56"]],
        expect_verdict="sufficient", expect_cited={4},
    ),
]

# ---------------------------------------------------------------------------
# 검색 결과 모양의 케이스 (w11~) — 문서 10~15개 × 약 500자
#
# 실제 retrieved_data 는 "문서 10개 이상 × 문서당 약 500자" 다. 위 케이스는 청크 3~6개라 답이
# 든 문서 하나에 같은 주제의 유사 문서 10개가 붙는 상황(놓침 · 엉뚱한 근거)을 재지 못했다.
# 같은 질문 · 정답을 유지하고 청크만 public_docs.CHUNKS 에서 검색 결과처럼 고른다:
#   답이 든 청크(anchor 로 찾음) + 같은 장의 청크 + 같은 법령의 다른 장 + 다른 법령, 합계 n 개.
#   exclude 에 걸리는 청크는 뺀다(leakage 케이스에서 답이 든 조를 빼는 용도).
#   답 위치(position)는 앞 · 중간 · 뒤로 돌아가며 둔다 - 위치별 정확도를 채점한다.
# ---------------------------------------------------------------------------

from ragdiag.fixtures.public_docs import CHUNKS as _CHUNKS  # noqa: E402

_N_CYCLE = (12, 10, 15, 13, 11, 14)
_POS_CYCLE = ("front", "mid", "back")


def _retrieve(anchors, law, chapter, n, position, seed, exclude=(), extra=()):
    """검색 결과 흉내. (chunks, cited) - cited 는 anchor 가 든 청크의 인덱스 집합."""
    import random as _random

    rng = _random.Random(seed)
    hit = [c for c in _CHUNKS if any(a in c["text"] for a in anchors)]
    targets = [c["text"] for c in hit] + list(extra)
    assert targets, f"anchor 를 찾지 못함: {anchors}"

    def ok(c):
        return c["text"] not in targets and not any(x in c["text"] for x in exclude)

    same = [c for c in _CHUNKS if ok(c) and c["law"] == law and c["chapter"] == chapter]
    same_law = [c for c in _CHUNKS if ok(c) and c["law"] == law and c["chapter"] != chapter]
    other = [c for c in _CHUNKS if ok(c) and c["law"] != law]
    for pool in (same, same_law, other):
        rng.shuffle(pool)
    fill = (same + same_law[: max(2, n // 4)] + other)[: max(0, n - len(targets))]
    fill = [c["text"] for c in fill]
    rng.shuffle(fill)
    if position == "front":
        at = 0
    elif position == "back":
        at = len(fill)
    else:
        at = len(fill) // 2
    chunks = fill[:at] + targets + fill[at:]
    cited = {i for i, c in enumerate(chunks) if c in targets}
    return chunks, cited


_WIDE_SPECS = [
    # (id, category, note, question, unmet_need, anchors, (law, chapter), expect, extra)
    dict(id="w11", category="clear", base="suf11", anchors=["근무지 내 국내 출장의 경우에는"],
         law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비")),
    dict(id="w12", category="clear", base="suf12", anchors=["| 3년 이상 4년 미만 | 14 |"],
         law=("국가공무원 복무규정", "제3장 휴가")),
    dict(id="w13", category="clear", base="suf13", anchors=["120일)의 출산휴가"],
         law=("국가공무원 복무규정", "제3장 휴가")),
    dict(id="w14", category="clear", base="suf14", anchors=["최대 3년까지 이월"],
         law=("국가공무원 복무규정", "제3장 휴가")),
    dict(id="w15", category="clear", base="suf15", anchors=["2주일 이내를 말한다", "국외 여행자는 2주일 이내에"],
         law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비")),
    dict(id="w16", category="clear", base="suf16", anchors=["일비의 2분의 1을 지급", "1만원을 감액하여 지급"],
         law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비")),
    dict(id="w17", category="clear", base="suf17", anchors=["근무지 내 국내 출장의 경우에는"],
         law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비")),
    dict(id="w18", category="clear", base="suf18", anchors=["6개월 전을 기준으로 10일 이내"],
         law=("근로기준법", "제4장 근로시간과 휴식")),
    dict(id="w19", category="clear", base="suf19", anchors=["120일)의 출산휴가"],
         law=("국가공무원 복무규정", "제3장 휴가")),
    dict(id="w20", category="partial", base="suf20", anchors=["120일)의 출산휴가"],
         law=("국가공무원 복무규정", "제3장 휴가")),
    dict(id="w21", category="partial", base="suf21", anchors=["연 60일의 범위"],
         law=("국가공무원 복무규정", "제3장 휴가")),
    dict(id="w22", category="partial", base="suf22", anchors=["시신 운구비"],
         law=("공무원 여비 규정", "제5장 퇴직자·사망자 등의 여비")),
    dict(id="w23", category="nearmiss", base="suf23", anchors=["숙박비는 숙박하는 밤의 수에 따라"],
         law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비"), no_cite=True),
    dict(id="w24", category="nearmiss", base="suf24", anchors=["근무지 내 국내 출장의 경우에는"],
         law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비"), no_cite=True),
    dict(id="w25", category="nearmiss", base="suf25", anchors=["별표 2의 기준에 따른 경조사휴가"],
         law=("국가공무원 복무규정", "제3장 휴가"), no_cite=True),
    dict(id="w26", category="nearmiss", base="suf26", anchors=["1일 1시간의 육아시간"],
         law=("국가공무원 복무규정", "제3장 휴가"), no_cite=True),
    dict(id="w27", category="nearmiss", base="suf27", anchors=["30일 전에 예고"],
         law=("근로기준법", "제2장 근로계약"), no_cite=True),
    dict(id="w28", category="leakage", base="suf28", anchors=["1주일에 평균 1회 이상의 유급휴일"],
         law=("근로기준법", "제4장 근로시간과 휴식"), no_cite=True,
         exclude=["40시간을 초과할 수 없다", "40시간으로 하며"]),
    dict(id="w29", category="leakage", base="suf29", anchors=["12시간을 한도로 제50조"],
         law=("근로기준법", "제4장 근로시간과 휴식"), no_cite=True, exclude=["100분의 50"]),
    dict(id="w30", category="leakage", base="suf30", anchors=["토요일 또는 공휴일 근무를 명할 수 있다"],
         law=("국가공무원 복무규정", "제2장 근무시간"), no_cite=True, exclude=["낮 12시부터"]),
    dict(id="w31", category="leakage", base="suf31", anchors=["| 3년 이상 4년 미만 | 14 |"],
         law=("국가공무원 복무규정", "제3장 휴가"), no_cite=True, exclude=["80퍼센트 이상 출근"]),
    dict(id="w32", category="inflated", base="suf32", anchors=["근무지 내 국내 출장의 경우에는"],
         law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비")),
    dict(id="w33", category="inflated", base="suf33", anchors=["| 3년 이상 4년 미만 | 14 |"],
         law=("국가공무원 복무규정", "제3장 휴가")),
    dict(id="w34", category="inflated", base="suf34", anchors=["최대 3년까지 이월"],
         law=("국가공무원 복무규정", "제3장 휴가")),
    dict(id="w35", category="format", base="suf35", anchors=[], extra=["별표2"],
         law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비")),
    dict(id="w36", category="format", base="suf36", anchors=[], extra=["정산시스템"],
         law=("공무원 여비 규정", "제1장 총칙")),
    dict(id="w37", category="format", base="suf37", anchors=[], extra=["FAQ"],
         law=("국가공무원 복무규정", "제3장 휴가")),
    dict(id="w38", category="format", base="suf38", anchors=[], extra=["PDF랩"],
         law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비"), exclude=["수로여행과 항공여행에는 숙박비"]),
    dict(id="w39", category="format", base="suf39", anchors=["병가 일수가 7일 이상"], dup=True,
         law=("국가공무원 복무규정", "제3장 휴가")),
    dict(id="w40", category="conflict", base="suf40", anchors=[], extra=["식비_구버전", "식비_신버전"],
         law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비")),
    dict(id="w41", category="position", base="suf41", anchors=["30일 전에 예고"], position="back",
         law=("근로기준법", "제2장 근로계약"), n=15),
    dict(id="w42", category="position", base="suf42", anchors=["1일 2시간의 근로시간 단축"], position="back",
         law=("근로기준법", "제5장 여성과 소년"), n=15),
    # 새 범주 - 같은 장의 문서만 12~15개인데 답이 없다
    dict(id="w43", category="many_absent", note="휴가 장 15개 - 배우자 출산휴가 일수는 별표에만",
         question="배우자가 출산하면 휴가를 며칠 받을 수 있는가?", unmet_need="배우자 출산 시 경조사휴가 일수",
         anchors=["별표 2의 기준에 따른 경조사휴가"], law=("국가공무원 복무규정", "제3장 휴가"),
         expect_verdict="insufficient", no_cite=True, n=15),
    dict(id="w44", category="many_absent", note="근로계약 장 15개 - 권고사직 위로금 기준은 없다",
         question="권고사직 시 위로금은 얼마나 받는가?", unmet_need="권고사직 위로금 지급 기준과 금액",
         anchors=["30일 전에 예고"], law=("근로기준법", "제2장 근로계약"),
         expect_verdict="insufficient", no_cite=True, n=15),
    dict(id="w45", category="many_absent", note="여비 12개 - 국외 항공 좌석 등급 기준은 별표 3에만 (마일리지로 상향 문장이 유혹)",
         question="국외 출장 때 비즈니스석을 탈 수 있는 직급 기준은?", unmet_need="국외 항공 좌석 등급의 직급별 기준",
         anchors=["좌석 등급을 상향 조정할 수 있는 경우"], law=("공무원 여비 규정", "제2장 운임"),
         expect_verdict="insufficient", no_cite=True, n=12),
    # 답이 두 청크의 겹침 구간에 걸쳐 있다
    dict(id="w46", category="split", note="복무20 ② 단서와 호가 청크 경계에 걸림 (만 40세 이상 분할 사용)",
         question="만 40세 이상 임신 공무원은 출산 전에 휴가를 나눠 쓸 수 있는가?",
         unmet_need="만 40세 이상 임신 공무원의 출산휴가 분할 사용 가능 여부",
         anchors=["만 40세 이상인 경우"], law=("국가공무원 복무규정", "제3장 휴가"),
         expect_verdict="sufficient"),
]


def _build_wide() -> list[dict]:
    base = {c["id"]: c for c in SUFFICIENCY}
    out = []
    for i, spec in enumerate(_WIDE_SPECS):
        src = base.get(spec.get("base"), {})
        law, chapter = spec["law"]
        n = spec.get("n", _N_CYCLE[i % len(_N_CYCLE)])
        position = spec.get("position", _POS_CYCLE[i % len(_POS_CYCLE)])
        extra = [PSEUDO[k] for k in spec.get("extra", ())]
        chunks, cited = _retrieve(spec["anchors"], law, chapter, n, position, seed=i,
                                  exclude=spec.get("exclude", ()), extra=extra)
        if spec.get("dup"):
            chunks = chunks + [chunks[min(cited)]]
            cited = cited | {len(chunks) - 1}
        case = dict(
            id=spec["id"], category=spec["category"], source="public",
            note=spec.get("note", src.get("note", "")) + f" · 청크 {len(chunks)}개 · 답 {position}",
            question=spec.get("question", src.get("question")),
            unmet_need=spec.get("unmet_need", src.get("unmet_need")),
            chunks=chunks, position=position,
            expect_verdict=spec.get("expect_verdict", src.get("expect_verdict")),
        )
        if src.get("accept"):
            case["accept"] = src["accept"]
        if src.get("inflated"):
            case["inflated"] = True
        if not spec.get("no_cite"):
            case["expect_cited"] = cited
        out.append(case)
    return out


WIDE = _build_wide()
SUFFICIENCY += WIDE

# ---------------------------------------------------------------------------
# Step 3 — 근거 활용
# ---------------------------------------------------------------------------

GROUNDING = [
    dict(
        id="gnd01", note="문서 내용을 그대로 활용",
        question="국내 출장 식비 상한은 얼마인가?",
        answer="국내 출장 식비는 1일 3만원을 상한으로 합니다.",
        chunks=RULES, expect="used",
    ),
    dict(
        id="gnd02", note="문서에 있는데 일반론으로 때움",
        question="국내 출장 식비 상한은 얼마인가?",
        answer="출장 식비는 회사 규정에 따라 지급되며, 자세한 금액은 부서별로 "
               "다를 수 있습니다.",
        chunks=RULES, expect="ignored",
    ),
    dict(
        id="gnd03", note="회피성 안내 — 거절이 아니라 활용 실패다",
        question="건강검진은 누가 언제 받는가?",
        answer="건강검진 관련 사항은 인사팀에 직접 문의해 주시기 바랍니다.",
        chunks=["임직원 건강검진은 매년 1회 실시하며, 만 35세 이상은 종합검진 대상으로 한다.",
                "만 35세 미만은 일반검진을 실시한다."],
        expect="ignored",
    ),
    dict(
        id="gnd04", note="문서와 다른 숫자를 말함",
        question="국내 출장 식비 상한은 얼마인가?",
        answer="국내 출장 식비는 1일 5만원입니다.",
        chunks=RULES, expect="contradicted",
    ),
    dict(
        id="gnd05", note="문서와 반대되는 결론",
        question="미사용 연차는 이월되는가?",
        answer="미사용 연차는 다음 해로 자동 이월됩니다.",
        chunks=["미사용 연차는 발생일로부터 1년이 경과하면 소멸함을 원칙으로 한다."],
        expect="contradicted",
    ),
    dict(
        id="gnd06", note="표현은 다르지만 문서 내용을 반영",
        question="출장비 정산은 언제까지 하는가?",
        answer="정산은 출장이 끝난 뒤 5영업일 안에 마치셔야 합니다.",
        chunks=RULES, expect="used",
    ),
    dict(
        id="gnd07", note="문서에 없는 내용이지만 어긋나지도 않음",
        question="출장 신청 절차는?",
        answer="출장 신청은 부서장 승인 후 진행하시면 됩니다.",
        chunks=RULES,
        # 문서를 쓰지 않았다. 다만 어긋나는 주장은 아니므로 contradicted 가 아니다.
        expect="ignored",
    ),
    dict(
        id="gnd08", note="여러 청크를 종합해 답함",
        question="국내 출장 식비 · 숙박비 상한과 정산 기한은?",
        answer="식비는 1일 3만원, 숙박비는 1박 8만원이며 정산은 5영업일 이내입니다.",
        chunks=RULES, expect="used",
    ),
]

# ---------------------------------------------------------------------------
# 검색 결과 모양의 근거 활용 케이스 (g01~) — 문서 10~15개 × 약 500자
#
# 위 8건은 청크가 한 문장이라 "문서 15개 중 하나를 썼는가" 를 재지 못한다. 아래는 Step 2 와
# 같은 청크 풀에서 검색 결과처럼 고른다. 필드:
#   question   사용자 질문 (지금 설계는 Step 3 에 주지 않는다 - 변형 측정용)
#   cited      Step 2 가 인용했을 청크 번호 (요구에 답하는 청크) - 변형 측정용
#   also       답변이 쓴 다른 청크의 anchor (ignored_wrong_chunk 에서 답변이 엉뚱한 청크를 쓴 것)
#   expect     used / ignored / contradicted · accept 는 정답이 애매할 때
#
#   used_clear          문서 내용을 표현만 바꿔 씀
#   used_multi          두 청크를 종합
#   used_unit           단위 · 표기가 다름 ("100,000원" → "십만 원")
#   ignored_generic     문서에 있는데 일반론
#   ignored_deflect     회피성 안내 ("인사팀에 문의")
#   ignored_wrong_chunk 답변이 문서의 다른 청크는 썼지만 요구에 답하는 청크는 안 씀 (H1)
#   contradicted_number 숫자가 문서와 다름
#   contradicted_conclusion 결론이 반대
#   contradicted_trap   한 청크와는 다르지만 맞는 청크와는 일치 → used
#   position            답변이 쓴 청크가 15개 중 맨 뒤
#   partial_use         문서 일부만 쓰고 나머지는 일반론 → accept {used, ignored}
# ---------------------------------------------------------------------------

_G_SPECS = [
    dict(id="g01", category="used_clear", question="근무지 내 출장인데 4시간 넘게 걸리면 여비가 얼마인가?",
         answer="근무지 내 출장으로 4시간 이상 걸리면 2만원을 지급받으실 수 있습니다.",
         anchors=["근무지 내 국내 출장의 경우에는"], law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비"), expect="used"),
    dict(id="g02", category="used_clear", question="재직 3년차 연가는 며칠인가?",
         answer="재직기간이 3년 이상 4년 미만이면 연가는 14일입니다.",
         anchors=["| 3년 이상 4년 미만 | 14 |"], law=("국가공무원 복무규정", "제3장 휴가"), expect="used"),
    dict(id="g03", category="used_clear", question="병가 진단서는 언제부터 필요한가?",
         answer="병가가 7일 이상이면 의사 진단서를 첨부하셔야 합니다.",
         anchors=["7일 이상일 경우"], law=("국가공무원 복무규정", "제3장 휴가"), expect="used"),
    dict(id="g04", category="used_clear", question="해고하려면 며칠 전에 예고해야 하는가?",
         answer="해고하려면 최소 30일 전에 예고해야 하고, 예고하지 않으면 30일분 이상의 통상임금을 지급해야 합니다.",
         anchors=["30일 전에 예고"], law=("근로기준법", "제2장 근로계약"), expect="used"),
    dict(id="g05", category="used_clear", question="국외 출장 추가 여비 정산은 언제까지 신청하나?",
         answer="국외 출장은 여행을 마친 다음 날부터 2주 안에 정산을 신청하시면 됩니다.",
         anchors=["2주일 이내를 말한다"], law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비"), expect="used"),
    dict(id="g06", category="used_clear", question="남은 연가를 저축하면 언제까지 쓸 수 있나?",
         answer="남은 연가는 최대 3년까지 저축해 쓸 수 있고, 저축 기간이 끝난 뒤 2년 안에 안 쓰면 소멸됩니다.",
         anchors=["최대 3년까지 이월"], law=("국가공무원 복무규정", "제3장 휴가"), expect="used"),
    dict(id="g07", category="used_multi", question="출산전후휴가 기간과 유급 기간은?",
         answer="출산전후휴가는 90일(다태아 120일)이고, 그중 최초 60일(다태아 75일)은 유급입니다.",
         anchors=["120일)의 출산전후휴가", "최초 60일(한 번에 둘 이상"], law=("근로기준법", "제5장 여성과 소년"), expect="used"),
    dict(id="g08", category="used_multi", question="법정 근로시간과 연장 한도는?",
         answer="주 40시간, 하루 8시간을 넘길 수 없고, 당사자가 합의하면 주 12시간까지 연장할 수 있습니다.",
         anchors=["40시간을 초과할 수 없다", "12시간을 한도로 제50조"], law=("근로기준법", "제4장 근로시간과 휴식"), expect="used"),
    dict(id="g09", category="used_multi", question="연차 사용 촉진은 어떻게 하나?",
         answer="휴가 소멸 6개월 전을 기준으로 10일 안에 미사용 일수를 알려주고, 근로자가 10일 안에 시기를 정하지 않으면 2개월 전까지 회사가 시기를 정해 서면으로 통보합니다.",
         anchors=["6개월 전을 기준으로 10일 이내"], law=("근로기준법", "제4장 근로시간과 휴식"), expect="used"),
    dict(id="g10", category="used_unit", question="국내 출장 서울 숙박비 상한은?",
         answer="서울은 1박 십만 원까지 실비로 지급됩니다.",
         anchors=[], extra=["별표2"], law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비"), expect="used"),
    dict(id="g11", category="used_unit", question="연장근로 수당은 얼마나 가산되나?",
         answer="연장근로 수당은 통상임금의 50%를 가산해 지급합니다.",
         anchors=["100분의 50"], law=("근로기준법", "제4장 근로시간과 휴식"), expect="used"),
    dict(id="g12", category="used_unit", question="장기 출장 시 일비는 줄어드나?",
         answer="같은 곳에 보름 넘게 머무르면 초과 일수의 일비가 10% 깎이고, 한 달 넘으면 20%, 두 달 넘으면 30% 깎입니다.",
         anchors=["15일을 초과한 경우"], law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비"), expect="used"),
    dict(id="g13", category="ignored_generic", question="국내 출장 정산 신청 기한은?",
         answer="출장비 정산은 사내 규정에 따라 기한 내에 처리하시면 됩니다.",
         anchors=["국내 여행자는 여행을 마친 날의 다음 날부터"], law=("공무원 여비 규정", "제1장 총칙"), expect="ignored"),
    dict(id="g14", category="ignored_generic", question="재직 3년차 연가는 며칠인가?",
         answer="연가 일수는 재직기간에 따라 달라지며 인사 규정을 참고하시기 바랍니다.",
         anchors=["| 3년 이상 4년 미만 | 14 |"], law=("국가공무원 복무규정", "제3장 휴가"), expect="ignored"),
    dict(id="g15", category="ignored_generic", question="병가는 1년에 며칠까지 가능한가?",
         answer="병가는 필요에 따라 적절히 승인될 수 있습니다.",
         anchors=["연 180일의 범위"], law=("국가공무원 복무규정", "제3장 휴가"), expect="ignored"),
    dict(id="g16", category="ignored_generic", question="해고하려면 며칠 전에 예고해야 하는가?",
         answer="해고는 관련 법령에 따라 적법한 절차를 거쳐야 합니다.",
         anchors=["30일 전에 예고"], law=("근로기준법", "제2장 근로계약"), expect="ignored"),
    dict(id="g17", category="ignored_deflect", question="국내 출장 서울 숙박비 상한은?",
         answer="숙박비 상한은 총무팀에 문의해 주세요.",
         anchors=[], extra=["별표2"], law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비"), expect="ignored"),
    dict(id="g18", category="ignored_deflect", question="쌍둥이 출산휴가는 며칠인가?",
         answer="출산휴가 관련 사항은 인사팀에서 안내드리고 있습니다. 인사팀으로 문의 부탁드립니다.",
         anchors=["120일)의 출산휴가"], law=("국가공무원 복무규정", "제3장 휴가"), expect="ignored"),
    dict(id="g19", category="ignored_deflect", question="남은 연가를 저축하면 언제까지 쓸 수 있나?",
         answer="해당 내용은 제가 확인할 수 없는 정보입니다. 담당 부서에 문의해 주세요.",
         anchors=["최대 3년까지 이월"], law=("국가공무원 복무규정", "제3장 휴가"), expect="ignored"),
    dict(id="g20", category="ignored_deflect", question="해고하려면 며칠 전에 예고해야 하는가?",
         answer="죄송하지만 해고 예고 기간에 대한 정보를 찾지 못했습니다.",
         anchors=["30일 전에 예고"], law=("근로기준법", "제2장 근로계약"), expect="ignored"),
    dict(id="g21", category="ignored_deflect", question="국내 출장 정산 신청 기한은?",
         answer="출장비 정산 기한은 회계팀 공지사항을 확인해 주시기 바랍니다.",
         anchors=["국내 여행자는 여행을 마친 날의 다음 날부터"], law=("공무원 여비 규정", "제1장 총칙"), expect="ignored"),
    dict(id="g22", category="ignored_wrong_chunk", question="병가 진단서는 언제부터 필요한가?",
         answer="병가 중 연간 6일을 초과하는 일수는 연가에서 차감됩니다.",
         anchors=["7일 이상일 경우"], also=["연간 6일을 초과하는 병가"], law=("국가공무원 복무규정", "제3장 휴가"), expect="ignored"),
    dict(id="g23", category="ignored_wrong_chunk", question="근무지 내 출장 여비는 얼마인가?",
         answer="같은 곳에 15일 넘게 체재하면 초과 일수의 일비가 10분의 1 감액됩니다.",
         anchors=["근무지 내 국내 출장의 경우에는"], also=["15일을 초과한 경우"], law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비"), expect="ignored"),
    dict(id="g24", category="ignored_wrong_chunk", question="연차 사용 촉진 통보는 언제까지 해야 하나?",
         answer="연차는 1년간 80% 이상 출근하면 15일이 발생합니다.",
         anchors=["6개월 전을 기준으로 10일 이내"], also=["80퍼센트 이상 출근한"], law=("근로기준법", "제4장 근로시간과 휴식"), expect="ignored"),
    dict(id="g25", category="ignored_wrong_chunk", question="출산전후휴가는 며칠인가?",
         answer="임신 12주 이내이거나 36주 이후면 하루 2시간 근로시간 단축을 신청할 수 있습니다.",
         anchors=["120일)의 출산전후휴가"], also=["1일 2시간의 근로시간 단축"], law=("근로기준법", "제5장 여성과 소년"), expect="ignored"),
    dict(id="g26", category="ignored_wrong_chunk", question="해고하려면 며칠 전에 예고해야 하는가?",
         answer="부당해고 구제신청은 해고일부터 3개월 이내에 노동위원회에 하시면 됩니다.",
         anchors=["30일 전에 예고"], also=["3개월 이내에 하여야"], law=("근로기준법", "제2장 근로계약"), expect="ignored"),
    dict(id="g27", category="contradicted_number", question="근무지 내 출장인데 4시간 넘게 걸리면 여비가 얼마인가?",
         answer="근무지 내 출장으로 4시간 이상이면 3만원을 지급합니다.",
         anchors=["근무지 내 국내 출장의 경우에는"], law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비"), expect="contradicted"),
    dict(id="g28", category="contradicted_number", question="재직 3년차 연가는 며칠인가?",
         answer="재직 3년 이상 4년 미만이면 연가는 15일입니다.",
         anchors=["| 3년 이상 4년 미만 | 14 |"], law=("국가공무원 복무규정", "제3장 휴가"), expect="contradicted"),
    dict(id="g29", category="contradicted_number", question="병가 진단서는 언제부터 필요한가?",
         answer="병가 진단서는 3일 이상이면 첨부해야 합니다.",
         anchors=["7일 이상일 경우"], law=("국가공무원 복무규정", "제3장 휴가"), expect="contradicted"),
    dict(id="g30", category="contradicted_number", question="해고하려면 며칠 전에 예고해야 하는가?",
         answer="해고 예고는 14일 전까지 하시면 됩니다.",
         anchors=["30일 전에 예고"], law=("근로기준법", "제2장 근로계약"), expect="contradicted"),
    dict(id="g31", category="contradicted_conclusion", question="배로 이동하는 출장에서도 숙박비가 나오나?",
         answer="배나 항공기로 이동하는 출장에서도 숙박비가 정상적으로 지급됩니다.",
         anchors=["수로여행과 항공여행에는 숙박비"], law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비"), expect="contradicted"),
    dict(id="g32", category="contradicted_conclusion", question="남은 연가를 저축하면 언제까지 쓸 수 있나?",
         answer="저축한 연가는 기간 제한 없이 계속 이월되어 소멸되지 않습니다.",
         anchors=["최대 3년까지 이월"], law=("국가공무원 복무규정", "제3장 휴가"), expect="contradicted"),
    dict(id="g33", category="contradicted_conclusion", question="입사 1년 미만이면 연차가 없나?",
         answer="계속 근로 기간이 1년 미만인 근로자에게는 연차 유급휴가가 발생하지 않습니다.",
         anchors=["1개월 개근 시 1일"], law=("근로기준법", "제4장 근로시간과 휴식"), expect="contradicted"),
    dict(id="g34", category="contradicted_trap", question="지금 국내 출장 식비는 하루 얼마인가?",
         answer="국내 출장 식비는 하루 25,000원입니다.",
         anchors=[], extra=["식비_신버전"], also_extra=["식비_구버전"], law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비"), expect="used"),
    dict(id="g35", category="contradicted_trap", question="3년차인데 연가를 미리 당겨 쓰면 최대 며칠인가?",
         answer="재직 3년 이상 4년 미만이면 최대 8일까지 미리 사용할 수 있습니다.",
         anchors=["| 3년 이상 4년 미만 | 8 |"], also=["| 3년 이상 4년 미만 | 14 |"], law=("국가공무원 복무규정", "제3장 휴가"), expect="used"),
    dict(id="g36", category="contradicted_trap", question="공무상 질병이면 병가를 얼마나 쓸 수 있나?",
         answer="공무상 질병이나 부상이면 연 180일까지 병가를 승인받을 수 있습니다.",
         anchors=["연 180일의 범위"], law=("국가공무원 복무규정", "제3장 휴가"), expect="used"),
    dict(id="g37", category="position", question="근무지 내 출장인데 4시간 넘게 걸리면 여비가 얼마인가?",
         answer="근무지 내 출장으로 4시간 이상 걸리면 2만원을 지급받으실 수 있습니다.",
         anchors=["근무지 내 국내 출장의 경우에는"], law=("공무원 여비 규정", "제3장 일비·숙박비 및 식비"), expect="used", n=15, position="back"),
    dict(id="g38", category="position", question="남은 연가를 저축하면 언제까지 쓸 수 있나?",
         answer="남은 연가는 최대 3년까지 저축해 쓸 수 있고, 저축 기간이 끝난 뒤 2년 안에 안 쓰면 소멸됩니다.",
         anchors=["최대 3년까지 이월"], law=("국가공무원 복무규정", "제3장 휴가"), expect="used", n=15, position="back"),
    dict(id="g39", category="position", question="연장근로 수당은 얼마나 가산되나?",
         answer="연장근로 수당은 통상임금의 50%를 가산해 지급합니다.",
         anchors=["100분의 50"], law=("근로기준법", "제4장 근로시간과 휴식"), expect="used", n=15, position="back"),
    dict(id="g40", category="partial_use", question="출산전후휴가는 며칠이고 나눠 쓸 수 있나?",
         answer="출산전후휴가는 90일이며, 분할 사용은 부서와 협의하시면 됩니다.",
         anchors=["120일)의 출산전후휴가"], law=("근로기준법", "제5장 여성과 소년"), expect="used", accept={"used", "ignored"}),
    dict(id="g41", category="partial_use", question="국내 출장 정산 기한과 증빙은?",
         answer="정산은 1주일 이내에 신청하시고, 증빙은 상황에 따라 다릅니다.",
         anchors=["국내 여행자는 여행을 마친 날의 다음 날부터"], law=("공무원 여비 규정", "제1장 총칙"), expect="used", accept={"used", "ignored"}),
    dict(id="g42", category="partial_use", question="재직 3년차 연가 일수와 반차 가능 여부는?",
         answer="3년차는 연가 14일이고, 반차는 팀장님께 여쭤보시면 됩니다.",
         anchors=["| 3년 이상 4년 미만 | 14 |"], law=("국가공무원 복무규정", "제3장 휴가"), expect="used", accept={"used", "ignored"}),
]


def _build_grounding_wide() -> list[dict]:
    out = []
    for i, spec in enumerate(_G_SPECS):
        law, chapter = spec["law"]
        n = spec.get("n", _N_CYCLE[i % len(_N_CYCLE)])
        position = spec.get("position", _POS_CYCLE[i % len(_POS_CYCLE)])
        cited_texts = [c["text"] for c in _CHUNKS if any(a in c["text"] for a in spec["anchors"])]
        cited_texts += [PSEUDO[k] for k in spec.get("extra", ())]
        also_texts = [c["text"] for c in _CHUNKS if any(a in c["text"] for a in spec.get("also", ()))]
        also_texts += [PSEUDO[k] for k in spec.get("also_extra", ())]
        assert cited_texts, spec["id"]
        chunks, _ = _retrieve(list(spec["anchors"]) + list(spec.get("also", ())), law, chapter, n, position,
                              seed=100 + i,
                              extra=[PSEUDO[k] for k in list(spec.get("extra", ())) + list(spec.get("also_extra", ()))])
        cited = {j for j, c in enumerate(chunks) if c in cited_texts}
        case = dict(
            id=spec["id"], category=spec["category"],
            note=f"{spec['category']} · 청크 {len(chunks)}개 · 인용 청크 {position}",
            question=spec["question"], answer=spec["answer"], chunks=chunks,
            cited=cited, position=position, expect=spec["expect"],
        )
        if spec.get("accept"):
            case["accept"] = spec["accept"]
        out.append(case)
    return out


GROUNDING_WIDE = _build_grounding_wide()
GROUNDING += GROUNDING_WIDE


# ---------------------------------------------------------------------------
# ④′ 읽기 골든셋 — 답변만 보고 "사람이 읽을 수 있는 글인가"
#
# 재는 것은 오탐이다. 모양이 특이하지만 멀쩡한 답변(표 · 코드 · JSON · 영문 · 한 줄 ·
# 이모지 · 거절 · 약어)을 읽을 수 없다고 하면 그 턴의 진짜 원인이 아무 단계에서도
# 판정받지 못한다. 그래서 정상 쪽을 붕괴 쪽의 두 배로 둔다.
#
# 붕괴 쪽은 코드 규칙(degenerate)이 못 잡는 모양만 담는다 - 5555… 는 여기 없다.
# ---------------------------------------------------------------------------

def _repeat_drift(base: str, n: int) -> str:
    tails = ["입니다.", "이며 확인 바랍니다.", "이고요.", "입니다만,", "이라고 합니다.", "입니다!"]
    return " ".join(base + tails[i % len(tails)] for i in range(n))


LEGIBILITY = [
    # ---------- 읽을 수 없다 (expect False) ----------
    dict(id="bad01", cat="토큰 잡탕", legible=False,
         answer="연차는 입사일 기준 15일이며 ㅁㄴㅇㄹ 申請 the the the 승인을 받으면 ᄀᄁᄂ 처리됩니다 vector_"),
    dict(id="bad02", cat="토큰 잡탕", legible=False,
         answer="出張費 정산은 5영업일 within ERP 에서 にて 처리하고 증빙은 recei 영수증 附 the of of"),
    dict(id="bad03", cat="토큰 잡탕", legible=False,
         answer="재직증명서 발급 groupware > 증명 발급 menu에서 即時 печать 가능합니다 hhhh 담당 tel"),
    dict(id="bad04", cat="토큰 잡탕", legible=False,
         answer="VPN 접속은 MFA 인증 후 가능 ㅇㅇㅇㅇㅇ authentication token 을 을 을 를 입력 입력 입력하시면"),
    dict(id="bad05", cat="토큰 잡탕", legible=False,
         answer="법인카드 한도 상향 은 팀장 승인 이후 finance 팀 檢討 를 거쳐 dsfkj 반영 됩니다 되 됩니 다다"),
    dict(id="bad06", cat="중간부터 깨짐", legible=False,
         answer="국내 출장 식비는 1일 3만원을 상한으로 합니다. 숙박비는 1박 8만원까지 정산됩니다. "
                "정산은 출장 종료 후 5영업일 이내에 ERP에서 하시면 됩니다. asdkjh qwpoie zxmcnv 3만 3만 3만 "
                "출장출장출장 the the ERP ERP ERP 이내이내이내에에에"),
    dict(id="bad07", cat="중간부터 깨짐", legible=False,
         answer="연차 이월은 인사규정 제12조에 따라 다음 해 3월 말까지 사용할 수 있습니다. 다만 "
                "ふうふうふう 이월된 연차는 は は は 수당으로 ¥¥¥ 전환되지 않 않 않으며 ###### %%%%"),
    dict(id="bad08", cat="중간부터 깨짐", legible=False,
         answer="재택근무는 주 2회까지 신청하실 수 있습니다. 신청은 근무 희망일 전일까지 그룹웨어에 등록하시면 되고, "
                "코어타임 10시~16시에는 연락이 가능해야 합니다. ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ ㄱㄴㄷㄹㅁㅂㅅ 근무근무근무근무 "
                "time time time 등록등록등록 되 되 되 되"),
    dict(id="bad09", cat="중간부터 깨짐", legible=False,
         answer="출입증 분실 시에는 총무팀에 신고하고 재발급을 신청하시면 됩니다. 재발급 수수료는 1만원이며 급여에서 공제됩니다. "
                "수수료수수료 1만1만1만 공제공제 총무 총무 총무 총무 총무 총무 총무 총무 총무 총무 총무 총무 총무 총무"),
    dict(id="bad10", cat="문단 되풀이", legible=False,
         answer=_repeat_drift("연차는 입사일 기준으로 매년 15일이 부여되며 팀장의 승인을 받아 사용", 6)),
    dict(id="bad11", cat="문단 되풀이", legible=False,
         answer=_repeat_drift("법인카드 사용 내역은 매월 말일 기준으로 자동 집계", 7)),
    dict(id="bad12", cat="문단 되풀이", legible=False,
         answer="출장비 정산 절차를 안내드리겠습니다.\n\n1. 출장 종료 후 5영업일 이내에 정산합니다.\n"
                "1. 출장 종료 후 5영업일 이내에 정산합니다.\n1. 출장 종료 후 5영업일 안에 정산합니다.\n"
                "1. 출장 종료 후 5영업일 이내에 정산하십시오.\n1. 출장 종료 후 5영업일 이내 정산합니다.\n"
                "1. 출장 종료 후 5영업일 이내에 정산합니다.\n1. 출장 종료 후 5영업일 이내에 정산을 합니다."),
    dict(id="bad13", cat="프롬프트 유출", legible=False,
         answer="You are a helpful assistant for internal company policy. Answer in Korean using only the provided context. "
                "[SYSTEM] context_window=4096 temperature=0.2 \n<|im_start|>assistant\n연차는"),
    dict(id="bad14", cat="프롬프트 유출", legible=False,
         answer="### 지시사항\n다음 문서를 바탕으로 사용자 질문에 답하세요. 문서에 없는 내용은 답하지 마세요.\n"
                "### 문서\n{{retrieved_chunks}}\n### 질문\n{{user_query}}\n### 답변\n"),
    dict(id="bad15", cat="프롬프트 유출", legible=False,
         answer="<think>사용자가 연차 이월을 묻고 있다. 문서 청크 2에 관련 내용이... 아니 청크 1인가. 다시 보자.</think>"
                "<think>청크 1: 연차유급휴가 신청. 청크 2: 승인. 이월 언급 없음.</think><think>그러면"),
    dict(id="bad16", cat="내부 오류 노출", legible=False,
         answer='{"error": {"code": 502, "message": "upstream connect error or disconnect/reset before headers. '
                'reset reason: connection failure", "trace_id": "8f3a1c"}}'),
    dict(id="bad17", cat="내부 오류 노출", legible=False,
         answer="Traceback (most recent call last):\n  File \"/app/rag/pipeline.py\", line 212, in generate\n"
                "    ctx = retriever.search(q, k=5)\n  File \"/app/rag/retriever.py\", line 88, in search\n"
                "KeyError: 'embedding'"),
    dict(id="bad18", cat="무의미한 문장", legible=False,
         answer="연차의 승인은 승인의 연차이며 신청은 신청을 신청합니다. 팀장은 팀장이 팀장에게 팀장을 승인하고, "
                "그룹웨어의 그룹웨어가 그룹웨어를 합니다. 따라서 결론적으로 연차는 연차입니다."),
    dict(id="bad19", cat="무의미한 문장", legible=False,
         answer="출장비는 정산되는 출장의 비용으로서 정산의 정산을 위해 정산되며, 영수증은 영수증이 영수증을 첨부하는 "
                "영수증입니다. ERP는 ERP에서 ERP로 ERP를 ERP합니다."),
    dict(id="bad20", cat="무의미한 문장", legible=False,
         answer="네 알겠습니다 확인했습니다 네 알겠습니다 그렇습니다 확인 부탁드립니다 네 네 확인했습니다 알겠습니다 "
                "감사합니다 확인했습니다 네 그렇습니다 확인 확인했습니다 알겠습니다 네"),

    # ---------- 읽을 수 있다 (expect True) — 모양이 특이한 정상 답변 ----------
    dict(id="ok01", cat="표", legible=True,
         answer="항목별 상한은 다음과 같습니다.\n\n| 항목 | 상한 |\n|---|---|\n| 식비 | 1일 3만원 |\n| 숙박비 | 1박 8만원 |"),
    dict(id="ok02", cat="표", legible=True,
         answer="| 구분 | 신청처 | 소요 |\n|---|---|---|\n| 재직증명서 | 그룹웨어 | 즉시 |\n| 경력증명서 | 인사팀 | 2영업일 |"),
    dict(id="ok03", cat="표", legible=True,
         answer="| 직급 | 연차 |\n|:--|--:|\n| 사원 | 15 |\n| 대리 | 16 |\n| 과장 | 18 |\n\n※ 입사 1년 미만은 월 1일씩 발생합니다."),
    dict(id="ok04", cat="표", legible=True,
         answer="지역별 숙박비 상한(1박)입니다.\n\n지역 | 상한\n--- | ---\n미주 | 250달러\n유럽 | 220달러\n아시아 | 150달러"),
    dict(id="ok05", cat="표", legible=True,
         answer="| | 1분기 | 2분기 |\n|---|---|---|\n| 예산 | 1,200 | 1,350 |\n| 집행 | 980 | 1,410 |\n\n단위: 만원"),
    dict(id="ok06", cat="코드", legible=True,
         answer="다음 쿼리를 쓰시면 됩니다.\n\n```sql\nSELECT emp_no, amount\nFROM trip_expense\nWHERE settled_at >= DATE_TRUNC('month', CURRENT_DATE)\nORDER BY amount DESC;\n```"),
    dict(id="ok07", cat="코드", legible=True,
         answer="```python\nimport os\n\nfor name in sorted(os.listdir('.')):\n    if name.endswith('.csv'):\n        print(name)\n```\n\n현재 폴더의 CSV 파일만 출력합니다."),
    dict(id="ok08", cat="코드", legible=True,
         answer="Excel 에서는 `=VLOOKUP(A2, 규정!A:B, 2, FALSE)` 를 쓰시면 됩니다. 마지막 인자 FALSE 가 정확히 일치입니다."),
    dict(id="ok09", cat="코드", legible=True,
         answer="```bash\ngit fetch --tags\ngit checkout v1.4.2\npip install -r requirements.txt\n```"),
    dict(id="ok10", cat="코드", legible=True,
         answer="정규식은 `^\\d{6}-\\d{7}$` 입니다. 앞 6자리와 뒤 7자리 사이에 하이픈이 하나 옵니다."),
    dict(id="ok11", cat="JSON", legible=True,
         answer='요청하신 형식입니다.\n\n```json\n{"item": "식비", "limit_per_day": 30000, "currency": "KRW"}\n```'),
    dict(id="ok12", cat="JSON", legible=True,
         answer='[{"name": "재직증명서", "code": "HR-07"}, {"name": "경력증명서", "code": "HR-08"}]'),
    dict(id="ok13", cat="JSON", legible=True,
         answer='{\n  "vpn_required": true,\n  "mfa_methods": ["app_otp", "sms"],\n  "helpdesk": "내선 1234"\n}'),
    dict(id="ok14", cat="영문", legible=True,
         answer="Annual leave is granted at 15 days per year based on your hire date. Submit the HR-01 form on the groupware and get your team lead's approval."),
    dict(id="ok15", cat="영문", legible=True,
         answer="Domestic travel meal allowance is capped at KRW 30,000 per day; lodging at KRW 80,000 per night."),
    dict(id="ok16", cat="영문", legible=True,
         answer="Sorry, I couldn't find that in the policy documents. Please contact the HR team (ext. 1234)."),
    dict(id="ok17", cat="영문", legible=True,
         answer="Yes — remote work is allowed up to twice a week. Register the day before on the groupware; core hours are 10:00–16:00."),
    dict(id="ok18", cat="한 줄", legible=True, answer="네."),
    dict(id="ok19", cat="한 줄", legible=True, answer="모르겠습니다."),
    dict(id="ok20", cat="한 줄", legible=True, answer="인사팀(내선 1234)에 문의해 주세요."),
    dict(id="ok21", cat="한 줄", legible=True, answer="1일 3만원입니다."),
    dict(id="ok22", cat="한 줄", legible=True, answer="해당 내용은 문서에서 확인되지 않습니다."),
    dict(id="ok23", cat="이모지", legible=True, answer="확인해 보세요! 👍 그룹웨어 > 증명서 발급 메뉴입니다 😊"),
    dict(id="ok24", cat="이모지", legible=True, answer="✅ 신청 완료\n⏳ 팀장 승인 대기\n📩 승인되면 알림이 갑니다"),
    dict(id="ok25", cat="이모지", legible=True, answer="주의하세요 ⚠️ 출장 신청은 출발 7일 전까지입니다."),
    dict(id="ok26", cat="번호 목록", legible=True,
         answer="1. 그룹웨어에 접속합니다.\n2. 증명서 발급 메뉴로 갑니다.\n3. 재직증명서(HR-07)를 선택합니다.\n4. 출력 버튼을 누릅니다."),
    dict(id="ok27", cat="번호 목록", legible=True,
         answer="- 식비: 1일 3만원\n- 숙박비: 1박 8만원\n- 정산 기한: 종료 후 5영업일"),
    dict(id="ok28", cat="번호 목록", legible=True,
         answer="① 팀장 승인 → ② 구매팀 검토(500만원 이상) → ③ 발주 → ④ 입고(통상 10영업일)"),
    dict(id="ok29", cat="번호 목록", legible=True,
         answer="• VPN 클라이언트 설치\n• 사내 인증서로 로그인\n• 인증서는 1년마다 갱신 (만료 30일 전부터 가능)"),
    dict(id="ok30", cat="긴 정상", legible=True,
         answer="해외 출장비 정산과 관련하여 안내드리겠습니다. 먼저 해외 출장을 다녀오신 경우에는 출장이 종료된 날로부터 "
                "5영업일 이내에 정산서를 제출해 주셔야 합니다. 정산서에는 출장 기간과 방문지, 그리고 지출하신 항목을 "
                "구분하여 기재해 주시면 됩니다.\n\n숙박비의 경우에는 실비 정산을 원칙으로 하고 있으므로, 숙박하신 "
                "호텔에서 발급받은 영수증을 반드시 첨부해 주셔야 합니다. 영수증이 누락되면 정산이 지연될 수 있으니 "
                "출장 중에 미리 챙겨두시는 것을 권해 드립니다."),
    dict(id="ok31", cat="긴 정상", legible=True,
         answer="연차유급휴가 제도에 대해 안내드리겠습니다. 연차는 그룹웨어를 통해 사전에 신청하시는 것이 원칙이며, "
                "신청하신 내용은 팀장님의 승인을 거쳐 확정됩니다. 승인이 완료되면 알림이 발송되므로 확인하실 수 있습니다. "
                "연차는 하루 단위뿐 아니라 반차 단위로도 사용하실 수 있어서, 반나절만 필요하신 경우에도 유연하게 쓰실 수 "
                "있습니다. 다만 팀 업무 일정과 겹치지 않도록 사전에 팀 내 공유를 해주시는 것이 좋습니다."),
    dict(id="ok32", cat="긴 정상", legible=True,
         answer="사내 자료의 외부 반출은 보안심의를 거쳐야 합니다. 절차는 다음과 같습니다. 먼저 반출 사유서와 반출 대상 자료 "
                "목록을 준비하시고, 정보보안팀에 심의를 신청합니다. 심의는 통상 3영업일이 걸리며, 승인되면 승인번호가 "
                "발급됩니다. USB 등 이동식 저장매체를 쓰시는 경우에는 별도로 사전 승인이 필요하니 참고해 주세요."),
    dict(id="ok33", cat="거절", legible=True,
         answer="죄송하지만 개인별 급여 정보는 보안 정책상 이 채널에서 안내해 드릴 수 없습니다. 급여 담당자에게 직접 문의해 주세요."),
    dict(id="ok34", cat="거절", legible=True,
         answer="해당 요청은 권한이 필요한 정보라 답변드리기 어렵습니다. 부서장 승인 후 인사팀에 요청해 주시기 바랍니다."),
    dict(id="ok35", cat="거절", legible=True,
         answer="문서에서 관련 내용을 찾지 못했습니다. 질문을 조금 더 구체적으로 적어 주시면 다시 찾아보겠습니다."),
    dict(id="ok36", cat="약어·용어", legible=True,
         answer="사외에서 사내망 접속은 VPN + MFA 입니다. MFA 는 사내 앱 OTP 또는 SMS 로 하시면 되고, 계정 잠김은 IT헬프데스크(내선 1234)에서 해제합니다."),
    dict(id="ok37", cat="약어·용어", legible=True,
         answer="ERP 의 GL 전표는 AP 모듈에서 PO 와 GR 을 매칭한 뒤 승인 워크플로(WF)로 넘어갑니다. SoD 위반 시 반려됩니다."),
    dict(id="ok38", cat="약어·용어", legible=True,
         answer="K8s 파드가 CrashLoopBackOff 면 kubectl logs -p 로 이전 컨테이너 로그를 먼저 보세요. OOMKilled 면 limits.memory 를 올립니다."),
    dict(id="ok39", cat="숫자 위주", legible=True,
         answer="식비 30,000원/일 · 숙박 80,000원/박 · 정산 D+5 영업일 · 초과분 본인 부담"),
    dict(id="ok40", cat="숫자 위주", legible=True,
         answer="2026-03-01 ~ 2026-03-03 (2박 3일), 서울→부산 KTX 59,800원 ×2, 숙박 80,000원 ×2 = 279,600원"),
]
