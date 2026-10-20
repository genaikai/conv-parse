"""데이터 실태 조사 — 진단 전에 무엇이 들어있는지부터 본다.

필터 조건은 분포를 보고 정해야 한다. "eval_score 40점 미만"이 10건을 거를지 3000건을
거를지 모르는 채로 임계값을 쓰면, 돌려보고 나서야 알게 된다. 이 도구는 필터를 걸기 전에
각 축이 어떻게 생겼는지, 어떤 조건이 몇 건을 남기는지 먼저 보여준다.

LLM을 쓰지 않는다. 순수 집계다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Optional, Sequence

from ragdiag.conv import Conversation, Turn
from ragdiag.textfmt import pad, text_width



@dataclass
class Issue:
    kind: str
    conversation_id: str
    detail: str


def check_integrity(conversations: list[Conversation]) -> list[Issue]:
    """진단 전에 데이터가 앞뒤가 맞는지 본다.

    전부 파생 관계에서 나오는 검사다. trace_matched 는 턴 수에서, eval 라벨의 유무는
    직전 턴의 존재에서 계산할 수 있다. 계산값과 선언값이 어긋나면 파일이 잘렸거나
    턴이 누락된 것이고, 그 상태로 진단하면 결과를 믿을 수 없다.
    """
    issues: list[Issue] = []
    for conv in conversations:
        declared = conv.declared_multi_turn
        if declared is None and conv.turns:
            issues.append(Issue(
                "trace_inconsistent", conv.conversation_id,
                "한 대화 안에서 trace_matched 값이 엇갈림"))
        elif declared is not None and declared != conv.actual_multi_turn:
            issues.append(Issue(
                "trace_mismatch", conv.conversation_id,
                f"trace_matched={declared} 인데 턴은 {len(conv.turns)}개 "
                f"— 턴이 누락됐을 수 있음"))

        numbers = [t.turn for t in conv.turns]
        if numbers and numbers != list(range(1, len(numbers) + 1)):
            issues.append(Issue(
                "turn_numbering", conv.conversation_id,
                f"턴 번호가 1..n 이 아님: {numbers}"))

        for turn in conv.turns:
            # eval 은 직전 턴을 참고해 계산되므로 turn 1에는 있을 수 없다.
            if turn.turn == 1 and turn.is_followup:
                issues.append(Issue(
                    "eval_on_first_turn", conv.conversation_id,
                    f"turn 1에 eval 라벨({turn.eval_result})이 있음"))
            if turn.turn >= 2 and not turn.is_followup:
                issues.append(Issue(
                    "eval_missing", conv.conversation_id,
                    f"turn {turn.turn}에 eval 라벨이 없음 — 평가 실패 또는 턴 누락"))
    return issues


def _bar(count: int, total: int, width: int = 28) -> str:
    if total <= 0:
        return ""
    filled = round(width * count / total)
    return "█" * filled + "·" * (width - filled)


def _dist(title: str, counter: Counter, total: int, limit: int = 12) -> list[str]:
    if not counter:
        return [f"  {title}: (값 없음)"]
    lines = [f"  {title}"]
    name_width = min(28, max(text_width(str(k)) for k in counter))
    for name, count in counter.most_common(limit):
        label = str(name) if str(name) else "(비어 있음)"
        lines.append(
            f"    {pad(label, name_width + 2)}{count:>6}  "
            f"{count / total:>5.1%}  {_bar(count, total)}"
        )
    remaining = len(counter) - limit
    if remaining > 0:
        lines.append(f"    … 그 외 {remaining}종")
    return lines


def _numeric(title: str, values: Sequence[float]) -> list[str]:
    present = [v for v in values if v is not None]
    if not present:
        return [f"  {title}: (값 없음)"]
    ordered = sorted(present)
    n = len(ordered)

    def q(p: float) -> float:
        return ordered[min(n - 1, int(n * p))]

    return [
        f"  {title}  n={n}  결측 {len(values) - n}",
        f"    최소 {ordered[0]:.1f} · p25 {q(.25):.1f} · 중앙 {q(.5):.1f} · "
        f"p75 {q(.75):.1f} · p90 {q(.9):.1f} · 최대 {ordered[-1]:.1f}",
    ]


def _histogram(values: Sequence[float], bins: int = 10) -> list[str]:
    present = [v for v in values if v is not None]
    if not present:
        return []
    low, high = min(present), max(present)
    if high == low:
        return [f"    전부 {low:.1f}"]
    width = (high - low) / bins
    counts = Counter(min(bins - 1, int((v - low) / width)) for v in present)
    lines = []
    for i in range(bins):
        lo, hi = low + i * width, low + (i + 1) * width
        c = counts.get(i, 0)
        lines.append(
            f"    {lo:>6.1f}~{hi:<6.1f} {c:>6}  {_bar(c, len(present))}"
        )
    return lines


def survey(conversations: list[Conversation], metadata: Optional[dict] = None) -> str:
    turns: list[Turn] = [t for c in conversations for t in c.turns]
    followups = [t for t in turns if t.is_followup]

    out = [
        "=" * 78,
        "데이터 실태 조사 (LLM 호출 없음)",
        "=" * 78,
        "",
        "[1] 규모",
        # 사용자 식별자가 로그에서 없어졌다. 셀 수 없는 것을 0명으로 찍으면
        # "사용자가 없다" 로 읽히므로 축 자체를 뺀다.
        f"  대화 {len(conversations)}건 · 턴 {len(turns)}개 · "
        f"부서 {len({c.user.dept for c in conversations})}개",
    ]
    if metadata:
        declared_users = metadata.get("total_users")
        declared_turns = metadata.get("total_turns")
        actual_users = None
        # metadata 와 실제가 어긋나면 파일이 잘렸거나 중복이 있다는 뜻이다.
        for name, declared, actual in [
            ("total_users", declared_users, actual_users),
            ("total_turns", declared_turns, len(turns)),
        ]:
            # 셀 수 없는 축은 대조하지 않는다. 비교 대상이 없는데 "불일치" 를
            # 찍으면 멀쩡한 로그가 깨진 것으로 보인다.
            if declared is not None and actual is not None:
                mark = "" if declared == actual else "   <-- 불일치"
                out.append(f"  metadata.{name}: 선언 {declared} / 실제 {actual}{mark}")

    lengths = Counter(len(c.turns) for c in conversations)
    out += ["", "[2] 대화당 턴 수"]
    for n in sorted(lengths):
        out.append(f"    {n:>3}턴  {lengths[n]:>6}건  {_bar(lengths[n], len(conversations))}")

    # 진단 케이스가 될 수 있는 것은 후속 턴뿐이다. 첫 턴은 비판할 답변이 없다.
    out += [
        "",
        "[3] 진단 가능 후보",
        f"  전체 턴                {len(turns):>6}",
        f"  후속 턴 (eval 라벨 있음) {len(followups):>6}  "
        f"{len(followups) / max(len(turns), 1):.1%}",
        "  └ 이 후속 턴들이 필터의 대상이다. 첫 턴은 직전 답변이 없어 제외된다.",
    ]

    out += ["", "[4] llm_eval_result — 후속 질문의 성격"]
    out += _dist("라벨 분포", Counter(t.eval_result for t in followups), len(followups))
    out += [""]
    out += _numeric("llm_eval_score", [t.eval_score for t in followups])
    out += _histogram([t.eval_score for t in followups])

    out += ["", "[5] llm_emotion_result — 사용자 감정"]
    with_emotion = [t for t in followups if t.emotion_result]
    out += _dist("라벨 분포", Counter(t.emotion_result for t in with_emotion),
                 max(len(with_emotion), 1))
    out += [""]
    out += _numeric("llm_emotion_score", [t.emotion_score for t in followups])
    out += _histogram([t.emotion_score for t in followups])

    out += ["", "[6] retrieved_data"]
    empty = sum(1 for t in turns if not t.retrieved)
    out += [
        f"  검색 결과 없음          {empty:>6}  {empty / max(len(turns), 1):.1%}",
        f"  검색 결과 있음          {len(turns) - empty:>6}",
    ]
    chunk_counts = [len(t.retrieved) for t in turns if t.retrieved]
    if chunk_counts:
        out += _numeric("  청크 수", chunk_counts)

    # trace_matched 는 턴 수에서 계산되는 파생값이라 분포를 세는 건 의미가 없다.
    # 선언값과 실제가 어긋나는지만 본다.
    issues = check_integrity(conversations)
    out += ["", "[7] 무결성"]
    if not issues:
        out.append("  이상 없음")
    else:
        by_kind = Counter(i.kind for i in issues)
        for kind, count in by_kind.most_common():
            out.append(f"  {pad(kind, 24)}{count:>6}건")
            for issue in [i for i in issues if i.kind == kind][:3]:
                out.append(f"      {issue.conversation_id[:24]:<26} {issue.detail}")
        out.append("  └ 턴이 누락된 대화가 있으면 진단 결과를 믿을 수 없다.")

    out += ["", "[8] 부서 · 직급"]
    out += _dist("부서", Counter(c.user.dept for c in conversations), len(conversations), 8)
    out += _dist("직급", Counter(c.user.job_grade for c in conversations),
                 len(conversations), 8)

    out += [
        "",
        "=" * 78,
        "필터를 걸기 전에 [4]와 [5]를 보고 조건을 정하세요.",
        "조건을 걸었을 때 몇 건이 남는지는 --eval-label / --emotion-label /",
        "--max-eval-score / --max-emotion-score 를 함께 주면 이어서 보여줍니다.",
    ]
    return "\n".join(out)


def preview_filter(
    conversations: list[Conversation],
    eval_labels: Optional[set[str]] = None,
    emotion_labels: Optional[set[str]] = None,
    max_eval_score: Optional[float] = None,
    max_emotion_score: Optional[float] = None,
) -> str:
    """조건을 걸었을 때 몇 건이 남는지 미리 본다.

    조건을 하나씩 누적하면서 각 단계에서 몇 건이 떨어지는지 보여준다.
    한 번에 다 걸고 "3건 남았다"만 보면 어느 조건이 과했는지 알 수 없다.
    """
    followups = [
        (c, t) for c in conversations for t in c.turns
        if t.is_followup and c.turn_at(t.turn - 1) is not None
    ]
    lines = ["=" * 78, "필터 미리보기", "=" * 78, "",
             f"  후속 턴 (직전 턴 존재)                  {len(followups):>6}"]

    current = followups
    steps = [
        ("eval_result 포함", eval_labels,
         lambda ct: ct[1].eval_result in eval_labels),
        ("emotion_result 포함", emotion_labels,
         lambda ct: ct[1].emotion_result in emotion_labels),
        (f"eval_score <= {max_eval_score}", max_eval_score,
         lambda ct: ct[1].eval_score is not None and ct[1].eval_score <= max_eval_score),
        (f"emotion_score <= {max_emotion_score}", max_emotion_score,
         lambda ct: ct[1].emotion_score is not None
         and ct[1].emotion_score <= max_emotion_score),
    ]
    for name, condition, predicate in steps:
        if condition is None:
            continue
        before = len(current)
        current = [ct for ct in current if predicate(ct)]
        lines.append(
            f"  {pad(name, 36)}{len(current):>6}   (-{before - len(current)})"
        )

    lines += ["", f"  최종 진단 대상                         {len(current):>6}"]
    if current:
        lines += ["", "  남은 케이스 미리보기 (최대 5건)"]
        for conv, turn in current[:5]:
            question = turn.user_question[:52]
            lines.append(
                f"    {conv.conversation_id[:16]:<18} turn {turn.turn:<3} "
                f"{turn.eval_result or '-':<10} {question}"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 청크 풀 계측 — LLM 호출 0
#
# 풀 크기는 파싱 시점에 정해진다. 그런데 지금껏 그걸 찍는 데가 없어서, "얼마나
# 커졌나" 를 알려면 전체 실행을 끝내고 결과 파일의 chunk_data 길이를 세야 했다
# (features/carried 의 설명이 그렇게 적혀 있다). 에어갭에서는 그게 비싸다 -
# 풀이 터지면 ⑦ 가 깨지면서 알게 되고, 그 시점에 GPU 시간은 이미 쓴 뒤다.
#
# 그래서 LLM 을 켜기 전에 숫자부터 본다. 상한을 걸지 말지는 이 숫자를 보고 정한다.
# ---------------------------------------------------------------------------

def chunk_report(cases: Sequence) -> str:
    """고른 케이스들의 청크 풀이 얼마나 큰가. `--dry-run` 에서 찍는다.

    청크 **개수**와 **문자 수**를 같이 낸다. 둘이 갈리기 때문이다 - 도구 결과는
    청크 하나가 JSON 덩어리라 개수는 안 늘고 문자만 폭증할 수 있고, 그쪽이
    프리필 비용과 "lost in the middle" 을 정하는 값이다.

    Step 2 골든셋이 문서 10~15개 기준이라, 중앙값이 거기서 멀어지면 충족도 판정이
    골든셋에서 재 본 적 없는 영역으로 들어간 것이다.
    """
    if not cases:
        return "  (케이스 없음)"
    counts = [len(c.rag_chunks) for c in cases]
    chars = [sum(len(x) for x in c.rag_chunks) for c in cases]
    lines = ["청크 풀 (LLM 호출 없음)"]
    lines += _numeric("청크 개수", counts)
    # 개수는 정수라 폭이 좁으면 막대가 "2.0~2.2" 같은 빈 칸으로 열 줄 나간다.
    # 화면으로 읽는 블록이라 그 열 줄이 정작 볼 줄을 밀어낸다.
    if max(counts) - min(counts) >= 10:
        lines += _histogram(counts)
    lines += [""]
    lines += _numeric("문자 수  ", chars)
    empty = sum(1 for n in counts if n == 0)
    if empty:
        lines += ["", f"  청크 0개 {empty}건 ({empty / len(counts):.0%}) "
                      f"— 검색 결과가 없었다는 뜻이다 (case21 후보)"]
    return "\n".join(lines)


def chunk_metric(cases: Sequence) -> str:
    """RUN SUMMARY 한 줄. 결과를 가지고 나올 수 없으니 요약에 숫자를 남긴다."""
    if not cases:
        return "없음"
    counts = sorted(len(c.rag_chunks) for c in cases)
    chars = sorted(sum(len(x) for x in c.rag_chunks) for c in cases)
    mid = len(counts) // 2
    return (f"중앙 {counts[mid]}개 / {chars[len(chars) // 2]:,}자 · "
            f"최대 {counts[-1]}개 / {chars[-1]:,}자")
