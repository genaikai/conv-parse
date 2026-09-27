# 설계 기록 — 무엇을 재고 왜 그렇게 정했나

여기 있는 문서는 **결정문이 아니라 측정 기록**이다. 어느 것도 "이렇게 하는 게 맞다"로
시작하지 않는다. 가설을 세우고, 골든셋으로 재고, 수치를 보고 정한 뒤, **되돌린 것까지
남긴다.** 되돌린 실험을 지우면 다음 사람이 같은 것을 다시 해 본다.

방식은 어느 문서나 같다.

```
약한 모델을 기준으로 가설을 세운다     강한 모델에서만 되는 것은 실행 환경에서 무너진다
    ↓
골든셋으로 잰다 (같은 조건 3회)        1회 차이는 잡음과 가를 수 없다
    ↓
코드 결함만 고친다                     프롬프트로 부탁한 것은 모델이 바뀌면 무너진다
    ↓
수치와 함께 남긴다 — 되돌린 것도
```

## 판정 단계별

| 문서 | 단계 | 무엇을 정했나 |
|---|---|---|
| [observe_step.md](observe_step.md) | ⑤ Step 1 관측 | 19개 관측을 LLM 한 번에 묻는다. 쪼개면 호출이 두 배인데 정확도는 안 오르고, 불만을 감추면 모호함을 놓친다 |
| [sufficiency_step.md](sufficiency_step.md) | ⑦ Step 2 충족도 · ⑧ 인용 대조 | 답변을 감춘다. 요구 부풀림은 프롬프트가 아니라 코드로 좁힌다(`narrow_need`) |
| [grounding_step.md](grounding_step.md) | ⑨ Step 3 근거 활용 | 질문은 준다 — 감추면 "아무 청크나 썼는가"가 되어 case22 가 15건 중 13건 샜다 |
| [legibility_step.md](legibility_step.md) | ④′ 읽기 | 답변만 보고 "사람이 읽고 뜻을 잡을 수 있는가" 하나만 묻는다 |
| [request_check.md](request_check.md) | 요구 확인 | 판정자에게 증거를 요구하던 것을 **코드가 확인하는 쪽으로** 바꿨다. 약한 모델이 인용을 안 베껴 맞는 요구가 지워지고 있었다 |

## 구조

| 문서 | 내용 |
|---|---|
| [features_pipeline.md](features_pipeline.md) | 판정 순서를 코드에서 빼내 `features/` 등록부로 옮긴 설계 |
| [features_pipeline_plan.md](features_pipeline_plan.md) | 그 구현 계획 (완료) |

두 문서는 **그 변경 시점의 기록**이다. 지금의 기능 목록과 순서는
`src/ragdiag/features/__init__.py` 의 `FEATURES` 가 유일한 출처다 — 그 뒤로
읽기(`legibility`) · 요구 확인(`request_quote` · `history_quote`) · 전달본(`handover`)이
더해졌다.

## 읽는 순서

처음이면 [../process_flow.md](../process_flow.md) 를 먼저 본다. 여기 문서들은
"왜 그 단계가 그 입력을 받는가"의 근거이지 단계 설명이 아니다.

## 여기에 남기지 않는 것

사이클 한 번의 결과는 [../insights/TEMPLATE.md](../insights/TEMPLATE.md) 를 채워
`docs/insights/` 에 쌓는다. 이 폴더는 **설계가 바뀐 이유**만 담는다.
