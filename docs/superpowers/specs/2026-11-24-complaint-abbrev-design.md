# ④ 불만 판정 입력 축약 — kev 500 폴백

## 의도
kev(컨텍스트 65,536 토큰)가 ④ 불만 판정 요청에 HTTP 500(OOM)을 내는 턴이 있다. 평소에는 원문을
그대로 보내고, **500 을 받았을 때만** 칸별 상한으로 입력을 줄여 한 번 더 묻는다. 축약은 이
저장소가 구현하고, 실행 환경은 설정(`llm.*` · `abbrev.*`)만 준다.

## 발동
- `Judge.decide("complaint", …)` 가 `KevHTTPError(status=500)` 을 받으면.
- 다른 코드(4xx · 503) · 다른 단계(⑤ · ⑥) · `abbrev.enabled: false` 면 그대로 올린다.
- 어느 칸도 상한을 넘지 않았으면 크기 문제가 아니다 → 원래 에러를 올린다.
- 재시도는 한 번. 두 번째 500 은 "축약 뒤에도" 메모를 붙여 올린다.

## 칸별 처방 (상한은 토큰 추정 = 글자 수 / chars_per_token)
| 칸 | 상한 | 방법 | LLM | 검증 · 폴백 |
|---|---|---|---|---|
| answer | 5000 | 머리 70% + `…(중략 N자)…` + 꼬리 30% (elide) | 없음 | — |
| followup | 3000 | 머리 50% + 꼬리 50% (elide) | 없음 | — |
| history | 1200 | ① assistant 발화를 앞 80자 + `…(답변 생략 · N자)` 로 접기 (fold) ② 여전히 넘치면 마지막 user 둘은 원문, 그 앞 user 발화를 LLM 이 요구 목록으로 요약 (summarize) | ② 만 | 요약 각 줄이 원문 user 발화와 내용어를 공유해야 한다. 실패 · LLM 없음 → 앞에서부터 버림 (drop), 그래도 넘치면 남은 발화 elide |
| question | 1200 | LLM 이 지시문(원문 발췌)과 첨부 요약으로 분리 (split) | 있음 | `instruction in question` 이어야 한다. 실패 · LLM 없음 → elide 50/50 |

history 는 `[{"role","content"}]` 모양을 유지한다.

## 기록
- 캐시: **원문 state 키**로 `{"answers": …, "abbrev": notes}` 를 쓴다. 재실행은 500 을 다시 맞지 않고 메모도 산다.
- 턴: `flags["입력 축약"] = [{"field","method","before","after"}]` (글자 수). 기본 `[]`.
- LLM 호출은 `n_calls` · `usage` 에 더한다 (2차 판정과 같은 백엔드).
- 전달본 플래그 집계 · 대시보드 열 `축약`.

## 설정 (`abbrev.*`)
enabled true · history_tokens 1200 · question_tokens 1200 · answer_tokens 5000 · followup_tokens 3000 · chars_per_token 1.2
