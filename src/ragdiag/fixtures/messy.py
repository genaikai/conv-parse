# -*- coding: utf-8 -*-
"""지저분한 골든셋 — 실제 챗봇 로그의 모양에 가깝게.

observations.py 의 케이스는 깔끔하다. 문장이 완결되고 맞춤법이 맞고 한 문장이다. 실제
로그는 그렇지 않다 — 오탈자 · 자모 깨짐 · 띄어쓰기 없음 · 존댓말과 반말 혼용 · 영어 용어
(VPN · MFA · ERP) · 3~5문장짜리 긴 발화 · "ㅇㅇ" "넵" 같은 단답 · 표와 코드가 섞인 답변 ·
같은 질문 반복 · 사번 · 부서명 · 양식명 · 5턴 넘게 이어지는 대화. 여기 모아 둔다.

두 층을 같이 잰다.

- 관측 (expect): observations.py 와 같은 규칙. 확실한 필드만 적고, *_quote_verified 도 적을 수 있다.
- 라우팅 (expect_case): 판정이 끝났을 때 나와야 하는 case. 정답이 하나로 확정되지 않으면
  허용 집합으로 둔다.

턴 필드는 실행 로그(pseudo_input/conv-data.json 에서 본 것)를 따른다 — db_login_id ·
영문 직급 · "<user>_conv_N" 대화 id · 밀리초 시각 · A~R 라벨 이름과 alternatives.
retrieved_data 만 이쪽 파서의 계약대로 JSON 문자열로 싣는다 (그 로그에는 없던 필드다).

한계는 observations.py 와 같다. 내가 만든 데이터이므로 실데이터의 분포와 다르고,
프롬프트를 여기 맞춰 고치면 점수가 과대평가된다.
"""

import json

RULES = [
    "[출장비 규정 제4조] 국내 출장 식비는 1일 3만원을 상한으로 한다.",
    "[출장비 규정 제4조] 국내 출장 숙박비는 1박 8만원을 상한으로 한다.",
    "[출장비 규정 제7조] 출장비는 출장 종료 후 5영업일 이내에 ERP 에서 정산한다.",
]
LEAVE = [
    "[인사규정 제12조] 연차유급휴가는 사전에 그룹웨어(HR-01 휴가신청서)로 신청한다.",
    "[인사규정 제12조] 연차 사용 시 팀장의 승인을 받아야 한다. 반차도 같다.",
]
IT = [
    "[정보보호 시행세칙 제3조] 사외에서 사내망 접속은 VPN 과 MFA 인증을 거친다.",
    "[정보보호 시행세칙 제3조] MFA 는 사내 앱 OTP 또는 SMS 로 한다.",
    "[정보보호 시행세칙 제5조] 계정 잠김은 IT헬프데스크(내선 1234)에서 해제한다.",
]
CERT = [
    "[총무 안내] 재직증명서(HR-07)는 그룹웨어 > 증명서 발급에서 즉시 출력한다.",
    "[총무 안내] 경력증명서(HR-08)는 인사팀 확인 후 2영업일 내 발급한다.",
]

