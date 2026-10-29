"""판정 결과(v4)를 훑어보는 대시보드.

  python -m streamlit run <저장소>/src/dashboard.py

--result 를 생략하면 ./output 에서 가장 최근 결과(<시각>_<로그>_<필터>.json)를 고른다.
조직 분류를 붙이려면:

  python -m streamlit run <저장소>/src/dashboard.py -- \\
      --dept-class configs/dept_class.json \\
      --job-class  configs/job_class.json

**src/ 직하에 있어야 한다.** streamlit 은 스크립트가 있는 디렉터리를 sys.path[0] 에 넣는다.
src/ragdiag/ 안에 두면 그 디렉터리가 올라가고 src/ 는 안 올라가서 `import ragdiag` 가 자기
자신을 못 찾는다. 서버는 정상으로 뜨고 헬스체크도 통과해서 로그만 봐서는 멀쩡해 보인다.

에어갭 장비에서 돌아야 하므로 streamlit·pandas 둘만 추가로 필요하다. 차트는 altair 로
그리고(streamlit 이 이미 의존하는 패키지) 히트맵은 CSS 를 직접 만든다.

화면 넷: 분포(묶음 × 들어온 길 · 어디서 멈췄나 · 어디서 막혔나) · 조직(묶음 crosstab) ·
개별 케이스(결론 → 지나온 단계 → 본문) · 근거 보강(근거 묶음의 질문 목록).
설계: docs/design/decision_tree_v4.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def _bail(message: str) -> None:
    """무엇을 하라는지까지 적고 멈춘다. 실행 환경에서는 화면에 적힌 것이 전부다."""
    print(f"\n{message}\n", file=sys.stderr)
    raise SystemExit(2)


try:
    import altair as alt
    import pandas as pd
    import streamlit as st
except ModuleNotFoundError as e:
    _bail(f"대시보드에 필요한 {e.name} 이 없습니다.\n\n"
          f"  {sys.executable} -m pip install -r "
          f"{Path(__file__).resolve().parents[1] / 'requirements-dashboard.txt'}\n\n"
          "분류 파이프라인(src/run.py)에는 필요 없습니다. 그래서 "
          "requirements.txt 와 나눠 뒀습니다 —\n"
          "에어갭 장비에 설치할 것을 늘리지 않기 위해서입니다.")

if not st.runtime.exists():
    _bail("이 파일은 streamlit 이 실행합니다. python 으로 직접 돌리면\n"
          "경고만 나오고 화면이 뜨지 않습니다.\n\n"
          f"  {sys.executable} -m streamlit run {sys.argv[0]}\n\n"
          "결과 경로를 생략하면 ./output 의 최신 것을 봅니다. 인자를 주려면\n"
          "`--` 뒤에 붙입니다 — 앞은 streamlit 이 먹습니다.\n"
          "`python -m streamlit` 은 PATH 를 타지 않습니다 — `streamlit` 만 쓰면\n"
          "venv 를 activate 하지 않았을 때 command not found 가 납니다.")

from ragdiag import questions as qs
from ragdiag import taxonomy as tx

# streamlit 1.49 에서 width= 가 use_container_width= 를 대체했다. 둘 다 받는다.
_VERSION = tuple(int(x) for x in re.findall(r"\d+", st.__version__)[:2])
WIDE = {"width": "stretch"} if _VERSION >= (1, 49) else {"use_container_width": True}

BUCKETS = [b.name for b in tx.BUCKETS.values()]            # 정상 · 사용자 · 근거 · 생성 · 시스템 · 검토
OWNER = {b.name: b.owner for b in tx.BUCKETS.values()}
NORMAL, REVIEW = tx.name("normal"), tx.name(tx.REVIEW)
EVIDENCE, GENERATION = tx.name("evidence"), tx.name("generation")
SLOT_NAMES = [korean for _, korean in qs.SLOTS]
DEFAULT_OUTPUT_DIR = "output"

# 판별된 로그 필드 -> 화면의 축. 결과 파일의 axes 가 이미 이 이름이다.
LOG_FIELD_TO_COLUMN = {"db_dept_name": "부서", "job_grade": "직급", "db_job_name": "직무"}
ORG_AXES = ("부서", "직급", "직무")


# ---------------------------------------------------------------------------
# 인자 · 설정 · 파일
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="설정 YAML. 생략하면 configs/env.yaml")
    parser.add_argument("--result", help="판정 결과 JSON. 생략하면 --output-dir 의 최신 것")
    parser.add_argument("--output-dir", help="여기서 가장 최근 결과를 고른다")
    parser.add_argument("--dept-class", help="부서 분류 체계 JSON")
    parser.add_argument("--job-class", help="직무·직급 분류 체계 JSON (어느 축인지는 값으로 판별)")
    known, _ = parser.parse_known_args(sys.argv[1:])
    # 우선순위는 파이프라인과 같다: CLI > 설정 > 기본값.
    config = _load_config(known.config)
    known.output_dir = known.output_dir or config.get("paths.output_dir") or DEFAULT_OUTPUT_DIR
    known.dept_class = known.dept_class or config.get("paths.dept_class")
    known.job_class = known.job_class or config.get("paths.job_class")
    known.config_source = config.source
    if not known.result:
        known.result = newest_result(known.output_dir)
    return known


def _load_config(path: str | None):
    """설정을 읽는다. 못 읽어도 대시보드는 떠야 한다 — 화면을 보는 도구다."""
    from ragdiag.config import Config, ConfigError, load

    target = path or ("configs/env.yaml" if Path("configs/env.yaml").exists() else None)
    if not target:
        return Config()
    try:
        return load(target)
    except ConfigError as e:
        st.warning(f"설정을 읽지 못해 기본값으로 띄웁니다.\n\n{e}")
        return Config()


_STAMP = re.compile(r"(\d{8}-\d{6})")


def result_files(out_dir: str) -> list[Path]:
    """결과 파일들을 오래된 것부터. 요약(_summary.txt)은 json 이 아니라 안 걸린다."""
    found = [p for p in Path(out_dir).glob("*.json")
             if p.name.startswith("conv_parsed_") or _STAMP.match(p.name)]
    return sorted(found, key=lambda p: (_STAMP.search(p.name) or [""])[0])


def newest_result(out_dir: str) -> str:
    found = result_files(out_dir)
    if found:
        return str(found[-1])
    return str(Path(out_dir) / "conv_parsed.json")


@st.cache_data
def load(path: str) -> pd.DataFrame:
    """결과 파일의 turns 를 턴 하나 = 한 행으로. 본문이 없는 파일(--no-text)도 연다."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = []
    for t in raw.get("turns", []):
        axes = t.get("axes") or {}
        v = t.get("verdict") or {}
        text = t.get("text") or {}
        flags = t.get("flags") or {}
        rows.append({
            "대화": t.get("chat_id", "-"), "턴": t.get("turn"),
            "부서": axes.get("부서") or "-", "직급": axes.get("직급") or "-", "직무": axes.get("직무") or "-",
            "answered_by": axes.get("answered_by", ""), "ask_on": axes.get("ask_on", ""),
            "묶음": v.get("bucket", "오류" if t.get("error") else ""),
            "확실": bool(v.get("sure", False)),
            "멈춘곳": v.get("stopped_at", ""),
            "단계": (v.get("stopped_at", "") or "").split(" · ")[0],
            "이유": v.get("because", ""),
            "근거위치": " · ".join(v.get("where") or []),
            "앞턴누락": flags.get("앞 턴 누락") is True,
            "개인정보": bool(flags.get("질문에 개인정보")),
            "재구성": int(flags.get("history 재구성 턴 수") or 0),
            "질문": text.get("question", ""), "답변": text.get("answer", ""),
            "불만": text.get("followup", ""),
            "본문": bool(text),
            "오류": t.get("error", ""),
            "_원본": t,
        })
    return pd.DataFrame(rows)


