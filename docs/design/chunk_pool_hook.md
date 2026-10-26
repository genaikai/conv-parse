# 청크 풀을 사내 함수로 — `rag_chunks` · `n_fetched` 를 밖에서 받는다

**상태: 구현됨 (2026-10-24, v3 와 함께).** 훅 자리는 `conv.to_case` → `_call_hook`, 설정은
`hooks.chunk_pool`, import 는 `config._install_hook` 이다. 사내 쪽에 남은 일은 **함수 본체**다 —
아래 계약대로 `(turn, prior) -> (own, carried)` 를 만들고 설정에 `모듈:함수` 를 적는다.

## 왜

`conv.chunk_pool` 은 턴 레코드의 네 자리(`retrieved_data` · `tool_output` ·
`history_input.retrieved_data` · `history_input.tool_output`)를 더해 **비판받은 답변이
볼 수 있었던 문서 전부**를 만든다. 이 로직은 로그의 실제 모양에 기댄다 - JSON 을 담은
문자열, 이스케이프가 깨진 통문자열, 호출 단위로 묶인 도구 결과 구조체. 사외에서는 그
모양을 **예시 몇 건으로 추정**해 왔고, 사내에는 같은 로그를 이미 파싱하는 함수가 있다.

같은 로그를 두 군데서 다르게 파싱하면 어긋난 쪽이 조용히 틀린다. 청크가 하나 빠지면
"문서에 없었다"(case20)가 늘고, 하나 더 들어가면 "있었는데 안 썼다"(case22)로 옮겨 간다 -
**고칠 곳이 문서팀과 생성 쪽으로 정반대다.** 그래서 풀을 만드는 자리를 사내 함수로
갈아끼울 수 있게 한다.

`n_fetched`(이 턴이 **이번에** 가져온 청크 수)도 같은 함수가 낸다. 풀과 따로 세면
"풀에는 있는데 이번 검색은 0건" 같은 모순이 생길 수 있고, 그 값 하나가 case21(Retrieve
미수행)을 가른다.

## 무엇을 바꾸고 무엇을 안 바꾸나

| | 지금 | 바뀐 뒤 |
|---|---|---|
| `rag_chunks` | `conv.chunk_pool(answered, scope)` | 훅이 있으면 훅, 없으면 지금 그대로 |
| `n_fetched` | `len(answered.retrieved) + len(answered.tool_output)` | 훅이 있으면 훅의 `own` 길이, 없으면 지금 그대로 |
| `pre_queries` · `memory` · `current_query` · `llm_ans_on_last_q` | `conv.to_case` | **안 바뀐다** |
| `features/` 전체 | `Case` 만 본다 | **안 바뀐다** - 경계는 `Case` 다 (tests/test_boundary.py) |

훅은 **입력 계층(`conv.py`)의 일**이다. 코어는 `Case` 가 어떻게 만들어졌는지 모른다.

## 계약

사내 쪽이 제공하는 것은 **함수 하나**다.

```python
def chunk_pool(turn: dict, prior: list[dict]) -> tuple[list[str], list[str]]:
    """비판받은 답변이 볼 수 있었던 문서를 (이 턴 것, 과거 것) 으로 가른다.

    turn   비판받은 답변의 턴 레코드. 로그 JSON 의 turns[] 원소 **그대로** (dict).
           retrieved_data · tool_output · history_input · memory 가 전부 이 안에 있다.
    prior  같은 대화에서 그보다 앞선 턴 레코드들, 턴 번호 오름차순. history_input 이
           있는 로그에서는 볼 일이 없다 - 옛 로그 폴백과 교차 검증용으로만 준다.

    반환   (own, carried)
           own      이 턴이 **이번에** 가져온 청크. retrieved_data 와 tool_output.
                    순서는 로그 순서 그대로. len(own) 이 n_fetched 가 된다.
           carried  그 답변을 만들 때 모델이 들고 있던 **과거** 청크.
                    history_input 의 retrieved_data 와 tool_output outputs.
    """
```

왜 `(chunks, n_fetched)` 가 아니라 `(own, carried)` 인가: 풀의 순서("이 턴 것이 먼저")와
`n_fetched == len(own)` 을 **우리 쪽에서** 강제하기 위해서다. 둘을 따로 받으면 두 값이
어긋날 수 있고, 어긋나면 case21 이 틀린다. 합치는 것은 `to_case` 가 한다:

