# 분류 체계 v3 — 묶음 라벨 · 증거 등급 중재 · 분류 모델(kev)

**상태: 구현 중 (2026-10-24 시작).** 이 문서가 설계의 유일한 출처다. 코드와 어긋나면
코드를 고치거나 이 문서를 고치되, 어느 쪽이든 커밋 메시지에 적는다.

## 왜 다시 잡았나

v2 (`case0~30`) 는 세 가지가 맞지 않았다.

1. **라벨이 너무 많고 셀이 빈다.** 30개 중 5개는 로그에 필드가 없어 원리적으로 못 내고,
   합성 46턴에서 실제로 나온 라벨은 9개였다. 경계가 흐린 쌍(1↔4 · 3↔15 · 13↔17)이 있어
   같은 사건이 실행마다 다른 번호로 갔다.
2. **새 데이터가 들어갈 자리가 없다.** 2026-10 로그는 `history_input`(모델에 실제로 들어간
   앞 턴 · 과거 문서 · 과거 도구 결과 · memory) · `tool_calls`(이름 · 인자 · 순서) ·
   라우팅 필드를 준다. "도구를 안 불렀다" · "앞 답변의 약속을 어겼다" · "memory 의 사용자
   정보를 무시했다" 는 이 데이터로 처음 볼 수 있는 실패인데 v2 에는 라벨이 없다.
3. **인상 라벨이 구체 원인을 가로챘다.** "의도와 다른 답"(case13)은 어떤 부실한 답에도
   붙일 수 있어 먼저 물으면 다른 원인을 삼킨다. if-체인 진리표는 순서가 곧 규칙이라
   라벨이 늘수록 유지가 안 된다.

v3 는 **고치는 사람으로 묶고**, 같은 묶음 안의 "무엇을 어겼나"는 라벨이 아니라 **태그**로
내리고, 주 라벨은 **증거 등급**으로 고른다. 판정 결정(범주 답)은 분류 모델 kev 에 맡기고
일반 LLM 은 문장을 만들어야 하는 자리에만 남긴다.

## 라벨

표기는 `묶음글자 + 번호` 다. 묶음 글자는 영어 머리글자이고 문서에서는 `C(context)` 처럼
괄호로 뜻을 붙인다. 코드의 식별자는 `C1` 처럼 짧은 쪽이다.

### 실패 라벨 — 실패율 분모에 들어간다

