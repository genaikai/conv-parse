# 사내에서 채워야 하는 것 — 청크 전처리 함수를 중심으로

이 저장소는 사외에서 로그 **예시 몇 건**으로 만들었다. 로그의 실제 모양을 아는 코드는 사내에
있다. 그 코드를 붙이는 자리는 이미 뚫려 있고, 사내에서 할 일은 **함수 본체 하나와 설정 네 줄**이다.
이 문서는 그 자리가 코드의 어디인지, 함수가 무엇을 지켜야 하는지, 붙인 뒤 무엇을 확인하는지를
적는다. 설계 배경은 `docs/design/chunk_pool_hook.md`.

## 1. 청크 전처리 함수 — 들어갈 자리

파이프라인은 네 질문(README "처리 흐름")으로 돈다. 그중 ⑶ "근거가 있었나 · 모델이 썼나" 가
읽는 것이 **청크 풀**(`Case.rag_chunks`)이다. 풀이 하나 비면 D1(검색 실패)이 늘고, 하나 더 들어가면
G5(있는데 안 씀)로 옮겨 간다 — 고칠 곳이 문서팀과 생성 쪽으로 정반대다. 그래서 풀을 만드는 자리가
사내 함수로 갈아끼워진다.

```
로그 JSON (turns[])
   │
   ▼
conv._parse_turn ──▶ Turn.raw  (레코드 dict 그대로 보존)                src/ragdiag/conv.py:364
   │
   ▼
conv.to_case                                                           src/ragdiag/conv.py:487
   │   hook = settings.CHUNK_POOL_HOOK                                  src/ragdiag/conv.py:528
   │   ├─ None  → 내장 chunk_pool_with_sources(answered, scope)        src/ragdiag/conv.py:670
   │   └─ 있음  → own, carried = _call_hook(hook, answered, prior)     src/ragdiag/conv.py:566
   │               rag_chunks = own + carried · n_fetched = len(own)
   ▼
Case ──▶ features/ (⑴~⑷)     ← 여기부터는 Case 만 본다. 훅이 있었는지 모른다
```

설정과 import:

| 무엇 | 어디 |
|---|---|
| 설정 키 | `hooks.chunk_pool: "<모듈>:<함수>"` — `configs/env.yaml` (예시는 `configs/env.example.yaml:199`) |
| import 시점 | `config._install_hook` (`src/ragdiag/config.py:543`). 설정 적용 때 import 하고 못 찾으면 계산 전에 `ConfigError` |
| 전역 | `settings.CHUNK_POOL_HOOK` (`src/ragdiag/settings.py:153`). callable 또는 None |
| 모듈 탐색 | `sys.path` + 작업 폴더. 공용 venv 의 패키지 이름이거나, 작업 폴더에 둔 파일 하나(`파일명:함수`) |

## 2. 함수 계약

```python
def chunk_pool(turn: dict, prior: list[dict]) -> tuple[list[str], list[str]]:
    """비판받은 답변이 볼 수 있었던 문서를 (이 턴 것, 과거 것) 으로 가른다.

    turn   비판받은 답변의 턴 레코드. 로그 JSON 의 turns[] 원소 그대로.
           retrieved_data · tool_output · history_input · memory 가 이 안에 있다.
    prior  같은 대화의 앞선 턴 레코드들, 턴 번호 오름차순. history_input 이 있으면
           볼 일이 없다 — 옛 로그 폴백 · 교차 검증용.

    반환   own      이 턴이 이번에 가져온 청크 (retrieved_data + tool_output). 로그 순서.
                    len(own) 이 n_fetched 가 되고, 0 이면 T1(도구 안 부름) 후보가 선다.
           carried  답변을 만들 때 모델이 들고 있던 과거 청크
                    (history_input 의 retrieved_data + tool_output 의 outputs).
    """
```

**지켜야 하는 것** — 어기면 라벨이 조용히 옮겨 간다.

| 규칙 | 어기면 |
|---|---|
| 문자열을 바꾸지 않는다 (머리말 · 출처 표기 · 공백 정리 · 요약 금지) | 인용 대조가 글자 그대로 연속 일치라 맞는 인용이 떨어지고 `G5:지어낸인용` 으로 집계 |
| `tool_calls`(호출 인자)는 넣지 않는다. `outputs` 만 | 충족도가 "인자" 를 문서로 읽어 sufficient 가 후해진다 |
| 같은 청크를 두 번 넣지 않는다 · 빈 문자열을 넣지 않는다 | 청크 인덱스가 밀려 `index_corrected` 가 늘고 그 지표를 못 믿는다 (빈 문자열은 `_call_hook` 이 걸러 주지만 중복은 안 거른다) |
| `turn` 을 수정하지 않는다 | 같은 dict 가 다음 턴의 `prior` 로 다시 들어간다 |
| 예외는 그대로 던진다. 잡아서 `([], [])` 를 돌려주지 않는다 | 파싱 실패가 "검색을 안 했다"(T1, 등급 4)로 둔갑한다. 최악의 결과다 |

