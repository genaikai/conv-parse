"""실무 전달본 — 결과 파일을 사람이 읽고 바로 쓸 수 있는 모양으로 바꾼다.

**LLM 을 부르지 않는다.** 이미 나온 결과 파일만 읽어 다시 담는다. 그래서 문구가
마음에 안 들면 몇 번이든 다시 만들 수 있다 - 판정을 다시 돌릴 이유가 없다.

판정용 결과 파일과 갈라 두는 이유가 셋이다.

1. 읽는 사람이 다르다. 판정용은 사후에 "왜 그 라벨이 나왔나" 를 되짚는 사람이 보고,
   이쪽은 "어디를 고쳐야 하나" 를 정하는 사람이 본다. 전자는 내부 용어를 알아야 하고
   후자는 몰라야 한다.
2. 묶는 축이 다르다. 판정용은 사용자 → 대화 → 턴 이고(원본 로그와 조인해야 한다),
   이쪽은 묶음(고치는 사람) → 라벨 → 태그 → 사례 다(무엇이 제일 많이 터지나부터 본다).
3. 담는 양이 다르다. 판정용은 청크 전문을 싣지만, 이쪽은 **근거로 선 청크만** 싣는다.
   열 개짜리 풀을 통째로 주면 어느 것이 문제인지 도로 찾아야 한다.

담지 않는 것: 신뢰도 · 증거 등급(실무가 쓸 기준이 아니다), N0 정상 턴(챗봇 지표가 아니라
필터 지표다), 내부 용어로 된 판정 근거(사유 문장으로 바꿔 싣는다).

무결성 플래그(C)와 이벤트(U2)는 실패가 아니라 **실패율 분모 밖**이다. 사례에 섞지 않고
별도 표로 센다 - 섞으면 "챗봇이 틀린 건수" 가 부풀어 보인다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from ragdiag import taxonomy

NAME = "handover"

# 문서를 싣지 않고 "없던 것" 을 싣는 라벨. 쓸 문서가 없다는 것이 결론이므로 문서 칸을
# 두면 빈 배열만 남아 혼란스럽다. 설명은 라벨마다 다르다 - 검색은 됐는데 없던 것(D1)과
# 부르지도 않은 것(T1)은 고칠 곳이 다르다.
NO_DOC = {
    "D1": "검색은 됐으나 이 내용이 문서에 없었다",
    "T1": "검색도 도구 호출도 없어 이 내용을 뒷받침할 것이 없었다",
    "T2": "도구가 가져온 결과에 이 내용이 없었다",
    "T3": "도구 결과가 비어 있었다",
}
MISSING_LABELS = set(NO_DOC)

# 문서 항목의 성격. 같은 구절을 G5[안씀] 에서는 "썼어야 하는데 안 쓴 것", G5[어긋남]
# 에서는 "답변과 어긋나는 것" 이라고 읽어야 한다. 이름이 같으면 실무가 잘못 읽는다.
#
# 다만 **키 이름으로 가르지 않는다.** 전에는 라벨마다 키가 달랐는데(활용했어야_할_문서 ·
# 답변과_어긋나는_문서 …) 사람은 읽기 좋지만 받아 쓰는 쪽은 네 이름을 다 알고 하나씩
# 있는지 봐야 한다. 키는 `문서` 하나로 두고 `성격` 에 그 말을 담는다.
DOC_UNUSED = ("활용했어야_할_문서", "검색은 됐는데 답변이 쓰지 않은 구절")
DOC_CONFLICT = ("답변과_어긋나는_문서", "답변이 이것과 다른 주장을 했다")
DOC_USED = ("활용한_문서", "썼지만 사용자가 원한 것과 달랐다")
DOC_DEFAULT = ("판정에_쓰인_문서", "판정 근거로 쓰인 구절")

# 로그에 정보가 없어 이 방법으로 못 보는 실패. "없는 문제" 가 아니라 "못 보는 문제" 라고
# 전달본 머리에 적는다 - 목록에서 조용히 지우면 받는 쪽이 "그건 안 터지나" 로 읽는다.
EXCLUDED_NOTE = (
    "응답 지연 · 답변 잘림 · 컨텍스트 초과 · 오래된 문서 · 권한 조회 실패는 이 로그에 "
    "응답 시간 · 종료 사유 · 문서 개정일 · 권한 정보가 없어 이 방법으로는 볼 수 없다. "
    "없는 문제가 아니라 여기서 못 보는 문제다.")

INTEGRITY_NOTE = (
    "실패 건수에 들어가지 않는 것들이다. 챗봇이 틀린 것이 아니라 그 턴의 기록을 믿을 수 "
    "없거나(C) 사용자 입력 쪽 사건(U2)이다. 받는 쪽도 로그 · 적재 · 화면이라 따로 센다.")


# ---------------------------------------------------------------------------
# 결과 파일에서 꺼내기
# ---------------------------------------------------------------------------

def _classification(turn: dict) -> dict:
    return turn.get("classification") or {}


def _evidence(turn: dict) -> dict:
    return _classification(turn).get("evidence") or {}


def _sufficiency(turn: dict) -> dict:
    return _evidence(turn).get("sufficiency") or {}


def obs_of(turn: dict) -> dict:
    return _evidence(turn).get("observation") or {}


def _checks(turn: dict) -> list:
    return _evidence(turn).get("checks") or []


def label_and_tags(turn: dict) -> tuple[str, list[str]]:
    """주 라벨과 태그. 옛 결과 파일(case0~30)은 v3 로 옮겨 읽는다.

    옮기는 표는 taxonomy.from_v2 다. 옛 case 하나가 v3 의 라벨 + 태그(case22 → G5 +
    G5:안씀)로 가므로 태그도 여기서 붙인다. v3 에 자리가 없는 옛 case(제외된 것 ·
    태그로만 남는 것)는 옛 번호 그대로 돌려주고, build 가 미분류로 보낸다.
    """
    c = _classification(turn)
    case_id = c.get("case_id") or ""
    tags = list(c.get("tags") or [])
    if case_id in taxonomy.LABELS or case_id == taxonomy.UNCLASSIFIED:
        return case_id, tags
    label, tag = taxonomy.from_v2(case_id)
    if tag and tag not in tags:
        tags.append(tag)
    return label or case_id, tags


def _sub_tags(label_id: str, tags: list[str]) -> list[str]:
    """이 라벨에 딸린 세부 태그의 뒷부분. `G5:어긋남` → `어긋남`.

    접두가 라벨(`G5:`)인 것과 묶음 글자(`T:` · `D:`)인 것 둘 다 받는다 - 도구 · 검색
    태그는 라벨이 아니라 묶음에 붙어 있다. 다른 라벨의 태그(`G1:언어` 가 G5 턴에)는
    이 라벨의 세부가 아니므로 걸러진다 - 그것은 `함께_관찰됨` 으로 간다.
    """
    prefixes = (label_id + ":", label_id[0] + ":")
    return [t.split(":", 1)[1] for t in tags if t.startswith(prefixes)]


def _evidence_chunks(turn: dict) -> list[dict]:
    """근거로 선 청크. 풀 전체가 아니라 판정이 "답한다" 고 본 것(p 가 문턱 이상)만이다.

    v3 는 판정 모델이 구절을 뽑지 않는다 - 청크 단위로 "답하나" 를 묻고 확률을 받는다.
    그래서 실을 수 있는 가장 작은 단위가 청크 전문이다. p 를 함께 싣는 것은 "얼마나
    확신했나" 를 등급 없이 보여 주는 길이다.
    """
    chunks = turn.get("chunk_data") or []
    out = []
    for e in _sufficiency(turn).get("evidence", []):
        i = e.get("chunk_index")
        text = chunks[i] if isinstance(i, int) and 0 <= i < len(chunks) else ""
        out.append({"문서번호": i, "p": e.get("p"), "구절": text})
    return out


def _conflict_quotes(turn: dict) -> list[dict]:
    """원문 대조를 통과한 어긋남 쌍만. 대조에 떨어진 것은 판정에도 안 쓰였다.

    통과한 것만 싣는 이유: 인용은 LLM 이 쓴 문장이라 원문에 없는 글자가 섞일 수 있다.
    코드가 답변 · 근거 양쪽 원문에서 글자로 찾아 살아남은 것만 실무에 보낸다.
    """
    return [{"답변": q.get("answer_quote", ""), "근거": q.get("source_quote", ""),
             "종류": q.get("kind", "")}
            for q in _evidence(turn).get("quotes") or [] if q.get("verified")]


def _code_evidence(turn: dict) -> list[str]:
    """코드가 확인한 것. 사유의 마지막 줄로 붙인다.

    신뢰도 등급을 빼는 대신 이것을 싣는다. "답변에서 확인했다" 와 "판정 모델이
    그렇게 읽었다" 는 실무가 아는 편이 낫고, high/medium 이라는 등급보다 뜻이 분명하다.
    """
    return [f"코드 확인 — {c['name']}: {c['detail']}"
            for c in _checks(turn) if c.get("verdict") == "violated"]


# ---------------------------------------------------------------------------
# 사유 - 라벨 + 태그 → 문장
# ---------------------------------------------------------------------------

# 라벨마다 고정 틀. 태그가 문장을 정하는 G1 · G2 · G5 · G6 은 아래 표가 따로 있다.
_FIXED: dict[str, tuple[str, list[str]]] = {
    "N0": ("후속 발화가 앞 답변을 문제 삼지 않았다", []),
    "U1": ("서비스가 낼 수 없는 형태(링크 · 이미지 · 파일 등)를 요구했다",
           ["질문 쪽 문제다. 질문 유도나 화면 안내로 막을 일이다"]),
    "U2": ("사용자가 질문에 개인정보를 넣었다",
           ["챗봇 실패가 아니라 입력 사건이다. 답변은 따로 끝까지 판정했다"]),
    "C1": ("대화에 앞 턴이 있는데 챗봇에 들어간 기록에는 빠져 있다",
           ["모델이 못 본 것인지 기록이 떨어뜨린 것인지 로그만으로 못 가른다"]),
    "C2": ("사용자 정보(memory)가 있는데 그 내용이 대화 어디에도 없다",
           ["사용자 정보 모듈이나 적재의 결함이다"]),
    "T1": ("업무 질문인데 검색도 도구 호출도 없이 답했다",
           ["서비스가 검색 없이 답할 수 있다고 판단했을 수 있다"]),
    "T2": ("도구를 불러 결과를 받았지만 그 내용이 질문에 답하지 못했다",
           ["도구 선택이나 넘긴 값이 질문과 맞지 않았을 수 있다"]),
    "T3": ("도구 결과가 비었는데 답변이 수치 · 사실을 단정했다",
           ["단정한 수치 · 사실의 출처가 도구 결과에 없다"]),
    # 없던 내용은 `문서.없던_내용` 에 있다. 여기 또 적으면 같은 문장이 두 번 나가는데,
    # 그 값이 길어서(실측 중앙값 60자 넘음) 근거를 읽기 나쁘게 만든다.
    "D1": ("검색된 문서에 사용자가 원한 내용이 없었다",
           ["검색은 됐으나 그 문서들로는 답할 수 없었다 (아래 '문서' 참고)"]),
    "G3": ("사용자가 물은 것과 다른 것을 답했다", []),
    "G4": ("여러 가지를 물었는데 일부만 답했다", []),
    "S1": ("정책 · 권한을 이유로 답변을 거절했고 사용자가 불만을 표했다", []),
    "S2": ("검색된 문서에 심긴 지시를 답변이 수행했다", []),
    "S3": ("질문에 없던 개인정보가 답변에 나왔다", []),
    "I1": ("서비스가 자원 부족 안내 문구를 냈다",
           ["모델이 답을 만든 적이 없다. 고칠 곳은 서빙이다"]),
    "I2": ("답변이 반복 · 깨진 글자로 무너져 읽을 수 없다",
           ["검색 · 생성 품질과 무관하다. 고칠 곳은 모델 · 서빙이다"]),
}

# G1 - 어느 요구를 어겼나. 여럿이면 "언어 · 형식" 처럼 이어 붙인다.
_G1_WHAT = {"언어": "언어", "길이": "분량", "포맷": "형식", "어조": "말투"}

# G2 - 어느 맥락을 어겼나. 문장이 서로 달라 첫 것을 요약으로, 나머지는 근거 줄로.
_G2 = {
    "조건": "앞 대화에서 정한 조건을 답변이 어겼다",
    "약속": "앞 답변이 약속한 것을 이번 답변이 지키지 않았다",
    "memory": "사용자 정보(memory)를 반영하지 않았다",
    "모순": "앞 답변과 다른 사실을 말했다",
}

# G5 - 근거를 어떻게 잘못 썼나.
_G5 = {
    "안씀": ("문서에 답이 있었는데 답변이 그것을 쓰지 않았다",
            ["검색된 문서에 그 내용이 있었다 (아래 구절)",
             "답변이 그 내용을 쓰지 않고 다르게 답했다"]),
    "어긋남": ("답변이 근거 문서와 어긋나는 주장을 했다",
             ["검색된 문서에 그 내용이 있었다 (아래 구절)",
              "답변이 문서와 다른 내용을 말했다"]),
    "지어낸인용": ("답변이 인용으로 제시한 문장이 문서에 없다",
               ["인용 표기된 문장을 문서 원문에서 찾지 못했다"]),
    "과거근거": ("답은 이전 턴에 가져온 문서에만 있었다",
              ["이번 검색 결과에는 없고 앞 턴의 문서에만 있었다"]),
}

# G6 - 무엇이 틀렸나.
_G6 = {
    "계산": "계산(등식 · 날짜) 질문에 틀리게 답했다",
    "코드": "코드 질문에 문법이 깨진 답을 냈다",
    "일반": "상식 질문에 사용자가 틀렸다고 반응했다 (코드로 확인하지는 못했다)",
}

# 주 라벨이 무엇이든 붙을 수 있는 태그. 근거 줄 하나씩. 코드 검증기 이름 태그는
# `_code_evidence` 가 상세와 함께 싣으므로 여기 없다.
_TAG_STEP = {
    "U3": "질문이 모호하거나 지시 대상이 앞 대화로도 안 풀렸다",
    "되묻기없음": "질문이 불완전했는데 답변이 되묻지 않았다",
    "복합질문": "질문이 여러 가지를 한 번에 물었다",
    "미검증주장": "답변에 일반 지식 주장이 있어 문서와 대조하지 못했다",
    "2차불일치": "근거 유무를 다른 방식으로 되물었을 때 결과가 흔들렸다",
    "T:인자불일치": "질문의 고유명사가 도구에 넘긴 값에 없다",
    "T:순서": "도구를 부른 순서가 의존 관계와 어긋난다",
    "D:출처미상": "검색 결과와 업무 도구 결과를 가르지 못해 도구 쪽 문제일 수도 있다",
}

# 그 턴에 선 플래그. 판정을 어떻게 읽어야 하는지 바꾸므로 사유에 한 줄 붙인다.
_FLAG_STEP = {
    "C1": "기록 주의 — 앞 턴이 기록에 빠져 있어 앞 대화 관련 판정은 하지 않았다",
    "C2": "기록 주의 — 사용자 정보가 대화와 맞지 않아 그 관련 판정은 하지 않았다",
}


def _summary(label_id: str, sub: list[str], obs: dict) -> tuple[str, list[str]]:
    """라벨 + 세부 태그 → (요약, 근거 줄들). 태그가 문장을 정하는 네 라벨만 분기한다."""
    if label_id == "G1":
        whats = [_G1_WHAT[s] for s in _G1_WHAT if s in sub]
        if whats:
            return f"사용자가 요구한 {' · '.join(whats)}대로 답하지 않았다", []
        return "사용자가 명시한 요구(언어 · 분량 · 형식 · 어조)대로 답하지 않았다", []
    if label_id == "G2":
        hits = [_G2[s] for s in _G2 if s in sub]
        if not hits:
            return "앞 대화의 맥락을 답변이 이어받지 못했다", []
        steps = []
        if "조건" in sub and obs.get("history_quote"):
            steps.append(f"앞 질문에서 정한 조건: {obs['history_quote']}")
            steps.append("답변이 그 조건과 다른 범위를 답했다")
        return hits[0], steps + hits[1:]
    if label_id == "G5":
        hits = [_G5[s] for s in _G5 if s in sub]
        if not hits:
            return "검색된 근거를 답변이 제대로 쓰지 못했다", []
        summary, steps = hits[0]
        return summary, list(steps) + [h[0] for h in hits[1:]]
    if label_id == "G6":
        hits = [_G6[s] for s in _G6 if s in sub]
        if not hits:
            return "문서와 무관한 질문에 틀리게 답했다", []
        return hits[0], hits[1:]
    if label_id in _FIXED:
        summary, steps = _FIXED[label_id]
        return summary, list(steps)
    if label_id == taxonomy.UNCLASSIFIED:
        return "지금 분류 체계로는 판정할 수 없었다", []
    return taxonomy.label(label_id), []


def reason_for(label_id: str, tags: list[str], turn: dict) -> dict:
    """왜 이 분류가 나왔는지. 내부 용어를 쓰지 않는다.

    라벨마다 틀을 두고 태그가 문장을 고른다 - v3 는 "무엇을 어겼나" 가 라벨이 아니라
    태그에 있으므로, 라벨만 보고 쓰면 G5 가 전부 같은 문장이 된다. 근거를 줄 단위
    배열로 두는 것은 판정 경로를 따라갈 수 있게 하기 위해서다 - 한 문장으로 뭉치면
    어디서 갈렸는지 되짚을 수 없다.

    원한 것은 `판정자가_읽은_것` 칸으로, 없던 내용은 `문서.없던_내용` 으로 올라갔다.
    여기 또 적으면 같은 말이 두 번 나간다.
    """
    obs = obs_of(turn)
    summary, steps = _summary(label_id, _sub_tags(label_id, tags), obs)
    steps += [_TAG_STEP[t] for t in tags if t in _TAG_STEP]
    steps += [_FLAG_STEP[f] for f in _classification(turn).get("flags") or []
              if f in _FLAG_STEP]
    steps += _code_evidence(turn)
    steps += list(_classification(turn).get("notes") or [])
    return {"요약": summary, "근거": steps}


# ---------------------------------------------------------------------------
# 문서
# ---------------------------------------------------------------------------

def _doc_kind(label_id: str, sub: list[str]) -> tuple[str, str]:
    """구절을 어떻게 읽어야 하나. 안 쓴 것 / 어긋나는 것 / 근거로 쓰인 것."""
    if label_id == "G5":
        if "안씀" in sub:
            return DOC_UNUSED
        if "과거근거" in sub:
            return ("활용했어야_할_문서", "이전 턴에 가져온 문서에만 답이 있었다")
        if "지어낸인용" in sub:
            return ("답변과_어긋나는_문서", "답변의 인용 표기가 이 원문과 어긋난다")
        if "어긋남" in sub:
            return DOC_CONFLICT
    if label_id == "G2" and ("모순" in sub or "memory" in sub):
        return ("답변과_어긋나는_문서", "앞 답변 · 사용자 정보가 이번 답변과 어긋난다")
    if label_id == "G3":
        return DOC_USED
    if label_id == "G4":
        return ("활용한_문서", "썼지만 일부만 답했다")
    return DOC_DEFAULT


def document_for(label_id: str, tags: list[str], turn: dict) -> Optional[dict]:
    """이 사례에 붙일 문서. 없으면 None 이라 칸 자체가 안 생긴다.

    키 이름은 언제나 `문서` 하나고, 그 문서를 어떻게 읽어야 하는지는 `성격` 이 말한다.
    근거 청크는 `구절`, 원문 대조를 통과한 어긋남 쌍은 `어긋난_구절` 이다 - 둘은 출처가
    다르다(전자는 충족도 판정, 후자는 모순 판정 뒤의 인용).
    """
    if label_id in MISSING_LABELS:
        missing = _sufficiency(turn).get("missing") or obs_of(turn).get("unmet_need")
        if not missing:
            return None
        return {"성격": "문서에_없던_것", "설명": NO_DOC[label_id],
                "없던_내용": missing, "구절": []}
    chunks = _evidence_chunks(turn)
    conflicts = _conflict_quotes(turn)
    if not chunks and not conflicts:
        return None
    kind, note = _doc_kind(label_id, _sub_tags(label_id, tags))
    document = {"성격": kind, "설명": note, "구절": chunks}
    if conflicts:
        document["어긋난_구절"] = conflicts
    return document


# ---------------------------------------------------------------------------
# 사례
# ---------------------------------------------------------------------------

def build_example(user: dict, conv: dict, turn: dict, label_id: str,
                  tags: Optional[list[str]] = None) -> dict:
    """사례 하나. 원본 로그로 되짚을 수 있게 식별자를 먼저 둔다."""
    # 챗봇은 **앞 질문들을 함께 받아** 답했다. 마지막 질문만 보여주면 답변이 왜
    # 그랬는지 알 수 없다 - "국내 기준으로만" 이 두 턴 앞에 있고 답변이 해외로 답한
    # 경우, 마지막 질문("식비는 얼마인가요")만 보면 답변이 멀쩡해 보인다.
    #
    # 마지막 질문을 따로 두는 이유: 그것이 **이 답변이 응답한 질문**이다. 전부를 한
    # 배열로 펴면 읽는 사람이 "마지막 것이 답을 받은 질문" 임을 알아야 한다.
    pre = turn.get("pre_queries") or [""]
    example: dict = {}
    if len(pre) > 1:
        example["앞_질문들"] = pre[:-1]
    example["질문"] = pre[-1]
    example["답변"] = turn.get("llm_ans_on_last_q", "")
    example["사용자_반응"] = turn.get("current_query", "")

    # 여기부터는 **우리가 본 것**이다. 위 네 칸은 사용자와 챗봇이 실제로 한 말이고,
    # 이 아래는 전부 이 도구가 만든 것이다 - 사유도, 고른 문서도, 식별자도.
    # 대화와 섞여 있으면 읽는 사람이 매번 건너뛰어야 해서 한 칸으로 묶는다. 접으면
    # 대화만 남아 훑기 좋고, 펴면 "무엇이 문제고 무엇을 고칠까" 가 순서대로 나온다.
    #
    # 정리된 질문은 판정이 **실제로 근거를 찾는 데 쓴 질문**이다. 검색 실패(D1)에서
    # 실무가 물을 것이 "그래서 뭘 찾으려다 실패했나" 라, 그 답이 여기 있다 -
    # 검색팀이 그대로 넣어 재현할 수 있는 값이기도 하다.
    #
    # 코드가 LLM 없이 확정하는 라벨(I1 · I2 …)에는 관측이 없다. 그때는 칸 자체를
    # 만들지 않는다.
    obs = obs_of(turn)
    read: dict = {}
    if obs.get("resolved_question"):
        read["질문"] = obs["resolved_question"]
    if obs.get("unmet_need"):
        read["원한_것"] = obs["unmet_need"]

    if tags is None:
        tags = label_and_tags(turn)[1]
    # 되짚을 때만 보는 것. 원본 로그로 찾아가는 식별자와 곁다리 관찰.
    meta: dict = {
        "대화": conv.get("chat_id"),
        "턴": turn.get("turn"),
        "부서": user.get("db_dept_name"),
        # 사례를 하나만 떼어 티켓에 붙이면 어느 분류였는지가 사라진다.
        "case": label_id,
        # 사유 문장은 태그에서 만들었다. 원래 태그를 두면 문장과 판정을 맞춰 볼 수 있다.
        "태그": tags,
    }
    secondary = _classification(turn).get("secondary_cases") or []
    if secondary:
        # 주 라벨과 별개로 성립한 것. 한 턴이 검색 실패이면서 요구 불이행일 수 있다.
        # 결과 파일은 이미 풀어 쓴 객체로 담는다(case_id · case_name · type_id …).
        meta["함께_관찰됨"] = [
            {"case": s["case_id"], "이름": s["case_name"]} for s in secondary]

    # 펼쳤을 때 읽는 순서다. 결론(사유) → 근거(문서) → 모델이 읽은 것 → 식별자.
    분석: dict = {"사유": reason_for(label_id, tags, turn)}
    document = document_for(label_id, tags, turn)
    if document:
        분석["문서"] = document
    if read:
        분석["판정자가_읽은_것"] = read
    분석["meta_data"] = meta
    example["분석"] = 분석
    return example


# ---------------------------------------------------------------------------
# 전달본
# ---------------------------------------------------------------------------

_GROUP_RANK = {g: i for i, g in enumerate("NUCTDGSI")}


def _integrity_section(hits: dict[str, list[dict]]) -> Optional[dict]:
    """플래그 · 이벤트 표. 하나도 없으면 None - 빈 표는 "무결성이 뭔가" 만 묻게 한다."""
    present = [k for k, v in hits.items() if v]
    if not present:
        return None
    items = []
    for label_id in taxonomy.ordered(present):
        l = taxonomy.LABELS.get(label_id)
        items.append({"id": label_id, "이름": l.name if l else label_id,
                      "뜻": taxonomy.desc(label_id),
                      "건수": len(hits[label_id]), "턴": hits[label_id]})
    return {"설명": INTEGRITY_NOTE, "항목": items}


def build(result: dict, source: str = "", generated_at: Optional[str] = None) -> dict:
    """결과 파일(analysis_results) → 실무 전달본.

    N0(정상 턴)은 뺀다 - 챗봇 지표가 아니라 필터가 넓게 잡은 것이라, 실무가 보면
    "이건 왜 실패냐" 가 된다. 미분류는 맨 뒤에 따로 묶어 싣는다. 숨기면 실패 건수가
    줄어 보이고, 나중에 원본과 대조할 때 신뢰를 잃는다.

    플래그 · 이벤트는 N0 와 미분류를 포함한 **판정된 턴 전부**에서 센다. 정상 턴에서도
    사용자가 개인정보를 넣을 수 있고, 그것은 답변의 성패와 독립이다.
    """
    buckets: dict[str, dict] = {}
    unclassified: list[dict] = []
    hits: dict[str, list[dict]] = {}
    total = skipped = 0

    for user in result.get("analysis_results", []):
        for conv in user.get("conversations", []):
            for turn in conv.get("turns", []):
                classification = _classification(turn)
                if not classification.get("case_id") or classification.get("error"):
                    continue
                label_id, tags = label_and_tags(turn)
                total += 1
                for marker in list(classification.get("flags") or []) + list(
                        classification.get("events") or []):
                    hits.setdefault(marker, []).append(
                        {"대화": conv.get("chat_id"), "턴": turn.get("turn")})
                if label_id == "N0":
                    skipped += 1
                    continue
                example = build_example(user, conv, turn, label_id, tags)
                if label_id not in taxonomy.LABELS:
                    # 어느 쪽 미분류인지는 meta_data 안에 둔다. 밖에 붙이면 이 사례만
                    # meta_data 뒤에 칸이 하나 더 생겨서 모양이 다른 사례가 된다.
                    # label() 은 "id · 이름" 꼴이라 case 칸과 겹친다. 이름만 담는다.
                    example["분석"]["meta_data"]["구분"] = (
                        taxonomy.describe(label_id)["case_name"]
                        if label_id == taxonomy.UNCLASSIFIED
                        else f"옛 분류 {label_id} — 지금 체계에 해당 라벨이 없다")
                    unclassified.append(example)
                    continue
                meta = taxonomy.describe(label_id)
                bucket = buckets.setdefault(meta["type_id"], {
                    "type": meta["type_id"], "이름": meta["type_name"],
                    "고칠_곳": meta["owner"], "건수": 0, "_cases": {}})
                bucket["건수"] += 1
                case_bucket = bucket["_cases"].setdefault(label_id, {
                    "case": label_id, "이름": meta["case_name"],
                    "뜻": taxonomy.desc(label_id), "건수": 0,
                    "태그별": {}, "사례": []})
                case_bucket["건수"] += 1
                # 같은 라벨 안에서 무엇을 어겼나. G1 이 열 건이면 그중 언어가 몇, 형식이
                # 몇인지가 고칠 순서를 정한다 - 라벨은 셀을 만들지 않고 태그는 센다.
                for tag in tags:
                    case_bucket["태그별"][tag] = case_bucket["태그별"].get(tag, 0) + 1
                case_bucket["사례"].append(example)

    groups = []
    for bucket in buckets.values():
        cases = bucket.pop("_cases")
        for case_bucket in cases.values():
            meanings = {t: taxonomy.TAGS[t] for t in case_bucket["태그별"]
                        if t in taxonomy.TAGS}
            if meanings:
                case_bucket["태그_뜻"] = meanings
            # 태그별 → 태그_뜻 → 사례 순으로 읽히게 사례를 뒤로 보낸다.
            case_bucket["사례"] = case_bucket.pop("사례")
        bucket["세부"] = [cases[c] for c in taxonomy.ordered(cases)]
        groups.append(bucket)
    # 건수가 많은 묶음이 위로. 실무가 처음 보는 것은 "어디가 제일 많이 터지나" 다.
    # 같으면 분류 체계의 묶음 순서.
    groups.sort(key=lambda b: (-b["건수"], _GROUP_RANK.get(b["type"], 99)))

    out = {
        "생성일시": generated_at or datetime.now().isoformat(timespec="seconds"),
        "대상": {"로그": source, "분석한 턴": total,
                 "실패로 판정": total - skipped - len(unclassified),
                 "정상으로 판정": skipped},
        "제외한_실패": EXCLUDED_NOTE,
        "분류": groups,
    }
    integrity = _integrity_section(hits)
    if integrity:
        out["무결성_이벤트"] = integrity
    if unclassified:
        out["미분류"] = {
            "설명": "지금 분류 체계로 판정하지 못한 턴이다. 사람이 봐야 한다",
            "건수": len(unclassified),
            "사례": unclassified,
        }
    return out


def process_data(ctx) -> tuple[list, list]:
    """등록부 규약. 이 기능은 집계에 싣는 지표가 없다 - 파일을 따로 만든다.

    파이프라인에 끼우지 않고 `src/handover.py` 가 결과 파일을 읽어 부른다.
    판정과 전달본을 갈라 두면 문구를 고칠 때 LLM 을 다시 부르지 않아도 된다.
    """
    return [], []
