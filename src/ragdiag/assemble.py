"""eval.jsonl 입력 — 필터를 먼저 걸어 필요한 턴만 조립한다.

conv-eval.json 은 대화 전부를 담아 너무 크다. 그 앞 단계 파일 eval.jsonl 은 턴마다 점수 ·
라벨 · 조직 · 시각만 있어 가볍다. 그래서 순서를 바꾼다 — **가벼운 파일로 먼저 고르고,
고른 턴의 본문만 CSV 에서 꺼낸다.**

    eval.jsonl + filter.json ──① select (여기)──▶ selected.jsonl
    selected.jsonl + csv     ──② lookup (사내)──▶ records.jsonl
    records.jsonl + selected ──③ run.py (여기)──▶ parsed.json

② 는 이 저장소 밖이다. CSV 를 아는 코드는 CSV 가 있는 곳에 있어야 하고, 여기서는 실
CSV 가 없어 테스트할 수 없다. 저장소가 ② 에게 주는 것은 **파일 계약 둘**(docs/assemble.md)과
`check` 뿐이다 — 함수 import 나 훅 같은 코드 경계는 두지 않는다.

selected.jsonl 한 줄 (좌표만, 본문 없음):
    {"chat_id", "event_time", "target_event_time", "n_prior", "llm_emotion_*"}
    event_time         불만 턴 N+1 의 시각 — ② 가 그 행을 찾는 키
    target_event_time  판정 대상 답변 턴 N 의 시각
    n_prior            N 앞에 있는 턴 수. ③ 이 턴 번호를 되살리고 C1 이 앞 턴 수를 센다

records.jsonl 한 줄 = conv-eval 턴 레코드 + chat_id + 조직 셋. `turn` 은 없다 — CSV 에
없어서다. ③ 이 (chat_id, event_time) 으로 selected 와 맞춰 번호를 붙인다. 그래서 event_time
문자열은 eval.jsonl → selected → records 까지 **가공 없이 그대로** 가야 한다.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from ragdiag.conv import Conversation, Turn, UserMeta, _parse_turn
from ragdiag.filters import FilterSpec, Step, apply_filter, parse_filter, render_steps

EMOTION_KEYS = ("llm_emotion_result", "llm_emotion_score", "llm_emotion_score_top1",
                "llm_emotion_alternatives")
# eval.jsonl 에서 비어 오는 키. 불만 턴에 None 으로 넣어 계약 대조가 "키가 없다" 로 울지 않게 한다.
EVAL_KEYS = ("llm_eval_result", "llm_eval_score", "llm_eval_alternatives")
# 본문 없는 앞 턴 자리. contracts.check_log 가 이 표시를 보고 대조에서 뺀다.
STUB_KEY = "_stub"
ORG_KEYS = ("job_grade", "db_dept_name", "db_job_name")
SELECTED_KEYS = ("chat_id", "event_time", "target_event_time", "n_prior")


class AssembleError(ValueError):
    """사람이 그대로 옮겨 적을 문장. 실데이터는 싣지 않는다 — 건수와 키만."""


# ---------------------------------------------------------------------------
# jsonl
# ---------------------------------------------------------------------------

def read_jsonl(path: str | Path) -> list[dict]:
    rows: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise AssembleError(f"{path}:{n} 을 읽을 수 없습니다: {e}\n"
                                    f"  한 줄에 JSON 객체 하나여야 합니다.") from e
            if not isinstance(row, dict):
                raise AssembleError(f"{path}:{n} 이 객체가 아닙니다: {type(row).__name__}")
            rows.append(row)
    return rows


def write_jsonl(path: str | Path, rows: Iterable[dict]) -> int:
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


# ---------------------------------------------------------------------------
# ① select — eval.jsonl 을 본문 없는 대화로 세워 기존 필터를 그대로 건다
# ---------------------------------------------------------------------------

def skeleton_conversations(rows: list[dict]) -> list[Conversation]:
    """eval.jsonl 행 → 본문 없는 Conversation. 필터가 읽는 필드만 산다.

    필터를 jsonl 용으로 다시 짜지 않는다 - 두 구현이 어긋나면 티가 안 난다. 같은
    `apply_filter` 에 같은 모양을 주면 재점수 · 단계별 탈락 보고까지 그대로 따라온다.
    조직 셋은 행마다 반복돼 오므로 첫 행 것을 쓴다.
    """
    by_chat: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        cid = row.get("chat_id")
        if not cid:
            continue
        by_chat[str(cid)].append(row)

    out: list[Conversation] = []
    for cid, chat_rows in by_chat.items():
        first = chat_rows[0]
        user = UserMeta(dept=first.get("db_dept_name") or "unknown",
                        job_grade=first.get("job_grade") or "unknown",
                        job_name=first.get("db_job_name") or "unknown")
        turns = sorted((_parse_turn(r) for r in chat_rows), key=lambda t: t.turn)
        out.append(Conversation(cid, user, turns))
    return out


def reject_eval_conditions(spec: FilterSpec) -> None:
    """eval.jsonl 에는 llm_eval_* 가 비어 온다. 조건이 있으면 조용히 0건이 되므로 멈춘다."""
    present = []
    if spec.eval_range is not None:
        present.append("eval_range")
    if spec.eval_letters:
        present.append("eval_labels")
    if present:
        raise AssembleError(
            f"filter.json 에 eval 조건이 있습니다 ({' / '.join(present)}).\n"
            f"  eval.jsonl 입력에서는 eval 점수를 아직 지원하지 않습니다 — "
            f"llm_eval_* 가 비어 있어 걸 수 없습니다.\n"
            f"  조건을 빼거나 conv-eval.json 입력으로 돌리세요.")


def duplicate_event_times(rows: list[dict]) -> int:
    """같은 chat 안에서 event_time 이 겹치는 행 수. 겹치면 ② 가 행을 못 가른다."""
    counts = Counter((str(r.get("chat_id")), str(r.get("event_time"))) for r in rows)
    return sum(c for c in counts.values() if c > 1)


@dataclass
class SelectResult:
    rows: list[dict] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    report: str = ""
    warnings: list[str] = field(default_factory=list)


def select(eval_rows: list[dict], spec: FilterSpec) -> SelectResult:
    reject_eval_conditions(spec)
    raw_by_key = {(str(r.get("chat_id")), int(r.get("turn", -1))): r for r in eval_rows
                  if r.get("chat_id")}
    conversations = skeleton_conversations(eval_rows)
    selected, steps = apply_filter(conversations, spec)

    out: list[dict] = []
    for s in selected:
        answer = s.conversation.turn_at(s.turn.turn - 1)
        raw = raw_by_key.get((s.conversation.chat_id, s.turn.turn), {})
        row = {"chat_id": s.conversation.chat_id,
               "event_time": s.turn.event_time,
               "target_event_time": answer.event_time,
               "n_prior": answer.turn - 1}
        for key in EMOTION_KEYS:
            if key in raw:
                row[key] = raw[key]
        out.append(row)

    result = SelectResult(rows=out, steps=steps, report=render_steps(spec, steps))
    dup = duplicate_event_times(eval_rows)
    if dup:
        result.warnings.append(
            f"같은 chat 안에서 event_time 이 겹치는 행이 {dup:,}건 있다 — ② lookup 이 "
            f"(chat_id, event_time) 으로 행을 못 가른다. 시각 해상도를 확인할 것.")
    blank = sum(1 for r in out if not r["event_time"] or not r["target_event_time"])
    if blank:
        result.warnings.append(f"event_time 이 빈 턴이 {blank:,}건 — ② 가 찾을 수 없다.")
    return result


# ---------------------------------------------------------------------------
# ③ records.jsonl + selected.jsonl → conv-eval 페이로드
# ---------------------------------------------------------------------------

def records_to_payload(records: list[dict], selected: list[dict]) -> dict:
    """두 jsonl 을 conv-eval.json 과 같은 중첩 모양으로 접는다.

    턴 번호는 selected 의 n_prior 에서 나온다 - 답변 턴 = n_prior+1, 불만 턴 = n_prior+2.
    records 에 없는 앞 턴(1..n_prior)은 본문 없는 자리만 채운다 - C1 이 "앞 턴이 k 개" 를
    셀 수 있게. 불만 턴에는 selected 의 llm_emotion_* 을 합친다 (② 는 복사하지 않는다).

    어긋남은 전부 AssembleError 다. 짝이 틀리면 조용히 엉뚱한 답변을 판정하게 되므로
    한 줄이라도 틀리면 멈춘다.
    """
    problems: list[str] = []

    # selected → (chat, event_time) 마다 턴 번호
    turn_no: dict[tuple[str, str], int] = {}
    emotion: dict[tuple[str, str], dict] = {}
    n_prior_max: dict[str, int] = {}
    for i, s in enumerate(selected):
        missing = [k for k in SELECTED_KEYS if k not in s]
        if missing:
            problems.append(f"selected[{i}] 에 {missing} 가 없다")
            continue
        cid = str(s["chat_id"])
        try:
            n_prior = int(s["n_prior"])
        except (TypeError, ValueError):
            problems.append(f"selected[{i}] 의 n_prior 가 정수가 아니다")
            continue
        for key, number in ((str(s["target_event_time"]), n_prior + 1),
                            (str(s["event_time"]), n_prior + 2)):
            prev = turn_no.get((cid, key))
            if prev is not None and prev != number:
                problems.append(f"selected: {cid} 의 event_time 하나에 턴 번호가 둘 "
                                f"({prev} 와 {number}) — n_prior 가 서로 안 맞는다")
            turn_no[(cid, key)] = number
        emotion[(cid, str(s["event_time"]))] = {k: s[k] for k in EMOTION_KEYS if k in s}
        n_prior_max[cid] = max(n_prior_max.get(cid, 0), n_prior)

    # records → 키로 찾는다
    by_key: dict[tuple[str, str], dict] = {}
    for i, r in enumerate(records):
        if "chat_id" not in r or "event_time" not in r:
            problems.append(f"records[{i}] 에 chat_id 나 event_time 이 없다")
            continue
        key = (str(r["chat_id"]), str(r["event_time"]))
        if key in by_key:
            problems.append(f"records: {key[0]} 의 event_time 하나에 행이 둘이다")
        by_key[key] = r

    missing = sorted(k for k in turn_no if k not in by_key)
    extra = sorted(k for k in by_key if k not in turn_no)
    if missing:
        problems.append(f"② 가 못 찾은 행 {len(missing):,}건 — 예: {missing[0][0]} "
                        f"@ {missing[0][1]}")
    if extra:
        problems.append(f"② 가 더 넣은 행 {len(extra):,}건 — 예: {extra[0][0]} @ {extra[0][1]}")
    if problems:
        raise AssembleError("records.jsonl 과 selected.jsonl 이 맞지 않습니다:\n  "
                            + "\n  ".join(problems))

    # 대화로 묶는다. 조직 셋은 레코드에서 — 없으면 unknown
    chats: dict[str, dict[int, dict]] = defaultdict(dict)
    org: dict[str, dict] = {}
    for (cid, event_time), number in turn_no.items():
        rec = dict(by_key[(cid, event_time)])
        rec["turn"] = number
        rec.pop("chat_id", None)                    # 대화 층으로 올라간다
        if (cid, event_time) in emotion:            # 불만 턴
            rec.update(emotion[(cid, event_time)])
            for k in EVAL_KEYS:
                rec.setdefault(k, None)
        chats[cid][number] = rec
        if cid not in org:
            org[cid] = {k: rec.get(k) for k in ORG_KEYS}
        for k in ORG_KEYS:
            rec.pop(k, None)

    users: list[dict] = []
    for cid, turns in chats.items():
        top = max(turns)
        for number in range(1, top + 1):
            turns.setdefault(number, {"turn": number, "user_question": "", "llm_response": None,
                                      STUB_KEY: True})
        users.append({**org[cid],
                      "conversations": [{"chat_id": cid,
                                         "turns": [turns[n] for n in sorted(turns)]}]})
    return {"metadata": {"source": "records.jsonl", "total_turns": sum(len(c) for c in chats.values())},
            "users": users}


def check(selected: list[dict], records: list[dict]) -> list[str]:
    """② 의 출력을 run 전에 검사한다. 돌려주는 것은 사람이 옮겨 적을 문장들. 비면 통과."""
    from ragdiag import contracts

    try:
        payload = records_to_payload(records, selected)
    except AssembleError as e:
        return [str(e)]
    report = contracts.check_log(payload)
    lines = [f"turn.{m.field}: {m.detail}" if m.layer == "turn" else f"{m.layer}.{m.field}: {m.detail}"
             for m in report.mismatches]
    return lines


# ---------------------------------------------------------------------------
# CLI — src/assemble.py 가 부른다
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog="assemble.py",
        description="eval.jsonl 입력 조립. select: 필터로 좌표를 고른다 / check: ② 의 출력을 검사한다")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("select", help="eval.jsonl + filter.json → selected.jsonl")
    s.add_argument("--eval-jsonl", required=True)
    s.add_argument("--filter-data", "--filter", dest="filter_data", required=True)
    s.add_argument("--out", default="selected.jsonl")

    c = sub.add_parser("check", help="selected.jsonl + records.jsonl 을 대조하고 계약을 검사한다")
    c.add_argument("selected")
    c.add_argument("records")

    x = sub.add_parser("example", help="합성 예시 네 파일(eval · filter · selected · records)을 폴더에 쓴다")
    x.add_argument("folder", nargs="?", default="pseudo_data/eval_jsonl")

    args = p.parse_args(argv)
    try:
        if args.command == "example":
            from ragdiag.fixtures.eval_jsonl import write_example

            for path in write_example(args.folder):
                print(path, file=sys.stderr)
            return 0
        if args.command == "select":
            spec = parse_filter(json.loads(Path(args.filter_data).read_text(encoding="utf-8")))
            result = select(read_jsonl(args.eval_jsonl), spec)
            print(result.report, file=sys.stderr)
            for w in result.warnings:
                print(f"경고: {w}", file=sys.stderr)
            n = write_jsonl(args.out, result.rows)
            print(f"{args.out}: {n:,}건", file=sys.stderr)
            return 0
        problems = check(read_jsonl(args.selected), read_jsonl(args.records))
        if problems:
            print("검사 실패:", file=sys.stderr)
            for line in problems:
                print(f"  {line}", file=sys.stderr)
            return 1
        print("통과 — run.py --conv-data <records.jsonl> --turns <selected.jsonl> 로 돌리면 된다",
              file=sys.stderr)
        return 0
    except (AssembleError, OSError, json.JSONDecodeError) as e:
        print(str(e), file=sys.stderr)
        return 2