| 묶음 | 라벨 | 뜻 | 근거 | 고칠 곳 |
|---|---|---|---|---|
| **N(none)** | `N0` 정상 후속 | 후속 발화가 앞 답변을 문제 삼지 않는다 | ② 불만 종류 = none | 필터 (챗봇 아님) |
| **U(user)** | `U1` 낼 수 없는 형태 요구 | 링크 · 이미지 · 파일 등 서비스가 낼 수 없는 것을 요구 | ② | 질문 유도 · UI |
| **T(tool)** | `T1` 호출 없음 | 업무 질문인데 `tool_calls` 와 `retrieved_data` 가 모두 빔 | 코드 + ② 질문 유형 | 오케스트레이션 |
| | `T2` 결과가 질문과 무관 | 업무 도구만 불렀고 그 `outputs` 가 질문에 답하지 못함 | ③ (출처 = 업무 도구) | 도구 연동 |
| | `T3` 빈 결과에 단정 | 도구 `outputs` 가 비었는데 답변이 수치 · 사실을 단정 | 코드 + ② | 생성 프롬프트 (도구 실패 처리) |
| **D(document)** | `D1` 검색 근거에 답 없음 | 검색 도구가 가져온 청크 어디에도 요구에 답하는 것이 없음 | ③ + ⑦ | 검색기 · 문서 |
| **G(generation)** | `G1` 명시 요구 불이행 | 언어 · 길이 · 포맷 · 어조 요구를 어김 | 코드 검증기 + 요구 확인 | 생성 프롬프트 |
| | `G2` 맥락 불이행 | 앞 조건 · 앞 답변 약속 · memory 사용자 정보 · 앞 답변과 모순 | ② + ⑤ + ⑥ + 원문 대조 | 생성 프롬프트 |
| | `G3` 의도와 다른 답 | 물은 것과 다른 것을 답함. 다른 라벨에 안 걸린 내용 불만의 **잔여** | ② | 생성 프롬프트 |
| | `G4` 복합 일부만 답 | 복합 질문의 일부만 답함 | ② | 생성 프롬프트 |
| | `G5` 근거 활용 실패 | 근거가 충분했는데 안 씀 · 어긋남 · 지어낸 인용 | ④ + 코드 | 생성 프롬프트 |
| | `G6` 일반 지식 · 계산 · 코드 오류 | 문서 무관 질문의 오답 — 코드가 확인한 것만 | 코드 검증기 | 모델 |
| **S(safety)** | `S1` 정책 거절 | 정책 · 권한을 이유로 거절했고 사용자가 불만 | ② | 권한 정책 |
| | `S2` 인젝션 수행 | 문서에 심긴 지시를 답변이 수행 | 코드 | 입력 방어 |
| | `S3` 답변 정보 유출 | 질문에 없던 개인정보 패턴이 답변에 있음 | 코드 | 출력 필터 |
| **I(infra)** | `I1` 자원 부족 문구 | 서비스 확정 문구 | 코드 | 서빙 |
| | `I2` 붕괴 · 읽을 수 없음 | 반복 · 토큰 잡탕 · 내부 유출 | 코드 + ① | 모델 · 서빙 |

잔여: `unclassified` (등급 0 — 어느 후보도 확신이 없음).

### 무결성 플래그 — 분모 밖. 그 턴의 기록을 믿을 수 없다

| 플래그 | 뜻 | 근거 | 효과 |
|---|---|---|---|
| `C1` 앞 턴 누락 | 대화에 앞 턴이 있는데 `history_chat` 에 없다 | 턴 목록 ↔ history_chat ↔ carried_turn_nos | **G2 전체**를 후보에서 뺀다 |
| `C2` memory 어긋남 | memory 가 있는데 그 내용이 history_chat 어디에도 없다 | memory ↔ history_chat 어휘 겹침 | **G2[memory]** 만 뺀다 |

빠진 것이 모델이 못 본 것인지 로그/적재가 떨어뜨린 것인지는 로그만으로 못 가른다. 그래서
라벨이 아니라 플래그다. 받는 쪽은 로그 · 적재 · 맥락 관리이고 어느 쪽인지는 그쪽이 가른다.
C 가 많이 나오면 그 사이클의 G2 집계를 보류한다.

### 이벤트 — 분모 밖 카운트 + 태그

| 이벤트 | 뜻 | 근거 |
|---|---|---|
| `U2` 질문에 개인정보 | 사용자가 질문에 개인정보를 넣었다 | pii 패턴 (질문) |

사용자가 개인정보를 넣은 것과 답변이 나빴던 것은 독립 사건이다. 멈추지 않고 그 턴의
답변을 끝까지 판정한다. 받는 쪽은 입력 마스킹(UI).

### 태그 — 주 라벨에 딸린다. 집계 셀을 만들지 않는다