CASES = [
    # ---------- 오탈자 · 자모 깨짐 · 띄어쓰기 없음 ----------
    dict(
        id="typo01", note="오탈자 여럿 — 관측은 흔들리지 않아야 한다",
        pre_queries=["국내 출장 식비 상한이 얼마인가여?"],
        answer="출장 식비는 회사 규정에 따라 지급됩니다.",
        complaint="그러니까 얼마냐구요 ㅡㅡ 금액 알려주세여",
        chunks=RULES,
        expect=dict(complaint_target="content_missing", question_domain="domain",
                    question_clarity="clear"),
        expect_case={"case22", "case17"},   # 문서에 답이 있는데 답변이 안 썼다 (혹은 두루뭉술)
    ),
    dict(
        id="typo02", note="자모 깨짐 — 'ㅈ기한' 처럼 초성이 튀어 나온다",
        pre_queries=["출장비 정산 ㅈ기한이 언제에요"],
        answer="출장비는 출장 종료 후 5영업일 이내에 ERP 에서 정산하시면 됩니다.",
        complaint="넵 감사합니다",
        chunks=RULES,
        expect=dict(complaint_target="none", complaint_quote_verified=True),
        expect_case={"case0"},
    ),
    dict(
        id="nospace01", note="띄어쓰기가 하나도 없다",
        pre_queries=["국내출장숙박비상한이얼마인가요"],
        answer="국내 출장 숙박비는 1박 8만원을 상한으로 합니다.",
        complaint="식비는요",
        chunks=RULES,
        expect=dict(complaint_target="none", question_domain="domain"),
        expect_case={"case0"},
    ),
    dict(
        id="nospace02", note="띄어쓰기 없는 요구 — 인용 대조가 공백을 무시해야 한다",
        pre_queries=["출장비항목별상한을표로정리해주세요"],
        answer="국내 출장 식비는 1일 3만원, 숙박비는 1박 8만원을 상한으로 합니다.",
        complaint="표로달라니까요",
        chunks=RULES,
        expect=dict(complaint_target="format", requested_format="table",
                    request_quote_verified=True),
        expect_case={"case12"},
    ),

    # ---------- 존댓말 · 반말 혼용, 영어 용어 ----------
    dict(
        id="mix01", note="반말과 존댓말이 섞였다",
        pre_queries=["연차 며칠 남았는지 알려줘요. 그리고 반차는 어떻게 씀?"],
        answer="잔여 연차는 그룹웨어 > 근태에서 확인하실 수 있습니다. 반차는 연차와 같은 "
               "절차로 HR-01 휴가신청서를 제출하시면 됩니다.",
        complaint="ㅇㅇ 알겠음",
        chunks=LEAVE,
        expect=dict(complaint_target="none", question_multi_intent=True),
        expect_case={"case0"},
    ),
    dict(
        id="eng01", note="영어 용어 혼용 — VPN · MFA · OTP",
        pre_queries=["사외에서 VPN 붙을 때 MFA를 꼭 해야 하나요? OTP 앱이 없는데"],
        answer="네, 사외에서 사내망 접속은 VPN 과 MFA 인증을 거쳐야 합니다. MFA 는 사내 앱 "
               "OTP 또는 SMS 로 하실 수 있습니다.",
        complaint="SMS로 되는 거였군요 감사합니다!",
        chunks=IT,
        expect=dict(complaint_target="none", question_domain="domain"),
        expect_case={"case0"},
    ),
    dict(
        id="eng02", note="영어 용어에 대한 내용 불만 — 문서에 답이 있다",
        pre_queries=["ERP 계정이 잠겼는데 어디에 풀어달라고 하나요"],
        answer="계정 잠김은 보안 정책에 따라 처리됩니다. 담당 부서에 문의해 주세요.",
        complaint="담당 부서가 어디냐고요. 내선 번호 주세요.",
        chunks=IT,
        expect=dict(complaint_target="content_missing", answer_refused=False,
                    answer_actionable=False),
        expect_case={"case22", "case17"},
    ),
    dict(
        id="eng03", note="영어 문장으로 묻고 한국어 답을 받았다 — 언어 요구가 명시되진 않았다",
        pre_queries=["How do I apply for annual leave?"],
        answer="연차유급휴가는 그룹웨어의 HR-01 휴가신청서로 신청하시면 됩니다.",
        complaint="Sorry, in English please.",
        chunks=LEAVE,
        # 요구는 후속 발화에서 처음 나왔다. 원래 질문이 영어였다는 것만으로 "영어로 답하라"
        # 는 요구가 있었다고 보기는 어렵다 - 어느 쪽으로 읽어도 받는다.
        expect=dict(complaint_target="language"),
        expect_case={"case10", "case13"},
    ),

    # ---------- 긴 발화 · 단답 ----------
    dict(
        id="long01", note="후속 발화가 4문장 — 불만은 셋째 문장에 있다",
        pre_queries=["출장비 정산은 어떻게 하나요?"],
        answer="출장비는 출장 종료 후 ERP 에서 정산하시면 됩니다.",
        complaint="안녕하세요. 지난주 부산 출장 다녀왔습니다. 그런데 정산 기한이 언제까지인지가 "
                  "답변에 없네요. 며칠 안에 해야 하는지 알려주시면 감사하겠습니다.",
        chunks=RULES,
        expect=dict(complaint_target="content_missing", question_domain="domain"),
        expect_case={"case22", "case17", "case13"},
    ),
    dict(
        id="long02", note="후속 발화가 길지만 불만이 아니다 — 부분 인용이 통과해야 한다",
        pre_queries=["재직증명서는 어디서 뽑나요?"],
        answer="재직증명서(HR-07)는 그룹웨어 > 증명서 발급에서 즉시 출력하실 수 있습니다.",
        complaint="아 그렇군요. 은행 제출용이라 회사 직인이 필요한데 그것도 그룹웨어에서 바로 "
                  "되는 건가요? 아니면 총무팀에 따로 가야 하나요? 급한 건 아니고 이번 주 안에만 "
                  "되면 됩니다.",
        chunks=CERT,
        expect=dict(complaint_target="none", complaint_quote_verified=True),
        expect_case={"case0"},
    ),
    dict(
        id="short01", note="단답 'ㅇㅇ' — 불만이 아니다. 인용은 발화 전체라 짧아도 통과",
        pre_queries=["반차도 팀장 승인 받아야 해?"],
        answer="네, 반차도 연차와 같이 팀장의 승인을 받아야 합니다.",
        complaint="ㅇㅇ",
        chunks=LEAVE,
        expect=dict(complaint_target="none", complaint_quote_verified=True),
        expect_case={"case0"},
    ),
    dict(
        id="short02", note="단답 '넵' 뒤에 새 질문",
        pre_queries=["연차 신청은 어디서 해요?"],
        answer="그룹웨어에서 HR-01 휴가신청서로 신청하시면 됩니다.",
        complaint="넵. 반차는요?",
        chunks=LEAVE,
        expect=dict(complaint_target="none"),
        expect_case={"case0"},
    ),
    dict(
        id="short03", note="단답이지만 불만 — '아니요'",
        pre_queries=["국내 출장 식비 상한이 얼마인가요?"],
        answer="해외 출장 식비는 미주 지역 기준 1일 80달러입니다.",
        complaint="아니요 국내요",
        chunks=RULES,
        expect=dict(complaint_target={"content_wrong", "content_missing"}),
        expect_case={"case22", "case13", "case18"},
    ),

    # ---------- 답변에 표 · 코드 · 목록 ----------
    dict(
        id="table01", note="답변이 표로 끝난다 — 잘림으로 보면 안 된다",
        pre_queries=["출장비 항목별 상한을 표로 정리해 주세요."],
        answer="항목별 상한은 다음과 같습니다.\n\n| 항목 | 상한 |\n|---|---|\n| 식비 | 1일 3만원 |\n"
               "| 숙박비 | 1박 8만원 |",
        complaint="정산 기한도 표에 넣어주세요",
        chunks=RULES,
        expect=dict(complaint_target={"none", "content_missing"}, requested_format="table"),
        expect_case={"case0", "case22", "case17", "case13"},
    ),
    dict(
        id="code01", note="답변에 SQL 코드 블록 — 문법은 멀쩡하고 불만은 내용",
        pre_queries=["ERP에서 이번 달 출장 정산 내역 뽑는 쿼리 알려줘"],
        answer="다음 쿼리를 쓰시면 됩니다.\n\n```sql\nSELECT emp_no, amount FROM trip_expense "
               "WHERE settled_at >= '2026-04-01';\n```",
        complaint="부서별로 합계도 나오게 해줘",
        chunks=[],
        expect=dict(question_domain={"code", "tool_usage"}, complaint_target={"none", "content_missing"}),
        expect_case={"case0", "case27"},
    ),
    dict(
        id="list01", note="답변이 번호 목록으로 끝난다 — 사용자는 다른 걸 묻는다",
        pre_queries=["VPN 연결 순서 알려주세요"],
        answer="1. VPN 클라이언트 실행\n2. 사번과 비밀번호 입력\n3. MFA 인증 (OTP 또는 SMS)",
        complaint="3번에서 OTP 앱 설치는 어디서 하나요",
        chunks=IT,
        # "3번에서 … 어디서 하나요" 는 목록을 받아들이고 다음을 묻는 것으로도, 목록 3번이
        # 설치 경로를 빠뜨렸다는 지적으로도 읽힌다. Haiku 는 후자로 읽었고 둘 다 틀리지 않다.
        expect=dict(complaint_target={"none", "content_missing"}, requested_format="none"),
        expect_case={"case0", "case20", "case22", "case17"},
    ),

    # ---------- 같은 질문 반복 ----------
    dict(
        id="repeat01", note="같은 질문을 그대로 두 번 — 앞 답이 부족했다는 신호",
        pre_queries=["재직증명서 발급 어떻게 하나요", "재직증명서 발급 어떻게 하나요"],
        answer="증명서 발급은 총무팀 안내를 따라 주세요.",
        complaint="재직증명서 발급 어떻게 하나요",
        chunks=CERT,
        expect=dict(complaint_target="content_missing", answer_actionable=False),
        expect_case={"case22", "case17"},
    ),
    dict(
        id="repeat02", note="같은 질문 반복이지만 이번엔 답이 맞았다 — 사용자가 수긍",
        pre_queries=["경력증명서 며칠 걸려요", "경력증명서 며칠 걸려요?"],
        answer="경력증명서(HR-08)는 인사팀 확인 후 2영업일 내 발급됩니다.",
        complaint="넵",
        chunks=CERT,
        expect=dict(complaint_target="none"),
        expect_case={"case0"},
    ),

    # ---------- 고유명사 — 사번 · 부서명 · 양식명 ----------
    dict(
        id="proper01", note="사번과 부서명이 질문에 있다 — 개인정보 정규식엔 안 걸린다",
        pre_queries=["사번 E123456 DX추진팀 김철수인데요, 제 잔여 연차 조회 가능한가요"],
        answer="개인별 잔여 연차는 그룹웨어 > 근태에서 본인이 직접 확인하실 수 있습니다.",
        complaint="여기서 바로 알려주실 순 없나요",
        chunks=LEAVE,
        expect=dict(complaint_target={"content_missing", "other"}, answer_refused=False),
        # 챗봇이 개인 잔여 연차를 조회해 줄 수 없다는 뜻이면 case2 이고, 청크에 조회 방법이
        # 없다고 보면 case20 이다 (실제로 LEAVE 에는 없다). 어느 쪽도 틀리지 않다.
        expect_case={"case2", "case20", "case22", "case13", "case17", "out_of_taxonomy"},
    ),
    dict(
        id="proper02", note="양식명으로 묻는다 — HR-07 vs HR-08",
        pre_queries=["HR-08 어디서 뽑아요?"],
        answer="HR-07 재직증명서는 그룹웨어 > 증명서 발급에서 즉시 출력하실 수 있습니다.",
        complaint="HR-08이요. 경력증명서",
        chunks=CERT,
        expect=dict(complaint_target="content_wrong", question_clarity="clear"),
        expect_case={"case22", "case13", "case18"},
    ),
    dict(
        id="proper03", note="휴대전화 번호가 질문에 — 개인정보 부가 case",
        pre_queries=["010-1234-5678 로 OTP 문자가 안 와요. MFA 어떻게 하죠"],
        answer="MFA 는 사내 앱 OTP 또는 SMS 로 하실 수 있습니다. SMS 가 안 오면 IT헬프데스크"
               "(내선 1234)에 문의해 주세요.",
        complaint="헬프데스크 내선 1234 맞나요? 감사합니다",
        chunks=IT,
        expect=dict(complaint_target="none"),
        expect_case={"case0", "unclassified"},   # pii 위반이 잡히면 case0 이 아니라 미분류로 간다
    ),

    # ---------- 5턴 넘게 이어지는 대화 ----------
    dict(
        id="deep01", note="6턴 — 앞에서 정한 조건(국내)을 4턴 뒤 답변이 어김, 창 3턴 밖",
        pre_queries=["출장비 규정 좀 볼게요", "국내 기준으로만 볼게요", "식비 상한은요?",
                     "숙박비는요?", "정산은 언제까지예요?", "식비 다시 알려주세요"],
        answer="해외 출장 식비는 미주 지역 기준 1일 80달러입니다.",
        complaint="국내라고 했잖아요",
        chunks=RULES,
        # 조건이 창(3턴) 밖이라 판정자는 못 본다. 답변이 틀린 것은 내용 불만으로 잡힌다.
        expect=dict(answer_used_history={"not_needed", "used"},
                    complaint_target={"content_wrong", "content_missing"}),
        expect_case={"case22", "case18", "case13"},
    ),
    dict(
        id="deep02", note="6턴 — 조건이 직전 턴에 있어 창 안이다. ignored 가 맞다",
        pre_queries=["출장비 규정 좀 볼게요", "식비 상한은요?", "숙박비는요?",
                     "정산은 언제까지예요?", "국내 기준으로만 볼게요", "식비 다시 알려주세요"],
        answer="해외 출장 식비는 미주 지역 기준 1일 80달러입니다.",
        complaint="국내라고 했잖아요",
        chunks=RULES,
        expect=dict(answer_used_history="ignored", history_quote_verified=True),
        expect_case={"case22", "case18", "case13", "case14"},
    ),
    dict(
        id="deep03", note="7턴 — 주제가 두 번 바뀌고 마지막은 새 질문. 불만 아님",
        pre_queries=["연차 신청 어디서 해요", "반차도요?", "재직증명서는요", "HR-07 맞죠",
                     "VPN은 어떻게 붙어요", "MFA 앱 어디서 받아요", "OTP 말고 SMS도 돼요?"],
        answer="네, MFA 는 사내 앱 OTP 또는 SMS 로 하실 수 있습니다.",
        complaint="오케이 SMS로 할게요",
        chunks=IT,
        expect=dict(complaint_target="none", question_clarity="clear"),
        expect_case={"case0"},
    ),
    dict(
        id="deep04", note="5턴 — '그거' 가 두 턴 전 주제를 가리킨다. 앞 질문으로 풀린다",
        pre_queries=["재직증명서 어디서 뽑나요", "그룹웨어 어디 메뉴요?", "경력증명서도 거기서요?",
                     "그거 며칠 걸려요"],
        answer="재직증명서는 즉시 출력됩니다.",
        complaint="경력증명서 말한 건데요",
        chunks=CERT,
        expect=dict(question_clarity={"clear", "unresolved_reference"},
                    complaint_target={"content_wrong", "content_missing"}),
        # 경력증명서를 물었는데 재직증명서로 답했다. 의도 오독(case13)이 맞지만, 판정자가
        # "답은 맞되 행동으로 이어지지 않는다" 로 읽으면 case17 이다 - 둘의 경계는 알려진
        # 한계(README)다. '그거' 를 못 풀었다고 보면 case14 도 부가로 붙는다.
        expect_case={"case22", "case13", "case17", "case18", "case20"},
    ),

    # ---------- 서비스 오류 · 잘림 — 코드가 잡아야 하는 것들 ----------
    dict(
        id="svc01", note="서비스 자원 부족 확정 문구가 줄바꿈 섞여서 온다",
        pre_queries=["연차 이월 되나요"],
        answer="서비스에 문제가 있거나,\n사용자 분들이 많아서 서버에\n부하가 걸리고 있어요. 잠시 후 다시 시도해 주세요.",
        complaint="또 이러네",
        chunks=LEAVE,
        expect=dict(),
        expect_case={"case9"},
    ),
    dict(
        id="cut01", note="답변이 문장 중간에서 끊겼다 — 사용자는 내용을 탓한다",
        pre_queries=["출장비 정산 기한 알려주세요"],
        answer="출장비는 출장 종료 후 5영업일 이내에 ERP 에서 정산하시면 되고, 증빙은",
        complaint="증빙은 뭐요? 말이 끊겼는데",
        chunks=RULES,
        expect=dict(),
        expect_case={"case8"},
    ),
]