@st.cache_data
def flat_records(path: str) -> list[dict]:
    """조직 필드 판별용 — 턴마다 조직 셋을 로그 필드 이름으로 돌려 놓는다."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    back = {v: k for k, v in LOG_FIELD_TO_COLUMN.items()}
    return [{back[k]: v for k, v in (t.get("axes") or {}).items() if k in back}
            for t in raw.get("turns", [])]


@st.cache_data
def load_org(dept_path: str | None, job_path: str | None, records: list[dict]):
    """조직 분류를 읽고 어느 필드에 붙는지 값으로 판별한다. 파일 이름으로 추측하지 않는다."""
    from ragdiag.org import detect_field, load_classification

    result = {}
    for path in (dept_path, job_path):
        if not path or not Path(path).exists():
            continue
        table = load_classification(path)
        chosen, scores = detect_field(records, table)
        label = LOG_FIELD_TO_COLUMN.get(chosen or "")
        if not label:
            result[Path(path).stem] = {"table": table, "field": None, "scores": scores, "orphan": chosen}
            continue
        result[label] = {"table": table, "field": chosen, "scores": scores}
    return result


def download(df: pd.DataFrame, name: str) -> None:
    """utf-8-sig 인 이유는 엑셀이다. BOM 이 없으면 한글이 깨진 채 열린다."""
    st.download_button("CSV 내려받기", data=df.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"{name}.csv", mime="text/csv", key=f"dl-{name}")


def heat(value: float) -> str:
    """0~1 을 배경색으로. matplotlib 을 쓰지 않는다."""
    if not isinstance(value, (int, float)) or pd.isna(value):
        return ""
    ratio = max(0.0, min(1.0, float(value)))
    if ratio < 0.02:
        return "color: #b0b0b0"
    weight = ratio ** 0.7
    r, g, b = int(255 - 200 * weight), int(255 - 90 * weight), int(255 - 105 * weight)
    text = "#ffffff" if weight > 0.55 else "#1a1a1a"
    return f"background-color: rgb({r},{g},{b}); color: {text}"


def bucket_tooltips(columns, numeric: bool = True) -> dict:
    column = st.column_config.NumberColumn if numeric else st.column_config.TextColumn
    return {name: column(name, help=f"고칠 곳: {OWNER[name]}")
            for name in columns if isinstance(name, str) and name in OWNER}


def crosstab(df: pd.DataFrame, axis: str, column: str = "묶음") -> pd.DataFrame:
    table = pd.crosstab(df[axis], df[column])
    table = table[[c for c in BUCKETS if c in table.columns]
                  + [c for c in table.columns if c not in BUCKETS]]
    table["계"] = table.sum(axis=1)
    return table.sort_values("계", ascending=False)


# ---------------------------------------------------------------------------
# 화면
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="대화 로그 실패 판정", layout="wide")
    args = parse_args()
    st.title("대화 로그 실패 판정")

    runs = result_files(args.output_dir)[::-1]
    path = Path(args.result)
    with st.sidebar:
        names = [str(r) for r in runs]
        if str(path) not in names:
            names.insert(0, str(path))
        if names:
            picked = st.selectbox("실행 결과", names, index=0,
                                  format_func=lambda n: Path(n).stem.replace("conv_parsed_", ""),
                                  help="<시각>_<로그>_<필터>. 최신이 위에 온다")
            path = Path(picked)
        st.divider()

    if not path.exists():
        st.error(f"결과 파일이 없습니다: {path}\n\n먼저 src/run.py 로 판정을 돌리세요.")
        st.stop()

    df = load(str(path))
    org = load_org(args.dept_class, args.job_class, flat_records(str(path)))
    if df.empty:
        st.warning("판정된 턴이 없습니다.")
        st.stop()

    others = len(runs) - 1
    stamp = f"  ·  다른 실행 {others}건 더 있음" if others > 0 else ""
    st.caption(f"{path}  ·  {len(df)}건{stamp}  ·  설정 {getattr(args, 'config_source', '(기본값)')}")

    # --- 좁히기 -----------------------------------------------------------------
    def _keep_valid(chosen: list[str], options: list[str]) -> list[str]:
        return [c for c in chosen if c in options]

    def cascade(label: str) -> "set[str] | None":
        """대분류 → 중분류 → 소분류 로 좁혀 고른다. 체계가 안 붙은 축은 값 하나만 고른다."""
        from ragdiag.org import allowed_values, level_options, observed_tree

        info = org.get(label)
        table = info["table"] if info and info["field"] else None
        values = [str(v) for v in df[label].unique()]
        if table is None:
            chosen = st.multiselect(label, sorted(values))
            return set(chosen) if chosen else None
        tree = observed_tree(table, values)
        with st.container(border=True):
            st.markdown(f"**{label}**")
            majors = st.multiselect("대분류", level_options(tree, [], [])[0], key=f"{label}:대분류")
            middles: list[str] = []
            if majors:
                options = level_options(tree, majors, [])[1]
                middles = _keep_valid(st.multiselect("중분류", options, key=f"{label}:중분류"), options)
            items: list[str] = []
            if middles:
                options = level_options(tree, majors, middles)[2]
                items = _keep_valid(st.multiselect("소분류", options, key=f"{label}:소분류"), options)
        return allowed_values(tree, majors, middles, items)

    with st.sidebar:
        st.header("좁히기")
        narrowed = {axis: cascade(axis) for axis in ORG_AXES}
        buckets = st.multiselect("묶음", [b for b in BUCKETS if b in set(df["묶음"])])
        for b in buckets:
            st.caption(f"**{b}** — 고칠 곳: {OWNER[b]}")
        sure = st.radio("확신", ["전부", "확실만", "검토만"], horizontal=True)
        if org:
            st.divider()
            st.caption("조직 분류")
            for label, info in org.items():
                if info["field"]:
                    cov = info["scores"][info["field"]]
                    st.caption(f"· {label} ← `{info['field']}` {cov.rate:.0%}")
                elif info.get("orphan"):
                    st.caption(f"· {label} → `{info['orphan']}` 에 붙었지만 화면에 그 축이 없다")
                else:
                    st.caption(f"· {label} 매칭 실패 — 원래 값으로 표시")

    view = df[df["오류"] == ""]
    for column, chosen in [*narrowed.items(), ("묶음", buckets or None)]:
        if chosen is not None:
            view = view[view[column].isin(chosen)]
    if sure == "확실만":
        view = view[view["확실"]]
    elif sure == "검토만":
        view = view[~view["확실"]]
    if view.empty:
        st.warning("조건에 맞는 케이스가 없습니다. 좁히기를 완화하세요.")
        st.stop()

    # --- 판정 건강 (탭 밖) -------------------------------------------------------
    st.subheader("판정 건강")
    st.caption("묶음 분포보다 먼저 볼 숫자다. 여기가 나쁘면 아래 집계를 믿을 수 없다.")
    n_normal = int((view["묶음"] == NORMAL).sum())
    n_review = int((view["묶음"] == REVIEW).sum())
    n_system = int((view["묶음"] == tx.name("system")).sum())
    n_errors = int((df["오류"] != "").sum())
    n_missing = int(view["앞턴누락"].sum())
    cols = st.columns(6)
    cols[0].metric("판정된 턴", len(view), delta=f"-{n_normal} 정상" if n_normal else None,
                   delta_color="off", help="정상을 빼면 실제 실패 건수가 된다.")
    cols[1].metric("정상", n_normal, help="후속 발화가 앞 답변을 문제 삼지 않은 턴. 챗봇이 아니라 필터를 가리킨다.")
    cols[2].metric("검토", n_review, help="kev 가 확신하지 못한 턴. 어느 문항에서 막혔는지가 분포 탭에 있다.")
    cols[3].metric("시스템", n_system, help="자원 부족 · 빈 답변 · 붕괴 · 거절 · 읽을 수 없음 · 잘림. 모델 품질이 아니다.")
    cols[4].metric("오류", n_errors, help="판정 중 예외 · 낙오. 결과 파일의 error 필드.")
    cols[5].metric("앞 턴 누락", n_missing, help="history_chat 에 앞 턴이 빠진 턴. 많으면 사용자 묶음 집계를 보류할 것.")
    if n_normal:
        st.info(f"필터가 고른 {len(view)}건 중 {n_normal}건({n_normal / len(view):.0%})은 불만이 아니었다. "
                "실패율에서 빼고 읽고, 이 비율이 크면 필터를 좁힐 신호다.", icon="✅")
    if n_review and n_review / len(view) > 0.2:
        st.warning(f"검토가 {n_review / len(view):.0%} 다. 막힌 문항의 기준문을 먼저 손볼 것 (분포 탭).")

    tab_dist, tab_org, tab_case, tab_gap = st.tabs(["분포", "조직", "개별 케이스", "근거 보강"])
    with tab_dist:
        _distribution(view)
    with tab_org:
        _by_org(view, org)
    with tab_case:
        _cases(view)
    with tab_gap:
        _evidence_gaps(view)


# ---------------------------------------------------------------------------
# 분포
# ---------------------------------------------------------------------------

def bar_height(bars: int) -> int:
    return max(160, 26 * bars + 60)


def hbar(data: pd.DataFrame, y: str, x: str, color: str, height: int) -> None:
    chart = (alt.Chart(data).mark_bar().encode(
        y=alt.Y(y, title="", axis=alt.Axis(labelLimit=420),
                sort=alt.EncodingSortField(field=x, order="descending")),
        x=alt.X(x, title="건수"),
        color=alt.Color(color, title=color),
        tooltip=[y, color, x],
    ).properties(height=height))
    st.altair_chart(chart, **WIDE)


def _distribution(view: pd.DataFrame) -> None:
    st.subheader("무엇이 얼마나")
    failures = view[~view["묶음"].isin([NORMAL, REVIEW])]
    head = st.columns(3)
    head[0].metric("실패", f"{len(failures):,}건", help="아래 차트의 분모다. 정상 · 검토를 뺀 수.")
    head[1].metric("정상", f"{int((view['묶음'] == NORMAL).sum()):,}건")
    head[2].metric("검토", f"{int((view['묶음'] == REVIEW).sum()):,}건")

    normal = view[view["묶음"] == NORMAL]
    if not normal.empty and normal["본문"].any():
        with st.expander(f"정상 {len(normal):,}건 — 어떤 발화가 걸렸나"):
            st.caption("앞 답변을 문제 삼지 않은 후속 발화다. 필터의 어느 조건이 이걸 골랐는지를 본다.")
            fp = normal[["부서", "답변", "불만"]].rename(columns={"답변": "앞 답변", "불만": "후속 발화"})
            st.dataframe(fp, **WIDE, hide_index=True)
            download(fp, "filter_false_positives")

    if failures.empty:
        st.info("실패로 판정된 턴이 없습니다.")
    else:
        counts = failures.groupby(["묶음", "이유"]).size().reset_index(name="건수")
        st.caption("묶음(고칠 곳) 별 — 색은 들어온 길(이유 문장)")
        hbar(counts, y="묶음", x="건수", color="이유", height=bar_height(counts["묶음"].nunique()))
        by_reason = counts.sort_values("건수", ascending=False)
        st.dataframe(by_reason, **WIDE, hide_index=True,
                     column_config={"이유": st.column_config.TextColumn("들어온 길", width="large")})

    st.subheader("어디서 멈췄나")
    stops = view["단계"].value_counts().reindex(list(tx.STEPS)).fillna(0).astype(int)
    st.dataframe(pd.DataFrame({"단계": stops.index, "건수": stops.values}), **WIDE, hide_index=True)

    review = view[view["묶음"] == REVIEW]
    st.subheader(f"어디서 막혔나 — 검토 {len(review):,}건")
    if review.empty:
        st.info("검토로 간 턴이 없습니다.")
        return
    st.caption("검토는 kev 가 확신하지 못한 턴이다. 자주 막히는 문항이 기준문을 고칠 곳이다.")
    counts = review["멈춘곳"].value_counts()
    blocked = pd.DataFrame({"막힌 문항": counts.index, "건수": counts.values})
    st.dataframe(blocked, **WIDE, hide_index=True,
                 column_config={"막힌 문항": st.column_config.TextColumn("막힌 문항", width="large")})
    download(blocked, "review_at")


# ---------------------------------------------------------------------------
# 조직
# ---------------------------------------------------------------------------

BASELINE = "■ 전체"
LIFT_FULL = 3.0
MIN_OUTLIER_TURNS = 5


def expected(counts: pd.DataFrame) -> pd.DataFrame:
    """규모와 전사 묶음 비율만으로 예상되는 건수. 규모를 빼고 남는 것이 편중이다."""
    rows, cols = counts.sum(axis=1), counts.sum(axis=0)
    total = float(cols.sum()) or 1.0
    return pd.DataFrame({c: rows * (cols[c] / total) for c in counts.columns}, index=counts.index)


def _by_org(view: pd.DataFrame, org: dict) -> None:
    st.subheader("어느 팀이 무엇을 겪나")
    st.caption("근거 묶음이 특정 부서에 몰려 있으면 그 도메인 문서가 비어 있다는 뜻이다. "
               "사용자 묶음이 몰려 있으면 그 부서의 질문 습관이다.")
    failures = view[~view["묶음"].isin([NORMAL, REVIEW])]
    if failures.empty:
        st.info("실패로 판정된 턴이 없습니다.")
        return

    picker = st.columns([2, 3, 2])
    with picker[0]:
        axis = st.radio("기준", list(ORG_AXES), horizontal=True, label_visibility="collapsed")
    with picker[2]:
        grouping = st.selectbox("묶기", ["묶음별"] + [f"{a}별" for a in ORG_AXES if a != axis],
                                label_visibility="collapsed")
    org_for_axis = org.get(axis)
    level_label = {"major": "대분류", "middle": "중분류", "item": "소분류"}
    if org_for_axis and org_for_axis["field"]:
        with picker[1]:
            level = st.radio("층", ["major", "middle", "item"], index=0, horizontal=True,
                             format_func=lambda x: level_label[x], label_visibility="collapsed")
        source = failures.assign(**{axis: failures[axis].map(
            lambda v: org_for_axis["table"].rollup(v, level))})
        st.caption(f"{level_label[level]} 기준 · {org_for_axis['field']} 필드로 매칭")
    else:
        source = failures
        if org_for_axis:
            st.caption("이 축에 붙는 분류 체계를 찾지 못해 원래 값으로 표시한다.")

    crossed = grouping[:-1]
    column = crossed if crossed in ORG_AXES else "묶음"
    table = crosstab(source, axis, column)
    counts = table.drop(columns="계")
    share = counts.div(table["계"], axis=0)
    ratio = counts / expected(counts)

    st.caption(f"실패 {len(failures):,}건 기준 · 정상 · 검토는 뺐다")
    st.dataframe(baseline_row(table, table.sum(axis=0)), **WIDE, column_config=bucket_tooltips(table.columns))

    mode = st.radio("색 기준", ["관측÷기대", "행 내 비율"], horizontal=True, label_visibility="collapsed")
    if mode == "관측÷기대":
        body = baseline_row(_cells(ratio, counts, lambda v: f"{v:.1f}×"),
                            _cells(pd.Series(1.0, index=ratio.columns), counts, lambda v: f"{v:.1f}×",
                                   totals=counts.sum(axis=0)))
        paint = baseline_row((ratio / LIFT_FULL).clip(upper=1.0), pd.Series(1.0 / LIFT_FULL, index=ratio.columns))
        st.caption(f"**관측÷기대** — 규모와 전사 비율로 예상되는 건수 대비. 1.0× 가 평균, {LIFT_FULL:g}× 에서 색이 꽉 찬다 · 괄호는 건수")
    else:
        body = baseline_row(_cells(share, counts, "{:.0%}".format),
                            _cells(_global_share(counts), counts, "{:.0%}".format, totals=counts.sum(axis=0)))
        paint = baseline_row(share, _global_share(counts))
        st.caption("**행 내 비율** — 그 부서 실패 중 몇 %인가 · 괄호는 건수")
    st.caption("맨 윗줄이 전사 기준선이다 · 열 머리글에 마우스를 올리면 고칠 곳이 나온다")
    st.dataframe(body.style.apply(lambda _: paint.map(heat), axis=None), **WIDE,
                 column_config=bucket_tooltips(body.columns, numeric=False))
    _outliers(counts, ratio, axis, column if column in ORG_AXES else "묶음")


def _global_share(counts: pd.DataFrame) -> pd.Series:
    cols = counts.sum(axis=0)
    return cols / (float(cols.sum()) or 1.0)


def _cells(values, counts: pd.DataFrame, fmt, totals=None):
    """값과 건수를 한 칸에. 비율만 있으면 2건 중 1건인지 40건 중 20건인지 알 수 없다."""
    if isinstance(values, pd.Series):
        return pd.Series({c: "—" if not totals[c] else f"{fmt(values[c])} ({int(totals[c])})"
                          for c in values.index})
    return values.combine(counts, lambda col, n: pd.Series(
        ["—" if not c else f"{fmt(v)} ({int(c)})" for v, c in zip(col, n)], index=col.index))


def baseline_row(table, row):
    head = pd.DataFrame([row], index=[BASELINE])[table.columns]
    return pd.concat([head, table])


def _outliers(counts: pd.DataFrame, ratio: pd.DataFrame, axis: str, column_name: str) -> None:
    found = [{axis: group, column_name: col, "배수": round(float(ratio.loc[group, col]), 1),
              "턴": int(counts.loc[group, col]), "전사에서는": f"{_global_share(counts)[col]:.0%}"}
             for group in counts.index for col in counts.columns
             if counts.loc[group, col] >= MIN_OUTLIER_TURNS and ratio.loc[group, col] >= 1.5]
    st.subheader("유독 많은 것")
    if not found:
        st.info(f"턴 {MIN_OUTLIER_TURNS}건 이상이면서 기대의 1.5배를 넘는 조합이 없습니다.")
        return
    table = pd.DataFrame(found).sort_values("배수", ascending=False)
    st.dataframe(table, **WIDE, hide_index=True,
                 column_config={"배수": st.column_config.NumberColumn("기대 대비", format="%.1f×"),
                                "전사에서는": st.column_config.TextColumn("전사 비율")})
    download(table, "outliers")


# ---------------------------------------------------------------------------
# 근거 보강
# ---------------------------------------------------------------------------

def _evidence_gaps(view: pd.DataFrame) -> None:
    gaps = view[view["묶음"] == EVIDENCE]
    st.subheader(f"근거 보강 목록 ({len(gaps):,}건)")
    st.caption("근거 묶음 — 청크 · 도구 결과 · 앞 턴 근거 · 메모리 어디에도 답이 없었던 질문이다. "
               "검색기 · 도구 연동 · 문서팀에 그대로 넘기는 목록이고, **들어온 길**이 셋을 가른다.")
    if gaps.empty:
        st.info("근거 묶음이 없습니다.")
        return
    table = gaps[["질문", "이유", "근거위치", "부서", "대화", "턴"]].sort_values(["이유", "부서"])
    st.dataframe(table, **WIDE, hide_index=True,
                 column_config={"질문": st.column_config.TextColumn("질문", width="large"),
                                "이유": st.column_config.TextColumn("들어온 길", width="medium"),
                                "근거위치": st.column_config.TextColumn("답이 없던 칸", width="medium")})
    download(table, "evidence_gaps")


# ---------------------------------------------------------------------------
# 개별 케이스
# ---------------------------------------------------------------------------

ALL = "(전체)"
CASE_ORDERS = {
    "로그 순서": lambda v: v,
    "검토 먼저": lambda v: v.sort_values("확실"),
    "부서 순": lambda v: v.sort_values(["부서", "묶음"]),
    "묶음 순": lambda v: v.sort_values("묶음", key=lambda c: c.map(BUCKETS.index)),
}


def _cases(view: pd.DataFrame) -> None:
    st.subheader("개별 케이스")
    st.caption("**행을 누르면** 그 케이스의 결론 → 지나온 단계 → 본문이 아래에 펼쳐진다.")
    state = st.session_state

    per_bucket = view["묶음"].value_counts()
    whole = len(view)
    picked = st.selectbox("묶음", [ALL] + [b for b in BUCKETS if b in per_bucket.index],
                          format_func=lambda b: f"전체 ({whole:,}건)" if b == ALL else f"{b} ({per_bucket[b]:,}건)",
                          label_visibility="collapsed")
    if picked != ALL:
        view = view[view["묶음"] == picked]

    found = st.text_input("찾기", placeholder="질문 · 답변 · 불만 · 이유 · 부서에서 찾기",
                          label_visibility="collapsed")
    if found:
        needle = found.strip().lower()
        hay = (view["질문"].fillna("") + " " + view["답변"].fillna("") + " " + view["불만"].fillna("")
               + " " + view["이유"].fillna("") + " " + view["부서"].fillna(""))
        view = view[hay.str.lower().str.contains(needle, regex=False)]
        if view.empty:
            st.info(f"'{found}' 에 걸리는 케이스가 없습니다.")
            return

    order = st.selectbox("정렬", list(CASE_ORDERS), label_visibility="collapsed")
    view = CASE_ORDERS[order](view)

    if (found, order, picked) != state.get("case_scope"):
        state.case_scope = (found, order, picked)
        state.case_idx = 0
        state.case_nonce = state.get("case_nonce", 0) + 1
    total = len(view)
    state.setdefault("case_idx", 0)
    state.setdefault("case_nonce", 0)
    state.case_idx = max(0, min(state.case_idx, total - 1))

    compact = view[["부서", "턴", "묶음", "확실", "멈춘곳", "질문"]].copy()
    compact.insert(0, "보기", False)
    compact.iloc[state.case_idx, 0] = True
    edited = st.data_editor(
        compact, **WIDE, height=280, hide_index=True, key=f"cases-{state.case_nonce}",
        disabled=[c for c in compact.columns if c != "보기"],
        column_config={"보기": st.column_config.CheckboxColumn("보기"),
                       "확실": st.column_config.CheckboxColumn("확실", help="꺼져 있으면 검토"),
                       "멈춘곳": st.column_config.TextColumn("멈춘 곳", width="medium"),
                       "질문": st.column_config.TextColumn("질문", width="large")})
    checked = [i for i, on in enumerate(edited["보기"]) if on]
    moved = [i for i in checked if i != state.case_idx]
    if moved:
        state.case_idx = moved[0]
        state.case_nonce += 1
        st.rerun()

    if _navigate(state, total, "top"):
        st.rerun()
    detail(view.iloc[state.case_idx])
    st.divider()
    if _navigate(state, total, "bottom"):
        st.rerun()


def _navigate(state, total: int, where: str) -> bool:
    back, position, forward = st.columns([1, 2, 1])
    moved = False
    if back.button("← 이전", key=f"prev-{where}", **WIDE, disabled=state.case_idx <= 0):
        state.case_idx -= 1
        moved = True
    position.markdown(f"**{state.case_idx + 1} / {total}**")
    if forward.button("다음 →", key=f"next-{where}", **WIDE, disabled=state.case_idx >= total - 1):
        state.case_idx += 1
        moved = True
    if moved:
        state.case_nonce += 1
    return moved


ANSWER_BOX_PX = 300
FITS_PER_WEIGHT = 100


def boxed(text: str, weight: int, paint) -> None:
    """폭에 비해 길면 고정 높이 안에서 스크롤한다."""
    if len(text) <= FITS_PER_WEIGHT * weight:
        paint(text)
        return
    with st.container(height=ANSWER_BOX_PX, border=False):
        paint(text)
    st.caption(f"{len(text):,}자 — 상자 안에서 스크롤")


def _bordered(text: str) -> None:
    with st.container(border=True):
        st.write(text)


def history_text(messages: list[dict]) -> str:
    if not messages:
        return "—"
    return "\n\n".join(f"**{'사용자' if m.get('role') == 'user' else '챗봇'}** · {m.get('content', '')}"
                       for m in messages)


def step_table(step: dict) -> pd.DataFrame:
    if "rules" in step:
        return pd.DataFrame([{"문항": k, "답": v} for k, v in step["rules"].items()])
    rows = []
    for k, v in step.get("answers", {}).items():
        if isinstance(v, dict):
            rows.append({"문항": k, "답": v.get("answer", ""), "p": v.get("p")})
        else:
            rows.append({"문항": k, "답": v, "p": None})
    return pd.DataFrame(rows)


def detail(row: pd.Series) -> None:
    """한 케이스 — 결론 → 지나온 단계 → 본문. 결과 파일의 값을 그대로 보여준다."""
    original = row["_원본"]
    v = original.get("verdict") or {}
    st.markdown(f"### {row['묶음']} — {row['이유']}")
    st.caption(f"고칠 곳: {OWNER.get(row['묶음'], '—')}  ·  멈춘 곳: {row['멈춘곳']}"
               + ("  ·  **검토**" if not row["확실"] else ""))
    if v.get("where"):
        st.caption("근거 위치: " + " · ".join(v["where"]))
    flags = original.get("flags") or {}
    if flags.get("앞 턴 누락") is True:
        st.warning("앞 턴 누락 — history_chat 에 앞 턴이 빠져 있다. 모델이 못 본 것인지 로그가 떨어뜨린 것인지 못 가른다.", icon="🚩")
    if flags.get("history 재구성 턴 수"):
        st.caption(f"history 는 턴 순서로 {flags['history 재구성 턴 수']}턴을 재구성한 것이다 (history_chat 이 비어 있었다).")
    if flags.get("질문에 개인정보"):
        st.caption("질문에 개인정보 — 답변의 성패와 독립인 사건. 입력 마스킹(UI)의 일이다.")

    steps = original.get("steps") or []
    st.markdown("**지나온 단계** — 문항과 답. p 는 kev 의 확률이고 0.9 이상이 확신이다")
    columns = st.columns(max(len(steps), 1))
    for col, step in zip(columns, steps):
        with col:
            st.markdown(f"**{step['step']}**")
            table = step_table(step)
            st.dataframe(table, **WIDE, hide_index=True, height=min(400, 40 + 36 * len(table)),
                         column_config={"문항": st.column_config.TextColumn("문항", width="large"),
                                        "p": st.column_config.NumberColumn("p", format="%.2f", width="small")})

    text = original.get("text")
    if not text:
        st.info("본문이 없는 결과 파일이다 (--no-text). chat_id · event_time 으로 원 로그를 찾는다.")
        return
    asked, said, complained = st.columns([1, 3, 1])
    with asked:
        st.markdown("**질문**")
        boxed(text.get("question") or "—", 1, _bordered)
    with said:
        st.markdown("**비판받은 답변**")
        boxed(text.get("answer") or "—", 3, st.info)
    with complained:
        st.markdown("**사용자의 불만**")
        boxed(text.get("followup") or "—", 1, st.warning)
    with st.expander(f"앞 대화 ({len(text.get('history') or [])}개 메시지)"):
        st.markdown(history_text(text.get("history") or []))
    for slot in SLOT_NAMES:
        items = text.get(slot) or []
        hit = slot in (v.get("where") or []) and row["묶음"] == GENERATION
        with st.expander(f"{slot} ({len(items)}개)" + (" — 답이 여기 있었다" if hit else "")):
            if not items:
                st.caption("비어 있음")
            for item in items:
                _bordered(item)


if __name__ == "__main__":
    main()