```python
own, carried = hook(raw_turn, raw_prior)
rag_chunks = own + carried
n_fetched = len(own)
```

### 훅이 지켜야 하는 것

- **문자열을 바꾸지 않는다.** 머리말(`[turn 2]`) · 출처 표기 · 공백 정리 · 요약 금지.
  ⑧ 인용 대조는 판정자의 인용을 청크와 **글자 그대로 연속 일치**로 대조한다
  (`thresholds.match_threshold` 0.9). 로그에 없던 글자가 끼면 맞는 인용이 떨어지고,
  판정자가 지어낸 인용으로 집계된다 (case24).
- **`tool_calls` 는 넣지 않는다.** 무엇을 물었는지지 무엇이 나왔는지가 아니다. 충족도 ⑦ 은
  "문서에 답이 있었나"를 묻는데 호출 인자는 답이 아니다. `outputs` 만 넣는다.
- **같은 청크를 두 번 넣지 않는다.** 중복은 인용 대조에서 `index_corrected`(판정자가 적은
  인덱스와 실제 일치 인덱스가 다름)를 양산해 그 지표를 못 믿게 만든다.
- **빈 문자열은 넣지 않는다.** 빈 청크는 인덱스만 밀어 역시 `index_corrected` 를 만든다.
- **`turn` 을 수정하지 않는다.** 같은 dict 가 다른 턴의 `prior` 로 다시 들어간다.
- **예외는 그대로 던진다.** 잡아서 빈 풀을 돌려주면 그 턴이 case21(Retrieve 미수행)로
  집계된다. 파싱 실패가 "검색을 안 했다"로 둔갑하는 것이 가장 나쁜 결과다.

### 우리 쪽이 보장하는 것

- 훅은 **턴마다 한 번**, `to_case` 안에서만 불린다. 필터를 통과한 턴만이다.
- 반환값을 검증한다: 길이 2 의 tuple/list, 각 원소는 `list[str]`. 아니면 턴을 건너뛰지
  않고 **그 자리에서 죽는다** - 훅 이름과 `conversation_id:turn` 을 찍는다.
- 캐시는 신경 쓰지 않아도 된다. LLM 판정 캐시 키는 프롬프트 본문의 해시라
  (`judge._cache_path`), 풀이 달라지면 저절로 캐시가 빗나간다.

## 설정

```yaml
# configs/env.yaml
hooks:
  chunk_pool: null        # 예: ragdiag_inhouse.parse:chunk_pool
                          # "<모듈>:<함수>". null 이면 내장 conv.chunk_pool
```

| 키 | 타입 | 기본 |
|---|---|---|
| `hooks.chunk_pool` | str, 선택 | null |

- 모듈은 실행 위치 기준 `sys.path` 에서 찾는다. 사내 패키지가 공용 venv 에 있으면 그
  이름을 적고, 파일 하나면 작업 폴더에 두고 `파일명:함수` 로 적는다.
- **설정 적용 시점(`config.apply`)에 import 한다.** 함수를 못 찾으면 계산을 시작하기 전에
  `ConfigError` 로 죽는다. 30분 돌고 나서 첫 턴에서 죽는 것과, 조용히 내장으로 떨어져
  "왜 풀이 안 바뀌지"를 찾는 것 - 둘 다 이 저장소가 피하려는 결과다.
- `settings.CHUNK_POOL_HOOK` 에 **callable 또는 None** 으로 둔다. `conv.to_case` 가 그걸
  본다. 다른 settings 값처럼 전역이고 실행 중 바뀌지 않는다.

## 구현 순서

코드 변경은 네 파일이다. 전부 입력 계층이다.

1. **`conv.py` — `Turn` 에 원본을 남긴다.**
   `raw: dict = field(default_factory=dict, repr=False, compare=False)`. `_parse_turn` 이
   `raw=raw` 로 채운다. 훅에 넘길 것은 우리가 파싱한 `Turn` 이 아니라 **로그 레코드
   그대로**여야 한다 - 사내 파서는 그 모양을 알고 우리 파싱은 모른다. frozen dataclass
   에 dict 를 두는 것은 괜찮다 (해시를 안 쓴다).