| 태그 | 붙는 조건 |
|---|---|
| `U3 질문 불완전` | 질문 명확성이 clear 가 아니다 |
| `되묻기 없음` | U3 인데 답변이 되묻지 않았다 (G3 와 짝) |
| `G1:언어` `G1:길이` `G1:포맷` `G1:어조` | 어느 요구를 어겼나 |
| `G2:조건` `G2:약속` `G2:memory` `G2:모순` | 어느 맥락을 어겼나 |
| `G5:안씀` `G5:어긋남` `G5:지어낸인용` `G5:과거근거` | 근거를 어떻게 잘못 썼나. 과거근거 = 답이 history_input 의 문서에만 있었다 |
| `G6:계산` `G6:코드` `G6:일반` | 무엇이 틀렸나 |
| `T:인자불일치` `T:순서` | 질문의 고유명사가 arguments 에 없음 · 의존 순서가 역순 |
| `D:출처미상` | 검색 도구 이름 목록이 없어 D1/T2 를 못 가름 |
| `복합질문` | 질문이 복합이다 (G4 가 아니어도) |
| `미검증주장` | 일반 지식 주장이 있어 대조하지 못함 |
| 코드 검증기 이름 | 위반한 검증기 전부 (`pii` `language` `format` … ) |

**주 라벨이 무엇이든 태그는 전부 붙는다.** 멈춤(I · S2 · S3)은 LLM 호출만 끊고 코드
검증기는 전 턴에 돈다.

### 집계 축 — 라벨이 아니다

질문 유형(② `question_domain`, 작업 요청 · 반도체 기술 값을 더함) · `answered_by` · `ask_on` ·
`fallback` · 부서 · 직급 · 반복 불만 횟수. 대시보드의 축이고 전달본의 분할 기준이다.

### 제외한 실패 — 로그에 정보가 없다

지연(응답 시간 없음) · 잘림(finish_reason 없음) · 컨텍스트 초과 · 구 문서(문서 개정일 없음) ·
권한 조회 실패 · 세션/인증. v2 와 같다. 목록에서 지우되 "없는 문제" 가 아니라 "이 방법으로
못 보는 문제" 라고 전달본 머리에 적는다.

## 입력 — Case 가 들고 가는 것

| 필드 | 출처 | 누가 읽나 |
|---|---|---|
| `pre_queries` | history_chat(user) → prev_question → 턴 순서. 마지막은 턴 N 질문 | ② · 요구 확인 · pii |
| `prior_answers` **신규** | history_chat(assistant), 순서대로 | ⑥ 일관성 · G2[약속] 대조 |
| `llm_ans_on_last_q` | 턴 N `llm_response` | 전부 |
| `current_query` | 턴 N+1 `user_question` | ② |
| `rag_chunks` | 청크 풀 (own + carried). **사내 훅**이 있으면 훅 | ③ ④ |
| `chunk_sources` **신규** | 청크마다 출처: `retrieved` · `tool:<name>` · `history_retrieved` · `history_tool:<name>` | D1/T2 가름 · G5[과거근거] |
| `n_fetched` | own 길이 | T1 |
| `tool_calls` **신규** | `[{turn_no, order, name, arguments}]` — 이 턴 + history_input | T1 · T2 · T3 · 태그 |
| `tool_outputs` **신규** | 이 턴 + history_input 의 outputs (풀에도 들어 있다) | T3 · 도구 수치 검증기 |
| `memory` | memory + history_input.memory | ⑤ · C2 |
| `prior_turn_nos` **신규** | 대화의 앞 턴 번호 전부 | C1 |
| `history_turn_count` **신규** | history_chat 의 user 메시지 수 | C1 |

입력은 완결된 형태로 들어온다고 가정한다 — `history_input` 에 과거 청크가 구분되어 있다.
풀을 사내 파서로 갈아끼우는 훅은 두지 않는다.

## 판정 — 단계와 호출

### 실행 주체 셋

- **코드** — 문자열 · 규칙 · 대조. 같은 입력에 같은 답.
- **kev** — 분류 모델. `POST /v1/systemone` 에 state 와 문항(noul · choice · score)을 보내
  보정된 확률을 받는다. 문장을 만들지 않는다. 설정 `kev.url` 이 없으면 **일반 LLM 이
  같은 문항에 JSON 으로 답하는 에뮬레이션**으로 떨어진다 (확률은 self-report, 실행 요약에
  "kev 에뮬레이션" 이라고 찍는다). 테스트는 스크립트형 스텁을 쓴다.
