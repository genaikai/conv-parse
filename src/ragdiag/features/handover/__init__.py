"""실무 전달본 — 결과 파일을 사람이 읽고 바로 쓸 수 있는 모양으로 바꾼다.

**LLM 을 부르지 않는다.** 이미 나온 결과 파일만 읽어 다시 담는다. 그래서 문구가
마음에 안 들면 몇 번이든 다시 만들 수 있다 - 판정을 다시 돌릴 이유가 없다.

판정용 결과 파일과 갈라 두는 이유가 셋이다.

1. 읽는 사람이 다르다. 판정용은 사후에 "왜 그 case 가 나왔나" 를 되짚는 사람이 보고,
   이쪽은 "어디를 고쳐야 하나" 를 정하는 사람이 본다. 전자는 내부 용어를 알아야 하고
   후자는 몰라야 한다.
2. 묶는 축이 다르다. 판정용은 사용자 → 대화 → 턴 이고(원본 로그와 조인해야 한다),
   이쪽은 TYPE → case → 사례 다(무엇이 제일 많이 터지나부터 본다).
3. 담는 양이 다르다. 판정용은 청크 전문을 싣지만, 이쪽은 **답변에 쓰였어야 할 구절만**
   싣는다. 열 개짜리 청크를 통째로 주면 어느 것이 문제인지 도로 찾아야 한다.

담지 않는 것: 신뢰도 등급(실무가 쓸 기준이 아니다), case0 정상 턴(챗봇 지표가 아니라
필터 지표다), 내부 용어로 된 판정 근거(사유 문장으로 바꿔 싣는다).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from ragdiag import taxonomy

NAME = "handover"

# 사례 하나에 붙일 문서 항목의 이름과 뜻. case 마다 "그 문서가 왜 거기 있는지" 가
# 다르다 - 같은 인용을 case22 에서는 "썼어야 하는데 안 쓴 것", case18 에서는
# "답변과 어긋나는 것" 이라고 읽어야 한다. 이름이 같으면 실무가 잘못 읽는다.
DOC_FIELD = {
    "case22": ("활용했어야_할_문서", "검색은 됐는데 답변이 쓰지 않은 구절"),
    "case18": ("답변과_어긋나는_문서", "답변이 이것과 다른 주장을 했다"),
    "case17": ("활용한_문서", "썼지만 답변이 두루뭉술했다"),
    "case13": ("활용한_문서", "썼지만 사용자가 원한 것과 달랐다"),
    "case24": ("활용한_문서", "인용 표기가 원문과 어긋난다"),
}

# 문서를 싣지 않고 "없던 것" 을 싣는 case. 쓸 문서가 없다는 것이 결론이므로
# 문서 칸을 두면 빈 배열만 남아 혼란스럽다.
MISSING_CASES = {"case20", "case21"}


def _sufficiency(turn: dict) -> dict:
    return ((turn.get("classification") or {}).get("evidence") or {}).get("sufficiency") or {}


def _observation(turn: dict) -> dict:
    return ((turn.get("classification") or {}).get("evidence") or {}).get("observation") or {}


def _checks(turn: dict) -> list:
    return ((turn.get("classification") or {}).get("evidence") or {}).get("checks") or []


def _verified_quotes(turn: dict) -> list[dict]:
    """인용 대조를 통과한 구절만. 청크 전문도, 폐기된 인용도 싣지 않는다.

    통과한 것만 싣는 이유: Step 2 가 "이 문서가 요구에 답한다" 고 지목하고 코드가
    원문과 글자로 대조해 살아남은 것이다. 지목만 받고 대조에 떨어진 것은 판정에도
    안 쓰였으므로 실무에 보낼 것이 아니다.
    """
    return [{"문서번호": e["chunk_index"], "구절": e["quote"]}
            for e in _sufficiency(turn).get("evidence", [])]


def _code_evidence(turn: dict) -> list[str]:
    """코드가 확인한 것. 사유의 마지막 줄로 붙인다.

    신뢰도 등급을 빼는 대신 이것을 싣는다. "답변에서 확인했다" 와 "판정 모델이
    그렇게 읽었다" 는 실무가 아는 편이 낫고, high/medium 이라는 등급보다 뜻이 분명하다.
    """
    return [f"코드 확인 — {c['name']}: {c['detail']}"
            for c in _checks(turn) if c.get("verdict") == "violated"]


def reason_for(case_id: str, turn: dict) -> dict:
    """왜 이 분류가 나왔는지. 내부 용어를 쓰지 않는다.

    case 마다 틀을 두고 관측값을 끼워 넣는다. 근거를 줄 단위 배열로 두는 것은
    판정 경로를 따라갈 수 있게 하기 위해서다 - 한 문장으로 뭉치면 어디서 갈렸는지
    되짚을 수 없다.
    """
    obs = _observation(turn)
    suf = _sufficiency(turn)
    want = obs.get("unmet_need") or "사용자가 원한 것"
    steps: list[str] = []
    if want:
        steps.append(f"사용자가 원한 것: {want}")

    if case_id == "case22":
        summary = "문서에 답이 있었는데 답변이 그것을 쓰지 않았다"
        steps += ["검색된 문서에 그 내용이 있었다 (아래 구절)",
                  "답변이 그 내용을 쓰지 않고 다르게 답했다"]
    elif case_id == "case18":
        summary = "답변이 검색 문서와 어긋나는 주장을 했다"
        steps += ["검색된 문서에 그 내용이 있었다 (아래 구절)",
                  "답변이 문서와 다른 내용을 말했다"]
    elif case_id == "case20":
        summary = "검색된 문서에 사용자가 원한 내용이 없었다"
        if suf.get("missing"):
            steps.append(f"문서에 없어서 답할 수 없던 것: {suf['missing']}")
        steps.append("검색은 됐으나 그 문서들로는 답할 수 없었다")
    elif case_id == "case21":
        summary = "검색이 아예 수행되지 않았다 (문서 0건)"
        steps.append("서비스가 검색 없이 답할 수 있다고 판단했을 수 있다")
    elif case_id == "case17":
        summary = "문서는 충분했으나 답변이 두루뭉술해 다음 행동을 알 수 없다"
        steps.append("답변만 보고 사용자가 무엇을 해야 할지 알 수 없다")
    elif case_id == "case13":
        summary = "사용자가 물은 것과 다른 것을 답했다"
    elif case_id in ("case10", "case11", "case12"):
        what = {"case10": "언어", "case11": "분량", "case12": "형식"}[case_id]
        summary = f"사용자가 요구한 {what}대로 답하지 않았다"
        if obs.get("requested_quote"):
            steps.append(f"앞 질문에 있던 요구: {obs['requested_quote']}")
    elif case_id == "case30":
        summary = "답변이 같은 글자·기호의 반복으로 무너졌다"
        steps.append("검색·생성 품질과 무관하다. 고칠 곳은 모델·서빙이다")
    elif case_id == "case9":
        summary = "서비스가 자원 부족 안내 문구를 냈다"
    elif case_id == "case29":
        summary = "검색된 문서에 심긴 지시를 답변이 수행했다"
    elif case_id == "case28":
        summary = "정책·권한을 이유로 답변을 거절했다"
    elif case_id in ("case25", "case26", "case27"):
        what = {"case25": "상식", "case26": "계산", "case27": "코드·도구 사용법"}[case_id]
        summary = f"{what} 질문에 틀리게 답했다"
    elif case_id in ("case1", "case2", "case3", "case4", "case6"):
        summary = taxonomy.label(case_id) + " — 질문 쪽 문제다"
    elif case_id == taxonomy.UNCLASSIFIED:
        summary = "지금 분류 체계로는 판정할 수 없었다"
    elif case_id == taxonomy.OUT_OF_TAXONOMY:
        summary = "불만 성격이 분류 체계 어디에도 맞지 않는다"
    else:
        summary = taxonomy.label(case_id)

    if obs.get("complaint_quote"):
        steps.append(f"사용자 반응에서 읽은 근거: {obs['complaint_quote']}")
    steps += _code_evidence(turn)
    for note in (turn.get("classification") or {}).get("notes", []):
        steps.append(note)
    return {"요약": summary, "근거": steps}


def build_example(user: dict, conv: dict, turn: dict, case_id: str) -> dict:
    """사례 하나. 원본 로그로 되짚을 수 있게 식별자를 먼저 둔다."""
    example: dict = {
        "대화": conv.get("conversation_id"),
        "턴": turn.get("turn"),
        "부서": user.get("db_dept_name"),
        "질문": (turn.get("pre_queries") or [""])[-1],
        "답변": turn.get("llm_ans_on_last_q", ""),
        "사용자_반응": turn.get("current_query", ""),
        "사유": reason_for(case_id, turn),
    }
    secondary = (turn.get("classification") or {}).get("secondary_cases") or []
    if secondary:
        # 주 라벨과 별개로 성립한 것. 한 턴이 검색 실패이면서 복합 질문일 수 있다.
        # 결과 파일은 이미 풀어 쓴 객체로 담는다(case_id · case_name · type_id …).
        example["함께_관찰됨"] = [
            {"case": s["case_id"], "이름": s["case_name"]} for s in secondary]

    if case_id in MISSING_CASES:
        missing = _sufficiency(turn).get("missing")
        if missing:
            example["문서에_없던_것"] = missing
    else:
        quotes = _verified_quotes(turn)
        if quotes:
            field, note = DOC_FIELD.get(case_id, ("관련_문서", "판정에 쓰인 구절"))
            example[field] = quotes
            example[f"{field}_설명"] = note
    return example


def build(result: dict, source: str = "", generated_at: Optional[str] = None) -> dict:
    """결과 파일(analysis_results) → 실무 전달본.

    case0(정상 턴)은 뺀다 - 챗봇 지표가 아니라 필터가 넓게 잡은 것이라, 실무가 보면
    "이건 왜 실패냐" 가 된다. 미분류는 맨 뒤에 따로 묶어 싣는다. 숨기면 실패 건수가
    줄어 보이고, 나중에 원본과 대조할 때 신뢰를 잃는다.
    """
    buckets: dict[str, dict] = {}
    unclassified: list[dict] = []
    total = skipped = 0

    for user in result.get("analysis_results", []):
        for conv in user.get("conversations", []):
            for turn in conv.get("turns", []):
                classification = turn.get("classification") or {}
                case_id = classification.get("case_id")
                if not case_id or classification.get("error"):
                    continue
                total += 1
                if case_id == "case0":
                    skipped += 1
                    continue
                example = build_example(user, conv, turn, case_id)
                if case_id in (taxonomy.UNCLASSIFIED, taxonomy.OUT_OF_TAXONOMY):
                    unclassified.append({**example, "사유_구분": taxonomy.label(case_id)})
                    continue
                meta = taxonomy.describe(case_id)
                bucket = buckets.setdefault(meta["type_id"], {
                    "type": meta["type_id"], "이름": meta["type_name"],
                    "건수": 0, "_cases": {}})
                bucket["건수"] += 1
                case_bucket = bucket["_cases"].setdefault(case_id, {
                    "case": case_id, "이름": meta["case_name"],
                    "뜻": taxonomy.desc(case_id), "건수": 0, "사례": []})
                case_bucket["건수"] += 1
                case_bucket["사례"].append(example)

    groups = []
    for bucket in sorted(buckets.values(), key=lambda b: b["type"]):
        cases = bucket.pop("_cases")
        bucket["세부"] = [cases[c] for c in taxonomy.ordered(cases)]
        groups.append(bucket)
    # 건수가 많은 묶음이 위로. 실무가 처음 보는 것은 "어디가 제일 많이 터지나" 다.
    groups.sort(key=lambda b: -b["건수"])

    out = {
        "생성일시": generated_at or datetime.now().isoformat(timespec="seconds"),
        "대상": {"로그": source, "분석한 턴": total,
                 "실패로 판정": total - skipped - len(unclassified),
                 "정상으로 판정": skipped},
        "분류": groups,
    }
    if unclassified:
        out["미분류"] = {
            "설명": "지금 분류 체계로 판정하지 못한 턴이다. 사람이 봐야 한다",
            "건수": len(unclassified),
            "사례": unclassified,
        }
    return out


def process_data(ctx) -> tuple[list, list]:
    """등록부 규약. 이 기능은 집계에 싣는 지표가 없다 - 파일을 따로 만든다.

    파이프라인에 끼우지 않고 `tools/handover.py` 가 결과 파일을 읽어 부른다.
    판정과 전달본을 갈라 두면 문구를 고칠 때 LLM 을 다시 부르지 않아도 된다.
    """
    return [], []
