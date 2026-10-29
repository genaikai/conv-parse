"""결과 파일 — 턴마다 결론 · 이유 · 지나온 단계. 코드가 아니라 말로 쓴다.

모양은 docs/design/decision_tree_v4.md "결과 파일". 묶음 이름 · 단계 이름 · 이유 문장은
taxonomy 의 원본이고, 문항 문장은 questions.TEXT 다 — 코드는 id 로 들고 있다가 여기서만
문장으로 바꾼다. 전달본 · 대시보드가 이 문장을 검색하므로 같은 결론은 늘 같은 문장이다.

본문(text)은 기본으로 싣는다. 전달본 · 대시보드가 결과 파일만 읽어 사례를 만드는 구조라
빼면 둘이 원 로그를 다시 열어야 한다. `--no-text` 로 뺀다.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from ragdiag import questions, taxonomy
from ragdiag.results import TurnResult

if TYPE_CHECKING:                      # 런타임 의존을 만들지 않는다.
    from ragdiag.conv import Conversation   # 쓰는 것은 .user 와 .chat_id 두 개뿐이다.

RULE_TEXT = {"service_error": "자원 부족 문구", "empty_answer": "빈 답변", "degenerate": "붕괴"}


def _identity(result: TurnResult, conv) -> dict:
    case = result.case
    return {
        "chat_id": conv.chat_id,
        "turn": case.turn,
        "event_time": case.event_time,
        "target_turn": case.turn - 1,
        "target_event_time": case.target_event_time,
    }


def _step_payload(step) -> dict:
    out: dict = {"step": step.step}
    if step.rules is not None:
        out["rules"] = {RULE_TEXT.get(k, k): v for k, v in step.rules.items()}
    if step.answers is not None:
        out["answers"] = {questions.TEXT.get(k, k): v for k, v in step.answers.items()}
    return out


def _text_payload(case) -> dict:
    names = dict(questions.SLOTS)
    return {
        "question": case.last_query,
        "answer": case.llm_ans_on_last_q,
        "followup": case.current_query,
        "history": list(case.history_messages),
        names["retrieved"]: list(case.retrieved_chunks),
        names["tool"]: list(case.tool_chunks),
        names["history"]: list(case.history_chunks),
        names["memory"]: [case.memory] if case.memory.strip() else [],
    }


def build_turn(result: TurnResult, conv, with_text: bool = True) -> dict:
    turn = _identity(result, conv)
    if result.error:
        turn["error"] = result.error
        return turn
    v = result.verdict
    case = result.case
    turn["verdict"] = {"bucket": taxonomy.name(v.bucket), "sure": v.sure, "stopped_at": v.stopped_at,
                       "because": v.because, "where": list(v.where)}
    turn["steps"] = [_step_payload(s) for s in result.steps]
    turn["flags"] = dict(result.flags)
    meta = conv.user
    turn["axes"] = {"부서": meta.dept, "직급": meta.job_grade, "직무": meta.job_name,
                    "answered_by": case.answered_by, "ask_on": case.ask_on, "fallback": case.fallback}
    if with_text:
        turn["text"] = _text_payload(case)
    return turn


def summary_of(results: list[TurnResult]) -> dict:
    done = [r for r in results if r.verdict and not r.error]
    buckets = Counter(r.verdict.bucket for r in done)
    stopped = Counter(r.verdict.stopped_at.split(" · ")[0] for r in done)
    review = Counter(r.verdict.stopped_at for r in done if r.verdict.bucket == taxonomy.REVIEW)
    return {
        "turns": len(results),
        "buckets": {taxonomy.name(b): buckets.get(b, 0) for b in taxonomy.BUCKETS},
        "stopped_at": {s: stopped.get(s, 0) for s in taxonomy.STEPS},
        "review_at": dict(review.most_common()),
        "errors": sum(1 for r in results if r.error),
        "kev_calls": sum(r.n_kev_calls for r in results),
    }


def build_output(pairs: list[tuple["Conversation", TurnResult]], run_info: dict,
                 with_text: bool = True) -> dict:
    """(대화, 결과) 쌍들 → {run, summary, turns}. turns 는 입력 순서다."""
    results = [r for _, r in pairs]
    return {
        "run": dict(run_info),
        "summary": summary_of(results),
        "turns": [build_turn(r, conv, with_text) for conv, r in pairs],
    }


def summarize(pairs: list[tuple["Conversation", TurnResult]]) -> str:
    """터미널 요약. 어디를 고쳐야 하는지 보이게 하는 게 목적이다. 80칸."""
    from ragdiag.textfmt import pad

    results = [r for _, r in pairs]
    s = summary_of(results)
    done = s["turns"] - s["errors"]
    if not done:
        return f"판정된 턴이 없습니다. (실패 {s['errors']}건)"
    lines = ["=" * 78,
             f"판정 결과  |  성공 {done}건 / 실패 {s['errors']}건  |  kev 요청 {s['kev_calls']}회",
             "=" * 78, "", "[1] 묶음 (고치는 사람)"]
    for b in taxonomy.BUCKETS.values():
        n = s["buckets"][b.name]
        if n:
            lines.append(f"  {pad(b.name, 6)}{pad(b.owner, 30)}{n:>5}  {n / done:>5.1%}")
    lines += ["", "[2] 어디서 멈췄나"]
    for step in taxonomy.STEPS:
        n = s["stopped_at"][step]
        if n:
            lines.append(f"  {pad(step, 22)}{n:>5}  {n / done:>5.1%}")
    if s["review_at"]:
        lines += ["", "[3] 검토 — 어느 문항에서 막혔나 (기준문을 고칠 곳)"]
        for where, n in list(s["review_at"].items())[:5]:
            lines.append(f"  {pad(where, 60)}{n:>5}")
    errors = [r for r in results if r.error]
    if errors:
        lines += ["", f"[!] 실패 {len(errors)}건"]
        for r in errors[:5]:
            lines.append(f"  {r.case.case_id}: {r.error}"[:78])
    return "\n".join(lines)