- **일반 LLM** — 텍스트를 만들어야 하는 네 자리: 질문 재구성 · 요구값 · 주장 추출 · 인용.

### 단계

```
③ 무결성 · 이벤트    C1 · C2 · U2                       코드   멈추지 않음
④ 확정 사건          I1 · I2(규칙) · S2 · S3              코드   → 끝
                     I2(읽을 수 없음)                     kev ①  → 끝
⑤ 관측               ②a 범주 11문항                       kev
                     ②b 텍스트 (resolved_question · unmet_need · 요구값 · 조건 인용)   LLM
                     요구 확인 · 조건 인용 대조           코드
⑥ 검증 (전부 돈다)   코드 검증기 11종                     코드
                     ③ 충족도 — 청크마다 "답하나"         kev    own / carried 따로
                     ⑦ 충족도 2차 (양방향)                kev
                     ④a 주장 추출                         LLM
                     ④b 주장별 판정                       kev
                     ⑤ memory 반영                        kev    memory 있을 때
                     ⑥ 답변 일관성                        kev    prior_answers 있을 때
                     인용 (모순 · 어긋남일 때만)           LLM    전달본용
⑦ 중재               후보 (등급, 순서) → 주 라벨 · 태그 · 신뢰도   코드
```

### 호출별 계약

**① 읽을 수 있나** — kev noul. state = 답변. `illegible` p ≥ 0.9 → I2 (등급 2). 코드 가드
(`_TEMPLATE` 토큰이 답변에 있으면 p 와 무관하게 I2 등급 4)는 유지.

**②a 범주 관측** — kev 11문항, state = {이전 질문들, 답변, 후속 발화}. 문서 · memory ·
앞 답변은 주지 않는다.

| 문항 id | 유형 | 선택지 |
|---|---|---|
| `complaint_target` | choice | none · tone · format · language · length · content_missing · content_wrong · no_answer · inconsistency · other |
| `question_domain` | choice | domain · general_knowledge · calculation · code · tool_usage · **task** (번역 · 작문 · 요약) · **technical** (반도체 · 공정 기술) · unclear |
| `question_clarity` | choice | clear · unresolved_reference · vague |
| `question_multi_intent` | noul | |
| `answer_refused` | noul | |
| `answer_covers_all_intents` | noul | |
| `answer_actionable` | noul | |
| `answer_ignored_history` | noul | |
| `answer_asked_back` **신규** | noul | 답변이 되물었나 |
| `requests_unsupported_output` | noul | |
| `requested_length_kind` | choice | none · max_chars · max_sentences · max_lines · vague_short |
| `requested_format` | choice | none · numbered_list · bullet_list · table · code_block · json · prose |

(12문항이다. 설계 대화의 "11" 은 되묻기를 더하기 전 수다.)

**②b 텍스트 관측** — 일반 LLM, 같은 state. 출력 `ObservationText`:
`resolved_question` · `unmet_need` · `requested_language`(ISO) · `requested_length_value` ·
`history_quote`(앞 질문들에 범위를 좁히는 조건이 있으면 그 구절, 없으면 빈 문자열).
②a 와 ②b 는 서로를 모른다. 합쳐서 `Observation` 하나가 된다.

**요구 확인** (코드, 기존 `requests.py`) — ②a 가 말한 포맷/언어/길이 요구가 이전 질문들에
어휘로 있는지. 없으면 요구를 지운다. **조건 인용 대조** (코드, 기존 `verify_history_quote`) —
②b 의 `history_quote` 가 마지막 질문보다 앞의 질문들에 있는지.

**③ 충족도** — kev noul, 청크마다 한 문항. state = {질문: resolved_question, 청크}.
문항: "이 청크가 질문에 답하는 내용을 담고 있나". own 청크들과 carried 청크들을 따로 돈다.
내용 불만(content_missing · content_wrong)이면 unmet_need 로 한 번 더 돈다.
코드가 집계한다:

```
p_i ≥ 0.8  →  그 청크는 근거 (evidence)
verdict:  근거 있음 → sufficient · 근거 없고 max p ≥ 0.5 → partial · 그 외 insufficient
```

인용 대조가 없어진다. 근거는 청크 인덱스다.

**⑦ 충족도 2차** — kev noul, 다른 문항으로 되묻는다.
불충분이면 state = {요구, 청크 전부}, 문항 "요구에 답하는 내용이 이 중 어디에도 없나" (yes 면 일치).
충분이면 근거 청크마다 "이 청크만으로 요구에 답할 수 있나" (yes 면 일치).
일치 → D1 / G5 등급 3. 불일치 → 등급 2 로 내리고 `2차불일치` 태그.

**④a 주장 추출** — 일반 LLM. state = 답변. 출력 `Claims`: `[{text, expected_source}]`,
expected_source ∈ doc · tool · general. 숫자 · 날짜 · 조건이 들어간 문장을 주장으로 뽑는다.
**④b 주장별 판정** — kev choice, 주장마다 state = {주장, 근거 청크들(③ 에서 p ≥ 0.5 인 것, 없으면
전부)}, 선택지 supported · contradicted · not_found. doc 주장만 묻는다. tool 주장은 코드
수치 대조로 넘기고 general 주장은 `미검증주장` 태그.

**⑤ memory 반영** — kev choice, state = {memory, 답변}, 선택지 reflected · ignored · contradicted.
memory 가 비어 있지 않을 때만. C2 플래그면 묻지 않는다.

**⑥ 답변 일관성** — kev noul, 앞 답변마다 state = {앞 답변, 이 답변}, 문항 "두 답변이 같은
것에 대해 서로 다른 사실을 말하나". prior_answers 가 있을 때만.

**인용 (조건부)** — 일반 LLM. ④b contradicted · ⑤ contradicted · ⑥ yes 인 쌍에 대해
"어긋나는 두 구절을 글자 그대로" 받아 코드가 원문 대조. 전달본에만 쓴다. 실패해도 판정은
안 바뀐다.

### 코드 검증기 11종

기존 10종(pii · quoted_spans · python_syntax · sql_shape · arithmetic · dates · injection ·
language · format · length)에 **`tool_numbers`** 를 더한다 — 답변의 숫자 · 식별자(영숫자 코드)
중 도구 outputs 에 없는 것. tool_outputs 가 있을 때만 적용. 전 턴에 돈다.

### 후보와 중재

각 단계는 **후보**를 낸다: `Candidate(label, grade, order, reason, tags)`.

```
등급 4  코드 확정      I1 · I2(규칙 · 템플릿 토큰) · S2 · S3 · T1 · T3 · G1(검증기 violated) · G6 · tool_numbers
등급 3  근거 확정      D1 · T2 (⑦ 일치) · G5[어긋남] (④b contradicted) · G2 (조건 인용 대조 통과) · S1
등급 2  확신 p ≥ 0.9   U1 · G4 · G5[안씀] · N0 · I2(①) · G2 (대조 없이 p 만) · D1 (⑦ 불일치) · S1 (p 만)
등급 1  0.6 ≤ p < 0.9  G3 — 이것뿐이면 신뢰도 low. 다른 등급 1 후보도 여기
등급 0                 unclassified
```

주 라벨 = 등급 최대, 같으면 `order` 최소. `order` 는 라벨 순서표(아래)다. 나머지 후보는
태그로 내려간다(`라벨:세부` 꼴). 신뢰도 = 주 라벨의 등급 (4·3 → high, 2 → medium, 1 → low).

라벨 순서 (같은 등급에서 앞이 이긴다):
`I1 I2 S2 S3 N0 S1 U1 T1 T3 D1 T2 G1 G5 G6 G4 G2 G3`

