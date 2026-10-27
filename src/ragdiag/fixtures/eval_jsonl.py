# -*- coding: utf-8 -*-
"""eval.jsonl 경로의 합성 예시 — 네 파일을 코드로 만든다 (docs/assemble.md).

가짜 데이터는 파일이 아니라 코드다 — 데이터 파일은 커밋하지 않는다. `assemble.py example <폴더>` 가 이걸 써서
eval.jsonl · filter.json · selected.jsonl · records.jsonl 을 떨군다. records.jsonl 은 사내
lookup 이 냈을 모양을 손으로 쓴 것이다 - C-0002 는 앞 턴 1 이 records 에 없고(n_prior=1)
답변 턴의 history_input 에만 들어 있다.
"""

from __future__ import annotations

import json
from pathlib import Path

ORG = {"job_grade": "선임", "db_dept_name": "플랫폼개발팀", "db_job_name": "백엔드 개발"}
ORG2 = {"job_grade": "책임", "db_dept_name": "공정기술팀", "db_job_name": "공정 엔지니어"}


def _ev(cid, turn, t, emo, score, org):
    return {"chat_id": cid, "event_time": t, "turn": turn, "ask_on": "web", "answered_by": "web",
            "route_intent": None, "fallback": None, **org, "prev_question": None,
            "llm_eval_result": None, "llm_eval_score": None, "llm_eval_score_top1": None,
            "llm_eval_alternatives": [],
            "llm_emotion_result": emo, "llm_emotion_score": score, "llm_emotion_score_top1": score,
            "llm_emotion_alternatives": [{"label": emo, "prob": 0.9}],
            "llm_emotion_context_summarized": ""}


EVAL_ROWS = [
    _ev("C-0001", 1, "2026-10-20 09:10:01", "중립", 50.0, ORG),
    _ev("C-0001", 2, "2026-10-20 09:12:33", "불만", 82.0, ORG),
    _ev("C-0001", 3, "2026-10-20 09:15:02", "중립", 40.0, ORG),
    _ev("C-0002", 1, "2026-10-21 14:00:00", "중립", 45.0, ORG2),
    _ev("C-0002", 2, "2026-10-21 14:03:10", "중립", 48.0, ORG2),
    _ev("C-0002", 3, "2026-10-21 14:07:45", "불만", 88.0, ORG2),
    _ev("C-0003", 1, "2026-10-22 11:00:00", "불만", 90.0, ORG2),   # turn 1 은 후보가 아니다
]

FILTER = {"name": "불만 80점 이상", "state": {"emotion_range": [80, 100]}}

# ① select 가 EVAL_ROWS + FILTER 로 내는 것. 테스트가 같은지 잰다.
SELECTED_ROWS = [
    {"chat_id": "C-0001", "event_time": "2026-10-20 09:12:33", "target_event_time": "2026-10-20 09:10:01",
     "n_prior": 0, "llm_emotion_result": "불만", "llm_emotion_score": 82.0, "llm_emotion_score_top1": 82.0,
     "llm_emotion_alternatives": [{"label": "불만", "prob": 0.9}]},
    {"chat_id": "C-0002", "event_time": "2026-10-21 14:07:45", "target_event_time": "2026-10-21 14:03:10",
     "n_prior": 1, "llm_emotion_result": "불만", "llm_emotion_score": 88.0, "llm_emotion_score_top1": 88.0,
     "llm_emotion_alternatives": [{"label": "불만", "prob": 0.9}]},
]

# ② 사내 lookup 이 냈을 모양. 답변 턴은 본문 전부, 불만 턴은 질문만.
RECORDS_ROWS = [
    {"chat_id": "C-0001", "event_time": "2026-10-20 09:10:01", **ORG,
     "user_question": "사내 API 게이트웨이 호출 제한이 얼마야?",
     "llm_response": "호출 제한은 팀마다 다르게 설정됩니다.",
     "retrieved_data": "[API 운영 가이드 3.2] 게이트웨이 기본 호출 제한은 분당 600회이며 팀 단위로 상향 신청할 수 있다.",
     "tool_output": None, "tool_calls": [],
     "history_input": {"history_chat": [], "memory": "", "retrieved_data": [], "tool_output": []},
     "memory": "", "prev_question": None, "carried_turn_nos": [], "carried_turn_count": 0,
     "trace_matched": "true", "ask_on": "web", "answered_by": "web", "route_intent": None, "fallback": None},
    {"chat_id": "C-0001", "event_time": "2026-10-20 09:12:33", **ORG,
     "user_question": "숫자를 물었는데요. 분당 몇 회예요?"},
    {"chat_id": "C-0002", "event_time": "2026-10-21 14:03:10", **ORG2,
     "user_question": "그 라인 PR 두께 규격은?",
     "llm_response": "PR 두께 규격은 공정마다 다릅니다.",
     "retrieved_data": ["[공정표준 WSP-001] WSPED01 라인의 PR 두께 규격은 1.2±0.05 µm 이다."],
     "tool_output": None, "tool_calls": [],
     "history_input": {"history_chat": [{"role": "user", "content": "WSPED01 라인 담당이 누구야?"},
                                        {"role": "assistant", "content": "설비팀이 담당합니다."}],
                       "memory": "사용자는 WSPED01 라인 공정 담당자다.", "retrieved_data": [], "tool_output": []},
     "memory": "사용자는 WSPED01 라인 공정 담당자다.", "prev_question": ["WSPED01 라인 담당이 누구야?"],
     "carried_turn_nos": [1], "carried_turn_count": 1, "trace_matched": "true",
     "ask_on": "web", "answered_by": "web", "route_intent": None, "fallback": None},
    {"chat_id": "C-0002", "event_time": "2026-10-21 14:07:45", **ORG2,
     "user_question": "우리 라인 규격을 물었는데요"},
]


def write_example(folder: str | Path) -> list[Path]:
    """네 파일을 folder 에 쓴다. 돌려주는 것은 쓴 경로들."""
    d = Path(folder)
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for name, rows in (("eval.jsonl", EVAL_ROWS), ("selected.jsonl", SELECTED_ROWS),
                       ("records.jsonl", RECORDS_ROWS)):
        p = d / name
        p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        out.append(p)
    p = d / "filter.json"
    p.write_text(json.dumps(FILTER, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out.append(p)
    return out
