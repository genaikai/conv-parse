"""Step 1 관측 품질 채점.

관측 8개가 라우팅 전체를 좌우하는데 지금까지 실제 모델로 검증된 적이 없다.
케이스마다 **확실한 필드만** 채점한다 — 모든 필드에 정답을 억지로 붙이면
설계자의 추측을 정답으로 만드는 셈이 된다.

필드별 일치율을 따로 내는 게 핵심이다. 전체 평균만 보면 어느 관측이 약한지
보이지 않고, 약한 관측이 무엇이냐에 따라 고칠 프롬프트가 달라진다.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from ragdiag.report import _pad, _w
from ragdiag.schema import Observation


@dataclass
class FieldScore:
    field: str
    hits: int = 0
    total: int = 0
    misses: list[tuple[str, Any, Any]] = field(default_factory=list)  # (case, 기대, 실제)

    @property
    def rate(self) -> float:
        return self.hits / self.total if self.total else 0.0


def score_observation(
    case_id: str, expect: dict, obs: Optional[Observation], scores: dict[str, FieldScore]
) -> list[str]:
    """기대 필드만 채점하고, 어긋난 필드 이름을 돌려준다."""
    wrong = []
    for name, want in expect.items():
        entry = scores.setdefault(name, FieldScore(name))
        entry.total += 1
        got = getattr(obs, name, None) if obs else None
        # 정답이 하나로 확정되지 않는 케이스는 허용 집합으로 둔다. 억지로 하나를
        # 고르게 만들면 설계자의 추측이 정답이 된다.
        ok = got in want if isinstance(want, (set, frozenset)) else got == want
        if ok:
            entry.hits += 1
        else:
            entry.misses.append((case_id, want, got))
            wrong.append(name)
    return wrong


def render(scores: dict[str, FieldScore], per_case: dict[str, list[str]],
           errors: list[tuple[str, str]]) -> str:
    graded = [s for s in scores.values() if s.total]
    total_hits = sum(s.hits for s in graded)
    total_all = sum(s.total for s in graded)
    clean = [c for c, wrong in per_case.items() if not wrong]

    lines = [
        "=" * 78,
        "Step 1 관측 채점 (합성 골든셋 — 실데이터가 아님)",
        "=" * 78,
        "",
        f"  전 필드 일치        {total_hits}/{total_all}  "
        f"({total_hits / total_all:.0%})" if total_all else "  채점할 항목 없음",
        f"  모든 필드가 맞은 케이스  {len(clean)}/{len(per_case)}",
        "",
        "[1] 관측 필드별 일치율",
    ]
    width = max((_w(s.field) for s in graded), default=10) + 2
    for entry in sorted(graded, key=lambda s: (s.rate, -s.total)):
        bar = "█" * round(20 * entry.rate) + "·" * (20 - round(20 * entry.rate))
        lines.append(
            f"  {_pad(entry.field, width)}{entry.hits:>3}/{entry.total:<3} "
            f"{entry.rate:>5.0%}  {bar}"
        )

    misses = [(e.field, m) for e in graded for m in e.misses]
    if misses:
        lines += ["", "[2] 어긋난 판정"]
        for name, (case_id, want, got) in misses:
            lines.append(f"  {_pad(name, width)}{case_id:<10} 기대 {want!r} · 실제 {got!r}")

    if errors:
        lines += ["", f"[!] 관측 실패 {len(errors)}건"]
        for case_id, message in errors[:5]:
            lines.append(f"  {case_id}: {message}")

    lines += [
        "",
        "=" * 78,
        "이 점수는 합성 데이터 기준이다. 내가 만든 케이스이므로 실데이터의 표현 방식과",
        "다를 수 있고, 프롬프트를 이 셋에 맞춰 고치면 과대평가된다.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 2·3 채점
#
# 관측 채점과 층이 다르다. 저건 관측 하나하나를 재고, 이건 그 관측을 받아
# 문서와 대조하는 판정의 정확도를 잰다. 회귀셋(경로)으로도 대체되지 않는다.
# ---------------------------------------------------------------------------

@dataclass
class JudgeScore:
    verdict_hits: int = 0
    verdict_total: int = 0
    routing_hits: int = 0           # sufficient 여부만 맞았는가 - 라우팅은 이것만 본다
    citation_hits: int = 0          # 인용을 올바른 청크에서 뽑았는가
    citation_total: int = 0
    downgraded: int = 0             # 인용이 하나도 안 살아남아 insufficient 로 강등된 수
    fabricated: list[str] = field(default_factory=list)   # 원문 대조 실패
    misses: list[tuple] = field(default_factory=list)     # (id, 기대, 실제, note)
    by_category: dict[str, list[int]] = field(default_factory=dict)  # 범주 -> [맞음, 전체]


def score_sufficiency(case: dict, judgment, citation, score: JudgeScore) -> None:
    """verdict 와 인용 위치를 함께 본다.

    verdict 는 파이프라인과 같이 인용 대조를 거친 값(final_verdict)이다 - 살아남은 인용이
    없으면 insufficient 로 강등된 채 채점된다. 판정자가 맞는 verdict 를 내고도 인용을 훼손해
    강등되면 그건 파이프라인의 오답이고, 여기서 그대로 드러나야 한다.

    두 층으로 센다. 3분류(sufficient · partial · insufficient)와, 라우팅이 실제로 보는
    2분류(sufficient 인가 아닌가 - partial 과 insufficient 는 같은 case20 이다).
    케이스에 accept 가 있으면 그 집합 안이면 맞은 것으로 친다(정답이 애매한 케이스).

    verdict 만 맞히고 엉뚱한 청크를 인용했다면 우연히 맞은 것이다. 그래서
    expect_cited 가 있는 케이스는 인용 위치도 채점한다.
    """
    from ragdiag.verify import final_verdict

    score.verdict_total += 1
    got = final_verdict(judgment, citation)
    if got != judgment.verdict:
        score.downgraded += 1
    accept = set(case.get("accept") or {case["expect_verdict"]})
    hit = got in accept
    if hit:
        score.verdict_hits += 1
    else:
        want = "/".join(sorted(accept))
        score.misses.append((case["id"], want, got, case["note"]))
    if (got == "sufficient") in {v == "sufficient" for v in accept}:
        score.routing_hits += 1
    cat = score.by_category.setdefault(case.get("category", "short"), [0, 0])
    cat[0] += hit
    cat[1] += 1

    # 지어낸 인용은 원문 대조에서 걸린다. 하나라도 폐기됐으면 기록한다.
    if citation and citation.dropped:
        score.fabricated.append(f"{case['id']} ({len(citation.dropped)}건)")

    wanted = case.get("expect_cited")
    if wanted is not None:
        score.citation_total += 1
        cited = {e.chunk_index for e in (citation.kept if citation else [])}
        if cited & wanted:
            score.citation_hits += 1
        else:
            score.misses.append(
                (case["id"], f"청크{sorted(wanted)} 인용", f"청크{sorted(cited) or '없음'}",
                 case["note"]))


def render_judge(suf: JudgeScore, gnd: JudgeScore) -> str:
    lines = ["", "=" * 78, "Step 2·3 판정 채점", "=" * 78, ""]

    def block(title: str, s: JudgeScore, extra: str = "") -> None:
        if not s.verdict_total:
            lines.append(f"  {title}: 채점할 항목 없음")
            return
        rate = s.verdict_hits / s.verdict_total
        bar = "█" * round(20 * rate) + "·" * (20 - round(20 * rate))
        lines.append(f"  {_pad(title, 22)}{s.verdict_hits:>3}/{s.verdict_total:<3} "
                     f"{rate:>5.0%}  {bar}{extra}")

    block("충족도 verdict (3분류)", suf)
    if suf.verdict_total:
        rate = suf.routing_hits / suf.verdict_total
        bar = "█" * round(20 * rate) + "·" * (20 - round(20 * rate))
        lines.append(f"  {_pad('sufficient 여부 (2분류)', 22)}{suf.routing_hits:>3}/"
                     f"{suf.verdict_total:<3} {rate:>5.0%}  {bar}   ← 라우팅이 보는 것")
    if suf.citation_total:
        rate = suf.citation_hits / suf.citation_total
        bar = "█" * round(20 * rate) + "·" * (20 - round(20 * rate))
        lines.append(f"  {_pad('인용 위치', 22)}{suf.citation_hits:>3}/"
                     f"{suf.citation_total:<3} {rate:>5.0%}  {bar}")
    if suf.downgraded:
        lines.append(f"  {_pad('인용 실패로 강등', 22)}{suf.downgraded:>3}건")
    block("근거 활용", gnd)
    if len(suf.by_category) > 1:
        lines.append("")
        lines.append("  충족도 범주별")
        for cat, (hits, total) in sorted(suf.by_category.items(), key=lambda kv: kv[1][0] / kv[1][1]):
            lines.append(f"    {_pad(cat, 12)}{hits:>3}/{total:<3} {hits / total:>5.0%}")

    lines.append("")
    lines.append(f"  지어낸 인용(원문 대조 실패): "
                 f"{', '.join(suf.fabricated) if suf.fabricated else '없음'}")
    if suf.fabricated:
        lines.append("    └ 이 값이 크면 라벨 분포보다 먼저 봐야 한다. 사전지식 오염 신호다.")

    misses = suf.misses + gnd.misses
    if misses:
        lines.append("")
        lines.append("  어긋난 판정")
        for case_id, want, got, note in misses:
            lines.append(f"    {_pad(case_id, 10)}기대 {want!r} · 실제 {got!r}   ({note})")
    return "\n".join(lines)