**우리 쪽이 보장하는 것**: 턴마다 한 번, 필터 통과 턴만 부른다. 반환 모양(길이 2, 각각 `list[str]`)을
검증하고 틀리면 `conversation_id:turn` 을 찍고 그 자리에서 죽는다. 캐시는 신경 쓰지 않아도 된다 —
판정 캐시 키가 프롬프트 본문 해시라 풀이 달라지면 저절로 빗나간다.

## 3. 붙인 뒤 확인하는 순서

1. **같은 로그로 훅 없이 한 번, 켜고 한 번** 돌린다. 결과 파일의 턴별 `chunk_data` 길이를 비교한다.
   다른 턴이 두 파서의 차이다. 전부 같으면 훅이 하는 일이 없고, 전부 다르면 둘 중 하나가 틀렸다.
2. 차이 난 턴에서 `evidence.sufficiency` 의 verdict 가 바뀌었는지 본다. insufficient → sufficient 로
   옮긴 턴이 "내장 파서가 놓치던 청크" 다.
3. 라벨 분포에서 **D1 ↔ G5** 가 움직였으면 그 이유를 `docs/insights/` 에 남긴다. 이 둘의 이동이
   풀 경계의 차이를 그대로 보여 준다.
4. `summary.txt` 의 `failed at` 에 `[conv]` 나 훅 이름이 찍히면 반환 모양 위반이다.

## 4. 알려진 한계 — 사내에서 결정해야 한다

**훅을 켜면 청크 출처가 전부 `hook` 이 된다.** 내장 경로는 청크마다 `retrieved · tool:<name> ·
history_retrieved · history_tool:<name>` 을 남기는데(`chunk_sources`), 훅 계약은 문자열만 돌려주므로
그 정보가 없다. 그 결과:

| 영향받는 것 | 내장 경로 | 훅 경로 |
|---|---|---|
| own / carried 가르기 (G5:과거근거, 충족도 scope) | 출처로 가른다 | `n_fetched` 로 가른다 — **정상 동작** (`features/sufficiency/__init__.py:55`) |
| D1 vs T2 (검색 실패 vs 엉뚱한 업무 도구) | 출처 이름과 `tools.search_names` 로 가른다 | **항상 D1**. T2 가 나오지 않는다 |
| `D:출처미상` 태그 | search_names 가 비었을 때만 | 같음 |

T2 가 필요하면 계약을 넓혀야 한다. 제안: own · carried 원소를 `str` 또는 `(str, source)` 로 받고,
source 는 `retrieved` · `tool:<도구이름>` 중 하나. 받는 쪽(`_call_hook`)이 문자열이면 `hook` 으로,
튜플이면 그 출처로 채우면 되고 `features/` 는 손댈 것이 없다. **T2 를 집계에 쓸 것인지가 먼저
정해져야** 이 확장을 한다 — 업무 도구가 검색기와 별개로 있는 서비스인지가 사내에서만 보인다.

## 5. 함께 채워야 하는 나머지

청크 전처리 말고도 사외에서 비워 둔 것이다. 전부 `configs/env.yaml` 과 로그 쪽이고 코드 변경은 없다.

| 항목 | 어디에 | 없으면 |
|---|---|---|
| kev 서버 | `kev.url` (`kev.key`, `kev.model`) | 일반 LLM 이 같은 문항에 답하는 에뮬레이션. 확률이 보정 안 됐다고 요약에 찍힌다. 등급 2 · 1 의 경계(`thresholds.kev_confident` 0.9 · `kev_lean` 0.6)가 뜻을 잃는다 |
| 검색 도구 이름 | `tools.search_names` | D1 과 T2 를 가르지 않고 `D:출처미상` 태그로 합친다 |
| 턴 단위 `tool_calls` | 로그 레코드 (`contracts.py` 에 선택 필드) | T1 이 `n_fetched == 0` 만으로 선다. `T:인자불일치` 태그 · T3(빈 결과 단정) 이 안 나온다 |
| 임계값 측정 | `thresholds.kev_confident` 0.9 · `kev_lean` 0.6 · `chunk_evidence` 0.8 · `chunk_partial` 0.5 | 사외에서 정한 기본값 그대로. 실제 로그 표본으로 등급 2 와 1 의 오분류율을 재서 조정 |
| I1 확정 문구 | `service_error.templates` | 배포마다 다르다. 운영 실값이 없으면 I1 이 S1(정책 거절)로 샌다 |

## 6. 사외 쪽에 남은 것 (이 저장소 안)

- **훅 경로의 테스트가 없다.** `docs/design/chunk_pool_hook.md` 가 적어 둔 표(훅이 받는 것 · 풀 순서 ·
  `n_fetched` · 반환 모양 오류 · 설정 경로 오류)가 `tests/test_history_input.py` 에 아직 없다.
  사내 함수를 붙이기 전에 스텁 훅으로 먼저 채우는 것이 맞다.
- dry-run 이 훅 이름을 찍지 않는다. 설계는 "풀이 어느 파서 것인지 결과만 보고 알 수 있어야 한다"
  였다. `summary.txt` 머리에 `hooks.chunk_pool` 값을 한 줄 넣으면 된다.
- 4절의 출처 확장은 결정이 나면 `_call_hook` 과 `to_case` 두 함수만 바뀐다.
