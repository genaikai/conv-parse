"""실무 전달본 — 결과 파일(v4)을 고치는 사람 단위로 다시 담는다. LLM 호출 없음.

결과 파일은 되짚는 사람을 위한 것이다 — 턴마다 단계 · 문항 · 확률이 전부 있다. 챗봇을 고칠
사람은 다른 것을 묻는다: 어디가 제일 많이 터지나, 그중 하나를 보여 달라, 왜 그렇게 판정했나.

규칙 다섯. 전부 실무가 **잘못 읽으면 엉뚱한 곳을 고치게 되는** 것들이다.

  - 묶음은 고치는 사람 단위이고 건수 많은 순. 정상은 빼고(필터 지표다), 검토는 맨 뒤에 따로
  - 사례마다 사유(결과 파일의 고정 문장 그대로)와 지나온 단계(문항과 답을 한 줄씩)
  - 확률 숫자는 싣지 않는다 — 실무가 무엇을 할지 정하는 기준이 아니다
  - 플래그는 정상 · 검토를 포함한 전부에서 센다 — 챗봇 실패와 독립인 사건이라
  - 본문이 없는 결과 파일(--no-text)도 받는다. 사례의 말 칸이 "(본문 없음)" 으로 남는다

파이프라인에 끼우지 않고 `src/handover.py` 가 결과 파일을 읽어 부른다. 판정과 전달본을 갈라
두면 문구를 고칠 때 kev 를 다시 부르지 않아도 된다.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Optional

from ragdiag import taxonomy

NAME = "handover"

NO_TEXT = "(본문 없음 — --no-text)"

EXCLUDED_NOTE = (
    "지연 · 컨텍스트 초과 · 구 문서 · 권한 조회 실패는 로그에 정보가 없어 이 방법으로 못 본다. "
    "인젝션 수행 · 개인정보 유출 · 못 내는 형태 요구 · 불명확 질문은 1단계에서 일부러 가르지 않는다 "
    "(docs/design/decision_tree_v4.md). 목록에 없다고 안 터지는 것이 아니다."
)

_P_SUFFIX = re.compile(r"\s*\(p [0-9.]+\)\s*$")
_BY_NAME = {b.name: b for b in taxonomy.BUCKETS.values()}
_NORMAL, _REVIEW = taxonomy.name("normal"), taxonomy.name(taxonomy.REVIEW)


def _step_line(step: dict) -> str:
    """단계 하나를 한 줄로 — '단계: 문항 답 · 문항 답'. 확률은 뺀다."""
    if "rules" in step:
        parts = [f"{k} {v}" for k, v in step["rules"].items()]
    else:
        parts = [f"{k} {v['answer'] if isinstance(v, dict) else v}" for k, v in step["answers"].items()]
    return f"{step['step']}: " + " · ".join(parts)


def build_example(turn: dict) -> dict:
    text = turn.get("text") or {}
    v = turn["verdict"]
    analysis: dict = {
        "사유": _P_SUFFIX.sub("", v["because"]),
        "지나온_단계": [_step_line(s) for s in turn.get("steps", [])],
    }
    if v.get("where"):
        analysis["근거_위치"] = list(v["where"])
        if text:
            analysis["근거_구절"] = {slot: text.get(slot, []) for slot in v["where"] if text.get(slot)}
    axes = turn.get("axes") or {}
    analysis["meta_data"] = {"대화": turn.get("chat_id"), "턴": turn.get("turn"),
                             "부서": axes.get("부서", ""), "직급": axes.get("직급", ""),
                             "직무": axes.get("직무", "")}
    return {
        "질문": text.get("question", NO_TEXT) if text else NO_TEXT,
        "답변": text.get("answer", NO_TEXT) if text else NO_TEXT,
        "사용자_반응": text.get("followup", NO_TEXT) if text else NO_TEXT,
        "분석": analysis,
    }


def _flag_section(turns: list[dict]) -> dict:
    counts = Counter()
    for t in turns:
        f = t.get("flags") or {}
        if f.get("앞 턴 누락") is True:
            counts["앞 턴 누락"] += 1
        elif isinstance(f.get("앞 턴 누락"), str):
            counts["옛 로그 (앞 턴 누락 판정 안 함)"] += 1
        if f.get("history 재구성 턴 수"):
            counts["history 재구성"] += 1
        if f.get("질문에 개인정보"):
            counts["질문에 개인정보"] += 1
    return dict(counts)


def build(result: dict, source: str = "", generated_at: Optional[str] = None) -> dict:
    """결과 파일(turns) → 실무 전달본."""
    judged = [t for t in result.get("turns", []) if "verdict" in t and not t.get("error")]
    errors = sum(1 for t in result.get("turns", []) if t.get("error"))
    normal = [t for t in judged if t["verdict"]["bucket"] == _NORMAL]
    review = [t for t in judged if t["verdict"]["bucket"] == _REVIEW]
    failed = [t for t in judged if t["verdict"]["bucket"] not in (_NORMAL, _REVIEW)]

    groups: dict[str, dict] = {}
    for t in failed:
        name = t["verdict"]["bucket"]
        g = groups.setdefault(name, {"묶음": name, "고칠_곳": _BY_NAME[name].owner, "건수": 0,
                                     "들어온_길": Counter(), "사례": []})
        g["건수"] += 1
        g["들어온_길"][t["verdict"]["because"]] += 1
        g["사례"].append(build_example(t))
    order = [b.name for b in taxonomy.BUCKETS.values()]
    listed = sorted(groups.values(), key=lambda g: (-g["건수"], order.index(g["묶음"])))
    for g in listed:
        g["들어온_길"] = dict(g["들어온_길"].most_common())

    out: dict = {
        "생성일시": generated_at or datetime.now().isoformat(timespec="seconds"),
        "대상": {"로그": source, "분석한 턴": len(judged), "실패로 판정": len(failed),
                 "정상으로 판정": len(normal), "검토": len(review), "오류": errors},
        "제외한_실패": EXCLUDED_NOTE,
        "분류": listed,
    }
    flags = _flag_section(judged)
    if flags:
        out["플래그"] = flags
    if review:
        out["검토"] = {
            "설명": "kev 가 확신하지 못한 턴이다. 어느 문항에서 막혔는지가 기준문을 고칠 곳이다",
            "건수": len(review),
            "막힌_문항": dict(Counter(t["verdict"]["stopped_at"] for t in review).most_common()),
            "사례": [build_example(t) for t in review],
        }
    return out


def process_data(ctx) -> tuple[list, list]:
    """등록부 규약. 이 기능은 집계에 싣는 지표가 없다 - 파일을 따로 만든다."""
    return [], []
