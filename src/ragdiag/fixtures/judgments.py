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
# Step 3 — 근거 활용
# ---------------------------------------------------------------------------

GROUNDING = [
    dict(
        id="gnd01", note="문서 내용을 그대로 활용",
        answer="국내 출장 식비는 1일 3만원을 상한으로 합니다.",
        chunks=RULES, expect="used",
    ),
    dict(
        id="gnd02", note="문서에 있는데 일반론으로 때움",
        answer="출장 식비는 회사 규정에 따라 지급되며, 자세한 금액은 부서별로 "
               "다를 수 있습니다.",
        chunks=RULES, expect="ignored",
    ),
    dict(
        id="gnd03", note="회피성 안내 — 거절이 아니라 활용 실패다",
        answer="건강검진 관련 사항은 인사팀에 직접 문의해 주시기 바랍니다.",
        chunks=["임직원 건강검진은 매년 1회 실시하며, 만 35세 이상은 종합검진 대상으로 한다.",
                "만 35세 미만은 일반검진을 실시한다."],
        expect="ignored",
    ),
    dict(
        id="gnd04", note="문서와 다른 숫자를 말함",
        answer="국내 출장 식비는 1일 5만원입니다.",
        chunks=RULES, expect="contradicted",
    ),
    dict(
        id="gnd05", note="문서와 반대되는 결론",
        answer="미사용 연차는 다음 해로 자동 이월됩니다.",
        chunks=["미사용 연차는 발생일로부터 1년이 경과하면 소멸함을 원칙으로 한다."],
        expect="contradicted",
    ),
    dict(
        id="gnd06", note="표현은 다르지만 문서 내용을 반영",
        answer="정산은 출장이 끝난 뒤 5영업일 안에 마치셔야 합니다.",
        chunks=RULES, expect="used",
    ),
    dict(
        id="gnd07", note="문서에 없는 내용이지만 어긋나지도 않음",
        answer="출장 신청은 부서장 승인 후 진행하시면 됩니다.",
        chunks=RULES,
        # 문서를 쓰지 않았다. 다만 어긋나는 주장은 아니므로 contradicted 가 아니다.
        expect="ignored",
    ),
    dict(
        id="gnd08", note="여러 청크를 종합해 답함",
        answer="식비는 1일 3만원, 숙박비는 1박 8만원이며 정산은 5영업일 이내입니다.",
        chunks=RULES, expect="used",
    ),
]