2. **`conv.py` — `to_case` 가 훅을 본다.**
   ```python
   hook = settings.CHUNK_POOL_HOOK
   if hook is None:
       rag_chunks = chunk_pool(answered, scope)
       n_fetched = len(answered.retrieved) + len(answered.tool_output)
   else:
       own, carried = _call_hook(hook, answered, prior, case_id)
       rag_chunks = own + carried
       n_fetched = len(own)
   ```
   `_call_hook` 이 반환값을 검증하고, 틀리면 `ValueError(f"{hook_name} 이 {case_id} 에서 …")`.

3. **`settings.py` — `CHUNK_POOL_HOOK = None`** 과 왜 있는지 한 단락.

4. **`config.py` — `SPEC` 에 `"hooks.chunk_pool": (str, False)`**, `apply()` 에서
   import 해 `settings.CHUNK_POOL_HOOK` 에 넣는다. `TO_SETTINGS` 는 문자열을 그대로
   옮기는 표라 여기 못 둔다 - `_install_labels` 처럼 따로 함수(`_install_hooks`)를 둔다.
   `env.example.yaml` 에 `hooks:` 블록을 더한다 (모든 키가 거기 등장해야 한다 -
   `tests/test_config.py` 가 확인한다).

`__main__.py` 의 dry-run 이 풀 크기를 찍는데, 훅이 켜져 있으면 그 이름도 같이 찍는다.
"풀이 달라졌는데 어느 파서가 만든 건지" 를 결과만 보고 알 수 있어야 한다.

## 테스트

`tests/test_history_input.py` 에 더한다. 스텁 훅은 테스트 파일 안의 함수로 두고
`settings.CHUNK_POOL_HOOK` 을 monkeypatch 한다.

| 확인할 것 | 어떻게 |
|---|---|
| 훅이 받는 것 | `turn` 이 로그 dict 그대로, `prior` 가 번호 오름차순, 비판받은 턴 자신은 `prior` 에 없다 |
| 풀 순서 | `rag_chunks == own + carried` |
| `n_fetched` | `== len(own)`, `carried` 가 아무리 커도 안 변한다 |
| 훅이 없으면 | 지금 테스트 전부 그대로 통과 (`test_history_chunks_join_the_pool` 등) |
| 반환 모양이 틀리면 | 길이 3 · 문자열 아닌 원소 → `ValueError`, 메시지에 `conversation_id:turn` |
| 설정 경로가 틀리면 | `config.apply` 가 `ConfigError`. 계산 전이다 |
| 경계 | `tests/test_boundary.py` 가 그대로 통과 - `features/` 는 손대지 않았다 |

골든셋(`tests/test_golden_sets.py`)은 훅 없이 돈다. 픽스처에 `history_input` 이 없어
내장 폴백이 맞는 자리다.

## 사내에서 처음 붙일 때 볼 것

1. 같은 로그로 **훅 없이 한 번, 훅 켜고 한 번** 돌려 결과 파일의 `chunk_data` 길이를
   턴별로 비교한다. 다른 턴이 어디인지가 두 파서의 차이다. 전부 같으면 훅이 하는 일이
   없는 것이고, 전부 다르면 둘 중 하나가 틀린 것이다.
2. 차이 난 턴의 `citation` 결과에서 `index_corrected` 가 늘었는지 본다. 늘었으면 훅이
   청크를 쪼개거나 합치는 경계가 다른 것이다.
3. case20 ↔ case22 분포가 움직였으면 그 이유를 `docs/insights/` 에 남긴다.

## 하지 않는 것

- `pre_queries` 는 훅으로 빼지 않는다. 세 갈래 폴백 규칙이 판정 정확도에 직접 닿아
  있고(case14), 그 규칙이 사내 파서와 다를 이유가 없다. 필요해지면 같은 모양으로
  `hooks.pre_queries` 를 더한다.
- `memory` 도 지금은 안 뺀다. memory 가 **사용자에 대한 정보**이고 모델이 답할 때
  참고해야 한다는 것까지만 확인됐다. 그걸 판정에 어떻게 쓸지는 case 분류 체계를 손본
  뒤 정한다 - 지금은 `history_quote` 대조 대상으로만 둔다.
- 훅이 `Case` 를 통째로 만들게 하지 않는다. 그러면 경계가 `Case` 에서 로그로 내려가고,
  `pre_queries` 규칙처럼 판정에 닿는 결정이 사내 코드로 새어 나간다.