N0 가 S1 보다 앞인 이유: 불만 없는 거절은 정당한 거절이다. S2 · S3 가 N0 보다 앞인 이유:
불만과 무관한 사건이다. G3 가 맨 뒤인 이유: 잔여 라벨이라 구조적으로 아무것도 삼키지 못하게.

후보 생성 규칙 (전부 코드):

| 후보 | 조건 |
|---|---|
| I1 | service_error 규칙 |
| I2 | degenerate 규칙 (4) · ① p≥0.9 (2) |
| S2 | injection violated |
| S3 | answer_pii violated (답변 PII − 질문 PII) |
| N0 | complaint_target = none, p 로 등급 |
| S1 | answer_refused ∧ complaint ≠ none |
| U1 | requests_unsupported_output |
| T1 | question_domain ∈ {domain, technical} ∧ 내용 불만 ∧ tool_calls 비어 있음 ∧ n_fetched = 0 |
| T3 | tool_calls 있음 ∧ outputs 전부 빔/0건 ∧ 답변에 숫자 · 단정 (tool_numbers 가 "outputs 없음에 수치" 를 낸다) |
| D1 | 내용 불만 ∧ verdict ≠ sufficient ∧ (출처에 검색 있음 ∨ 출처 미상) |
| T2 | 내용 불만 ∧ verdict ≠ sufficient ∧ 출처가 업무 도구만 |
| G1 | 검증기 violated (4) · 요구 있고 undetermined ∧ 불만이 그 요구 (2) |
| G5 | verdict = sufficient ∧ (④b contradicted (3) ∨ 근거 주장 없음 (2) ∨ quoted_spans violated (4→태그)) |
| G6 | question_domain ∉ {domain, technical} ∧ (arithmetic · dates · python_syntax · sql_shape violated) |
| G4 | question_multi_intent ∧ ¬answer_covers_all_intents |
| G2 | ¬C1 ∧ (answer_ignored_history ∧ 조건 인용 통과 (3) / p 만 (2)) ∨ ⑤ ignored·contradicted (¬C2) ∨ ⑥ yes |
| G3 | 내용 불만 ∧ 다른 G·D·T 후보 없음 — 등급 1 |

## 설정

```yaml
kev:
  url: null            # http://<서버>:8009   없으면 일반 LLM 에뮬레이션
  key: null
  model: kev-latest
  timeout_sec: 120
thresholds:
  kev_confident: 0.9   # 등급 2 하한
  kev_lean: 0.6        # 등급 1 하한
  chunk_evidence: 0.8  # ③ 청크가 근거로 서는 p
  chunk_partial: 0.5
tools:
  search_names: []     # 검색 도구 이름. 비어 있으면 D1/T2 를 가르지 않는다
```

## 출력

결과 JSON 의 `classification` 키는 그대로 두고 **값**이 바뀐다.

```json
"classification": {
  "case_id": "G5",  "case_name": "근거 활용 실패",
  "type_id": "G",   "type_name": "생성",  "category": "generation",
  "owner": "생성 프롬프트",
  "confidence": "high",  "grade": 3,
  "reason": "…",
  "tags": ["G5:어긋남", "복합질문", "format"],
  "secondary_cases": [...],        // 태그 중 라벨 꼴인 것의 describe — 대시보드 호환
  "flags": ["C2"],  "events": ["U2"],
  "candidates": [{"label": "G5", "grade": 3, "reason": "…"}, …],
  "probabilities": {"complaint_target": {"content_wrong": 0.91, …}, …},
  "evidence": { … 관측 · 충족도(청크 인덱스 · p) · 주장 · memory · 일관성 · 검증기 … },
  "llm_calls": 7, "kev_calls": 23
}
```