def build() -> tuple[dict, dict]:
    """실행 로그 모양(pseudo_input)으로 조립한 conv_eval 페이로드와 케이스별 기대값."""
    from ragdiag.labels import EMOTION_LABELS, QUERY_LABELS
    from ragdiag.load import mask

    grades = ["Assistant Engineer", "Engineer", "Senior Engineer", "Staff Engineer",
              "Principal Engineer"]
    users, expected = [], {}
    for index, case in enumerate(CASES):
        history = case["pre_queries"]
        user_id = f"messy-{case['id']}"
        conv_id = f"{user_id}_conv_1"
        turns = []
        for i, question in enumerate(history):
            last = i == len(history) - 1
            turns.append({
                "turn": i + 1,
                "timestamp": f"2026-04-{(index % 28) + 1:02d} 1{i % 10}:{(index * 7) % 60:02d}:14.000",
                "user_question": question,
                "llm_response": case["answer"] if last else f"(이전 답변 {i + 1})",
                "conversation_id": conv_id,
                "retrieved_data": json.dumps(case["chunks"] if last else [], ensure_ascii=False),
                "llm_eval_result": None if i == 0 else QUERY_LABELS["E"].name,
                "llm_eval_score": None if i == 0 else 60,
                "llm_eval_score_top1": None if i == 0 else 60,
                "llm_alternatives": [] if i == 0 else [
                    {"label": "E", "name": QUERY_LABELS["E"].name, "probability": 0.7},
                    {"label": "A", "name": QUERY_LABELS["A"].name, "probability": 0.3}],
                "llm_emotion_result": None if i == 0 else EMOTION_LABELS["E"].name,
                "llm_emotion_score": None if i == 0 else 50,
                "llm_emotion_score_top1": None if i == 0 else 50,
                "llm_emotion_alternatives": [] if i == 0 else [
                    {"label": "E", "name": EMOTION_LABELS["E"].name, "probability": 1.0}],
            })
        complaint_turn = len(history) + 1
        turns.append({
            "turn": complaint_turn,
            "timestamp": f"2026-04-{(index % 28) + 1:02d} 1{complaint_turn % 10}:00:14.000",
            "user_question": case["complaint"],
            "llm_response": "(아직 답변 없음)",
            "conversation_id": conv_id,
            "retrieved_data": "[]",
            "llm_eval_result": QUERY_LABELS["K"].name,
            "llm_eval_score": 25, "llm_eval_score_top1": 25,
            "llm_alternatives": [{"label": "K", "name": QUERY_LABELS["K"].name, "probability": 0.8},
                                 {"label": "L", "name": QUERY_LABELS["L"].name, "probability": 0.2}],
            "llm_emotion_result": EMOTION_LABELS["I"].name,
            "llm_emotion_score": 0, "llm_emotion_score_top1": 0,
            "llm_emotion_alternatives": [
                {"label": "I", "name": EMOTION_LABELS["I"].name, "probability": 1.0}],
        })
        users.append({
            "user_id": user_id, "db_login_id": f"user{index:02d}.kim",
            "job_grade": grades[index % len(grades)],
            "db_dept_name": "DX추진팀" if index % 2 else "경영지원팀",
            "db_job_name": "-", "db_position_name": "-",
            "conversations": [{"conversation_id": conv_id, "turns": turns}],
        })
        expected[f"{mask(user_id)}:{conv_id}:{complaint_turn}"] = {
            "id": case["id"], "note": case["note"], "expect": case["expect"],
            "expect_case": case.get("expect_case"),
        }

    total = sum(len(u["conversations"][0]["turns"]) for u in users)
    return ({"metadata": {"total_users": len(users), "total_turns": total},
             "users": users}, expected)