실행 요약에 `무결성 N건 · 이벤트 N건 · kev 호출 N · kev 에뮬레이션 여부` 가 더 찍힌다.
전달본은 묶음 → 라벨 → 태그 → 사례이고 무결성 · 이벤트는 별도 표다.

## v2 → v3 대응 (옛 결과 파일을 읽을 때)

```
case0→N0  case1·4→(U3 태그)  case2→U1  case3→(복합질문 태그)  case6→U2
case9→I1  case30→I2  case10·11·12·16→G1  case13·17→G3  case14→G2  case15→G4
case18·22·24→G5  case20→D1  case21→T1  case25·26·27→G6  case28→S1  case29→S2
case5·7·8·19·23→(제외)
```

## 바뀌는 코드

| 자리 | 변경 |
|---|---|
| `taxonomy.py` | v3 표 · 묶음 · 등급 · 순서 · 태그 레지스트리 · v2 대응 |
| `schema.py` | `Case` 필드 추가 · `ObservationText` · `Claims` · kev 문항 정의 |
| `conv.py` | assistant 보존 · tool_calls 파싱 · chunk_sources · 훅 |
| `decide.py` **신규** | kev HTTP 클라이언트 · LLM 에뮬레이션 · 캐시 |
| `judge.py` | `decide()` 추가 · 단계 이름 확장 |
| `results.py` | `Candidate` · flags · events · probabilities · 단계 결과 필드 |
| `features/integrity` **신규** | C1 · C2 · U2 |
| `features/short_circuit` | S2 · S3 규칙 추가 |
| `features/legibility` | kev 로 |
| `features/observe` | ②a kev + ②b LLM |
| `features/sufficiency` | 청크 단위 kev · own/carried · ⑦ |
| `features/claims` **신규** | ④a + ④b (grounding 대체) |
| `features/memory_check` **신규** | ⑤ |
| `features/consistency` **신규** | ⑥ |
| `features/tool_numbers` **신규** | 검증기 |
| `features/arbitrate` **신규** | route 대체 |
| `output.py` · `summary` · `handover` · `dashboard.py` | v3 값 · 태그 · 플래그 · 이벤트 |
| `config.py` · `settings.py` · `env.example.yaml` | kev · thresholds · tools |
| 테스트 | 라우팅 → 중재 · 스냅숏 재생성 · v3 합성 테스트셋 |

지우는 것: `features/route` · `features/citation` · `features/grounding` ·
`features/complaint_quote` (quote 요구가 없어졌다) · `features/request_quote` 는 요구 확인으로
남는다 · `features/history_quote` 는 ②b 의 조건 인용 대조로 남는다.

## 테스트셋

`src/ragdiag/fixtures/v3_cases.py` — 라벨 · 플래그 · 이벤트 · 태그마다 최소 2건, kev 스텁이
낼 답과 LLM 스텁이 낼 텍스트를 케이스 안에 적어 둔다. `tests/test_v3_pipeline.py` 가 전부
돌려 주 라벨 · 태그 · 등급 · 플래그가 기대와 같은지 본다. 중재는 `tests/test_arbitrate.py`
가 후보 조합으로 전 경로를 덮는다.

## 정한 것 (대화에서) 과 내가 정한 것

대화에서: 묶음 글자 표기 · 도구가 검색을 포함하는 상위 개념 · 도구 이름으로 결과를 추측하지
않음 · C 는 플래그 · U2 는 이벤트 · S1 은 N0 뒤 · 정확성 우선 (분기 없이 전부 돌림) · kev 가
판정 결정 전부 · 일반 LLM 은 텍스트만.

내가 정한 것 (바꿔도 된다): 등급 임계값 0.9 / 0.6 / 0.8 / 0.5 · 되묻기 문항 추가 · 질문 유형에
task · technical 추가 · 결과 JSON 키 이름 유지(값만 v3) · kev 없을 때 LLM 에뮬레이션 ·
D1/T2 가를 때 검색 결과가 하나라도 있으면 D1.
