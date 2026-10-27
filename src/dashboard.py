"""분류 결과를 훑어보는 대시보드.

  python -m streamlit run <저장소>/src/dashboard.py

--result 를 생략하면 ./output 에서 가장 최근 결과(<시각>_<로그>_<필터>.json)를 고른다.
조직 분류를 붙이려면:

  python -m streamlit run <저장소>/src/dashboard.py -- \
      --dept-class configs/dept_class.json \
      --job-class  configs/job_class.json

**src/ 직하에 있어야 한다.** streamlit 은 스크립트가 있는 디렉터리를
sys.path[0] 에 넣는다. src/ragdiag/ 안에 두면 그 디렉터리가 올라가고 src/ 는
안 올라가서 `import ragdiag` 가 자기 자신을 못 찾는다. 실제로 한 번 그렇게
깨졌는데, 서버는 정상으로 뜨고 헬스체크도 통과해서 로그만 봐서는 멀쩡해 보였다 -
streamlit 이 스크립트를 브라우저 접속 시에 실행하고 예외를 화면에만 보이기
때문이다. src/run.py 와 같은 이유로 여기 둔다.

에어갭 장비에서 돌아야 하므로 streamlit·pandas 둘만 추가로 필요하다. 차트는
altair 로 그리고(streamlit 이 이미 의존하는 패키지라 설치가 늘지 않는다) 히트맵은
CSS 를 직접 만든다 - plotly 나 matplotlib 을 쓰면 설치할 패키지가 늘어난다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


def _bail(message: str) -> None:
    """무엇을 하라는지까지 적고 멈춘다.

    실행 환경에서는 맨 트레이스백 하나가 사이클을 먹는다. 인터넷도 없고 물어볼
    곳도 없어서, 화면에 적힌 것이 전부다.
    """
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

# streamlit 서버 없이 이 파일을 직접 실행하면 경고만 쏟고 아무 화면도 안 나온다.
# 실패로 끝나지도 않아서 뭐가 잘못됐는지 알기 어렵다.
if not st.runtime.exists():
    # 경로는 사용자가 친 것을, 인터프리터는 지금 도는 것을 그대로 돌려준다.
    # `streamlit run` 은 PATH 에 실행 파일이 있어야 하는데 venv 를 activate 하지
    # 않았거나 공용 venv 를 쓰면 command not found 가 난다. python -m 은 지금
    # 이 인터프리터를 그대로 쓰므로 PATH 를 타지 않는다.
    _bail("이 파일은 streamlit 이 실행합니다. python 으로 직접 돌리면\n"
          "경고만 나오고 화면이 뜨지 않습니다.\n\n"
          f"  {sys.executable} -m streamlit run {sys.argv[0]}\n\n"
          "결과 경로를 생략하면 ./output 의 최신 것을 봅니다. 인자를 주려면\n"
          "`--` 뒤에 붙입니다 — 앞은 streamlit 이 먹습니다.\n"
          "`python -m streamlit` 은 PATH 를 타지 않습니다 — `streamlit` 만 쓰면\n"
          "venv 를 activate 하지 않았을 때 command not found 가 납니다.")

from ragdiag import taxonomy as tx
from ragdiag.features.sufficiency import narrow_need

# streamlit 1.49 에서 width= 가 use_container_width= 를 대체했고, 옛 인자는
# 2025-12-31 이후 제거 예고다. 실행 환경 venv 의 버전을 알 수 없으므로 둘 다 받는다 -
# 한쪽만 쓰면 어느 버전에서든 그 자리에서 죽고, 화면만 죽는 실패라 알아채기 어렵다.
_VERSION = tuple(int(x) for x in re.findall(r"\d+", st.__version__)[:2])
WIDE = {"width": "stretch"} if _VERSION >= (1, 49) else {"use_container_width": True}

# 신뢰도는 주 라벨의 증거 등급에서 나온다 (4·3 → high, 2 → medium, 1·0 → low).
CONF_ORDER = ["high", "medium", "low"]
CONF_LABEL = {"high": "높음 (등급 4·3 — 코드·근거 확정)", "medium": "중간 (등급 2 — 확신 p≥0.9)",
              "low": "낮음 (등급 1·0 — 기울어짐·불일치)"}
GRADE_LABEL = {4: "4 코드 확정", 3: "3 근거 확정", 2: "2 확신", 1: "1 기울어짐", 0: "0 불일치"}

# 화면이 따로 다루는 라벨. 번호를 흩어 놓으면 체계가 바뀔 때 하나씩 빠진다.
NORMAL = "N0"            # 정상 후속 — 실패가 아니다. 필터를 가리킨다
SERVICE_ERROR = "I1"     # 자원 부족 문구 — 모델이 답을 만든 적이 없다
COLLAPSED = "I2"         # 붕괴 · 읽을 수 없음
CORPUS_GAP = "D1"        # 검색 근거에 답 없음 — 코퍼스 보강 목록의 재료
NO_TOOL_CALL = "T1"      # 호출 없음 — 검색 0건의 갈림길
FABRICATED_QUOTE_TAG = "G5:지어낸인용"
# 등급 1 · 0 은 표본 검토 대상이다. 다른 등급과 같은 무게로 집계하지 않는다.
LOW_GRADE_MAX = 1


# ---------------------------------------------------------------------------
# 로딩
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="설정 YAML. 생략하면 configs/env.yaml")
    parser.add_argument("--result", help="분류 결과 JSON. 생략하면 --output-dir 의 최신 것")
    parser.add_argument("--output-dir",
                        help="여기서 가장 최근 결과(<시각>_<로그>_<필터>.json)를 고른다")
    parser.add_argument("--dept-class", help="부서 분류 체계 JSON")
    parser.add_argument("--job-class",
                        help="직무·직급 분류 체계 JSON (어느 축인지는 값으로 판별)")
    known, _ = parser.parse_known_args(sys.argv[1:])

    # 설정 파일도 읽는다. 여기 적어둔 값이 무시되면 "설정했는데 안 먹는다"가
    # 되고, 대시보드는 매번 인자를 붙여야 하는 도구가 된다 - 화면을 열 때마다
    # 조직 분류 경로를 다시 치게 만들 이유가 없다.
    # 우선순위는 파이프라인과 같다: CLI > 설정 > 기본값.
    config = _load_config(known.config)
    known.output_dir = (known.output_dir or config.get("paths.output_dir")
                        or DEFAULT_OUTPUT_DIR)
    known.dept_class = known.dept_class or config.get("paths.dept_class")
    known.job_class = known.job_class or config.get("paths.job_class")
    known.config_source = config.source

    if not known.result:
        known.result = newest_result(known.output_dir)
    return known


DEFAULT_OUTPUT_DIR = "output"


def _load_config(path: str | None):
    """설정을 읽는다. 못 읽어도 대시보드는 떠야 한다 - 화면을 보는 도구다.

    파이프라인은 설정이 깨지면 계산 전에 죽는 것이 맞지만, 여기서 죽으면
    결과를 볼 방법 자체가 사라진다. 무엇이 잘못됐는지는 화면에 남긴다.
    """
    from ragdiag.config import Config, ConfigError, load

    target = path or ("configs/env.yaml" if Path("configs/env.yaml").exists() else None)
    if not target:
        return Config()
    try:
        return load(target)
    except ConfigError as e:
        st.warning(f"설정을 읽지 못해 기본값으로 띄웁니다.\n\n{e}")
        return Config()


# 결과 파일 이름 - <시각>_<로그>_<필터>.json. 옛 이름(conv_parsed_<시각>.json)도
# 같이 찾는다. 결과는 실행 환경에 쌓이고, 이름 규칙이 바뀌었다고 옛 것이 안 보이면 안 된다.
_STAMP = re.compile(r"(\d{8}-\d{6})")


def result_files(out_dir: str) -> list[Path]:
    """결과 파일들을 오래된 것부터. 요약(_summary.txt)은 json 이 아니라 안 걸린다."""
    found = [p for p in Path(out_dir).glob("*.json")
             if p.name.startswith("conv_parsed_") or _STAMP.match(p.name)]
    return sorted(found, key=lambda p: (_STAMP.search(p.name) or [""])[0])


def newest_result(out_dir: str) -> str:
    """--output-dir 에서 가장 최근 결과를 고른다.

    파일 이름에 끝난 시각이 박혀 있어 고정된 경로를 기본값으로 둘 수 없다.
    시각이 앞이라 이름순이 곧 시간순이고, 마지막이 최신이다.
    """
    found = result_files(out_dir)
    if found:
        return str(found[-1])
    # 시각 스탬프가 없던 시절의 파일이나 --out 으로 직접 지정한 것
    legacy = Path(out_dir) / "conv_parsed.json"
    return str(legacy)


@st.cache_data
def load(path: str) -> pd.DataFrame:
    """중첩 JSON 을 턴 하나 = 한 행으로 편다."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = []
    for user in raw.get("analysis_results", []):
        for conv in user.get("conversations", []):
            for turn in conv.get("turns", []):
                cls = turn.get("classification") or {}
                evidence = cls.get("evidence") or {}
                obs = evidence.get("observation") or {}
                suf = evidence.get("sufficiency") or {}
                case_id, case_name, tags = _label_of(cls)
                rows.append({
                    "부서": user.get("db_dept_name", "-"),
                    # db_position_name(직위)이 로그에서 빠져(2026-10) job_grade 가
                    # 유일한 직급 축이 됐다. 그대로 뒀으면 이 상자가 전부 "-" 가
                    # 되는데 에러는 안 난다.
                    "직급": user.get("job_grade", "-"),
                    "직무": user.get("db_job_name", "-"),
                    "대화": conv.get("chat_id", "-"),
                    "턴": turn.get("turn"),
                    "case": case_id,
                    "case명": case_name,
                    "type": (tx.describe(case_id)["type_name"] if tx.get(case_id)
                             else cls.get("type_name", "")),
                    "신뢰도": cls.get("confidence", ""),
                    # 증거 등급. 옛 결과 파일에는 없다 - 그 행은 NaN 으로 남겨 집계에서 빠진다.
                    "등급": cls.get("grade"),
                    "판정근거": cls.get("reason", ""),
                    "부가": [c.get("case_id") for c in cls.get("secondary_cases") or []],
                    # 주 라벨에 딸린 것들. 태그는 "무엇을 어겼나", 플래그는 "이 기록을
                    # 믿을 수 있나", 이벤트는 "챗봇 실패가 아닌 사건".
                    "태그": tags,
                    "플래그": list(cls.get("flags") or []),
                    "이벤트": list(cls.get("events") or []),
                    "주의": cls.get("notes") or [],
                    "질문": obs.get("resolved_question", ""),
                    "원한것": obs.get("unmet_need", ""),
                    # Step 2 에 실제로 간 요구. Step 1 은 "정확한 금액이요" 에 절차 · 서류 ·
                    # 기한을 덧붙이는 버릇이 있어, unmet_need 로 묶으면 같은 요구가
                    # 부풀린 꼬리만큼 여러 줄로 흩어진다.
                    "요구": narrow_need(obs.get("unmet_need", ""),
                                      bool(obs.get("question_multi_intent"))),
                    "불만유형": obs.get("complaint_target", ""),
                    "질문성격": obs.get("question_domain", ""),
                    # v3 는 final_verdict 가 verdict 와 같다. 옛 결과 파일(인용 대조로
                    # 강등하던 시절)은 둘이 다를 수 있어 거친 쪽을 읽는다.
                    "충족도": suf.get("final_verdict") or suf.get("verdict", ""),
                    "없던것": suf.get("missing", ""),
                    # 검색된 청크. 0 이면 검색 결과가 없었다는 뜻이고 그게 T1 의 갈림길이다.
                    "문서수": len(turn.get("chunk_data") or []),
                    # ③ 충족도가 근거로 세운 청크 수 (p ≥ 임계). 인용 대조는 없어졌다 -
                    # 근거는 청크 인덱스와 확률이다.
                    "인용수": len(suf.get("evidence") or []),
                    # 지어낸 인용은 코드 검증기(quoted_spans)가 잡아 태그로 남는다.
                    "지어낸인용": 1 if FABRICATED_QUOTE_TAG in tags else 0,
                    "근거활용": (evidence.get("grounding") or {}).get("answer_used_rag", ""),
                    "검증": evidence.get("checks") or [],
                    "LLM호출": cls.get("llm_calls", 0),
                    "kev호출": cls.get("kev_calls", 0),
                    "_원본": turn,
                })
    df = pd.DataFrame(rows)
    if not df.empty:
        # None 이 섞인 열은 object 가 되어 `<=` 비교에서 죽는다. 숫자(NaN 허용)로 맞춘다.
        df["등급"] = pd.to_numeric(df["등급"], errors="coerce")
    return df


def _label_of(cls: dict) -> tuple[str, str, list[str]]:
    """결과 파일의 라벨 · 이름 · 태그. 옛 파일(case0~30)은 v3 로 옮겨 읽는다.

    결과는 실행 환경에 쌓이고 사이드바에서 옛 실행을 고를 수 있다. 번호를 그대로
    두면 열 머리글도 툴팁도 안 붙어 표를 읽을 수 없다. 대응이 없는 번호(제외된
    실패)는 원래 값으로 남긴다 - 지어내지 않는다.
    """
    case_id = cls.get("case_id", "error")
    case_name = cls.get("case_name", "")
    tags = list(cls.get("tags") or [])
    if case_id not in tx.LABELS and case_id != tx.UNCLASSIFIED:
        moved, tag = tx.from_v2(case_id)
        if moved:
            case_id, case_name = moved, tx.describe(moved)["case_name"]
        if tag and tag not in tags:
            tags.append(tag)
    return case_id, case_name, tags


@st.cache_data
def load_org(dept_path: str | None, job_path: str | None, records: list[dict]):
    """조직 분류를 읽고 어느 필드에 붙는지 판별한다.

    파일 이름으로 추측하지 않는다 - job_class 가 직무일 수도 직급일 수도 있고,
    잘못 붙이면 에러 없이 전부 (미분류)가 되어 알아채기 어렵다.
    """
    from ragdiag.org import detect_field, load_classification

    result = {}
    for path in (dept_path, job_path):
        if not path or not Path(path).exists():
            continue
        table = load_classification(path)
        chosen, scores = detect_field(records, table)
        # 어느 축인지는 **판별 결과**가 정한다. 예전에는 두 번째 파일을 무조건
        # "직급"에 붙였는데, job_class 는 보통 직무(db_job_name) 체계라 상자는
        # 직급이라 써 놓고 직무를 걸러 주고 있었다. 파일 이름은 아무것도 보장하지
        # 않는다 - 그래서 값으로 판별해 놓고 그 결과를 쓰지 않으면 판별이 무의미하다.
        label = LOG_FIELD_TO_COLUMN.get(chosen or "")
        if not label:
            result[Path(path).stem] = {"table": table, "field": None, "scores": scores,
                                       "orphan": chosen}
            continue
        result[label] = {"table": table, "field": chosen, "scores": scores}
    return result


@st.cache_data
def flat_records(path: str) -> list[dict]:
    """조직 필드 판별용 - 사용자 레코드만 뽑는다."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [{k: v for k, v in u.items() if k != "conversations"}
            for u in raw.get("analysis_results", [])]


def download(df: pd.DataFrame, name: str) -> None:
    """표를 CSV 로. 문서팀 · 필터 담당에게 그대로 넘기는 표에만 붙인다.

    utf-8-sig 인 이유는 엑셀이다. BOM 이 없으면 한글이 깨진 채 열리고, 받는 쪽은
    엑셀로 연다.
    """
    st.download_button("CSV 내려받기", data=df.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"{name}.csv", mime="text/csv", key=f"dl-{name}")


# 판별된 로그 필드 -> 화면의 축. db_position_name 이 로그에서 빠진 뒤로 직급은
# job_grade 다. 없는 필드에 체계가 붙으면 라벨을 지어내지 말고 "어느 축에도
# 못 붙였다"고 말해야 한다.
LOG_FIELD_TO_COLUMN = {"db_dept_name": "부서", "job_grade": "직급",
                       "db_job_name": "직무"}

# 사이드바에서 좁힐 수 있는 조직 축. 조직 탭의 기준 라디오와 같은 순서다 -
# 다르면 표에서 본 축을 고르는 자리에서 못 찾는다.
ORG_AXES = ("부서", "직급", "직무")



def heat(value: float) -> str:
    """0~1 을 배경색으로. matplotlib 을 쓰지 않는다.

    Styler.background_gradient 는 matplotlib 을 요구하는데, 대시보드 하나 때문에
    에어갭 장비에 설치할 패키지를 늘릴 이유가 없다. 값에 따라 CSS 를 직접 만든다.
    비율이 높을수록 진해지고, 글자는 배경이 어두워지면 흰색으로 바꾼다.
    """
    if not isinstance(value, (int, float)) or pd.isna(value):
        return ""
    ratio = max(0.0, min(1.0, float(value)))
    if ratio < 0.02:
        return "color: #b0b0b0"
    # 흰색 -> 청록 계열. 낮은 값도 옅게 보이도록 감마를 준다.
    weight = ratio ** 0.7
    r = int(255 - 200 * weight)
    g = int(255 - 90 * weight)
    b = int(255 - 105 * weight)
    text = "#ffffff" if weight > 0.55 else "#1a1a1a"
    return f"background-color: rgb({r},{g},{b}); color: {text}"


def column_label(case_id: str) -> str:
    """`G/G5` — 열 머리글에 묶음 글자를 함께 적는다.

    라벨은 묶음순이라 같은 묶음이 이어 붙지만, 열이 열일곱 개면 지금 어느 묶음을
    보고 있는지 놓친다. 묶음이 앞에 있으면 경계가 보이고, "이 부서는 G 가 통째로
    많다" 같은 읽기가 열 단위 합계 없이도 된다. 글자 하나가 겹쳐 보이지만 묶음은
    고치는 사람이라 그 글자가 곧 받는 쪽이다.
    """
    case = tx.get(case_id)
    return f"{case.type_id}/{case_id}" if case else case_id


def type_label(case_id: str) -> str:
    """`G · 생성` — 묶음으로 묶어 볼 때의 열 머리글.

    열이 여덟 개뿐이라 이름을 그대로 쓸 자리가 있다. 라벨 열은 열일곱 개라
    번호만 쓰고 툴팁으로 펼치지만, 여기서는 이름이 바로 보이는 편이 낫다.
    """
    case = tx.get(case_id)
    return f"{case.type_id} · {case.type_name}" if case else case_id


def case_of(column: str) -> str:
    """열 머리글에서 라벨 id 만 꺼낸다. 툴팁·정렬이 이걸로 붙는다."""
    return column.rsplit("/", 1)[-1]


def type_of(column: str) -> str:
    """열 머리글에서 묶음 글자만 꺼낸다. 없으면 빈 문자열."""
    head = column.split("/", 1)[0].split(" · ", 1)[0]
    return head if head in tx.GROUPS else ""


# 묶음의 순서. tx.GROUPS 가 선언된 순서가 곧 sort_key 의 묶음 순서다.
GROUP_RANK = {g: i for i, g in enumerate(tx.GROUPS)}


def column_order(name: str):
    """묶음이 먼저, 그 안에서 번호. 두 모양 다 이 키로 정렬된다.

    tx.sort_key 가 이미 (묶음, 번호) 다 - 사이드바에서 고르는 순서와 같아야 하므로
    같은 함수를 쓴다. 열 머리글이 묶음만 담고 있을 때(묶음별 묶기)는 그 순위를 쓴다.
    """
    kind = type_of(name)
    if not tx.get(case_of(name)) and kind:
        return (0, GROUP_RANK[kind], -1, "")        # "G · 생성" 처럼 묶음만인 열
    return tx.sort_key(case_of(name))


def case_tooltips(columns, numeric: bool = True) -> dict:
    """라벨 열 머리글에 설명을 매단다.

    머리글에는 G/G5 까지만 찍는다. 이름을 다 적으면 열이 넓어져 한 화면에
    안 들어오고, 번호만 있으면 무엇인지 알 수 없다 - 머리글은 짧게 두고 마우스를
    올렸을 때 펼친다. 묶음은 글자(G)만 보이므로 툴팁이 그 이름과 고칠 곳도 말한다.
    """
    # unclassified 도 붙인다. 오히려 이것이 제일 헷갈린다 - "분류 실패"를
    # "문제 없음"으로 읽으면 집계 전체를 잘못 읽는다.
    known = set(tx.LABELS) | {tx.UNCLASSIFIED}
    column = st.column_config.NumberColumn if numeric else st.column_config.TextColumn
    tips = {}
    for name in columns:
        if not isinstance(name, str):
            continue
        case = tx.get(case_of(name))
        if case:
            # 머리글에는 G 까지만 보인다. 번호가 무엇을 뜻하는지는 여기서.
            tips[name] = column(name, help=f"{case.type_id} {case.type_name}\n\n"
                                           f"{tx.tooltip(case_of(name))}")
        elif type_of(name):
            group = tx.GROUPS[type_of(name)]
            members = ", ".join(tx.label(c) for c, v in tx.LABELS.items()
                                if v.type_id == type_of(name))
            tips[name] = column(name, help=f"{group.group_id}({group.word}) {group.name} — "
                                           f"고칠 곳: {group.owner}\n\n이 묶음의 라벨: {members}")
        elif case_of(name) in known:
            tips[name] = column(name, help=tx.tooltip(case_of(name)))
    return tips


def crosstab(df: pd.DataFrame, axis: str, column: str = "case") -> pd.DataFrame:
    table = pd.crosstab(df[axis], df[column])
    table = table[sorted(table.columns, key=column_order)]
    table["계"] = table.sum(axis=1)
    return table.sort_values("계", ascending=False)


# ---------------------------------------------------------------------------
# 화면
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="대화 로그 실패 분류", layout="wide")
    args = parse_args()

    st.title("대화 로그 실패 분류")

    # 결과는 실행마다 쌓인다 (파일 이름에 끝난 시각). 최신만 볼 수 있으면 설정을
    # 바꿔가며 돌린 것들을 나란히 못 본다 - 대시보드를 다시 띄우지 않고 고른다.
    runs = result_files(args.output_dir)[::-1]
    path = Path(args.result)
    with st.sidebar:
        names = [str(r) for r in runs]
        # --result 로 지목한 것이 이 디렉터리 밖일 수 있다. 목록에 없다고 최신으로
        # 갈아치우면 인자가 조용히 무시된다 - 맨 앞에 넣어 그것이 기본이 되게 한다.
        if str(path) not in names:
            names.insert(0, str(path))
        if names:
            picked = st.selectbox(
                "실행 결과", names, index=0,
                format_func=lambda n: Path(n).stem.replace("conv_parsed_", ""),
                help="<시각>_<로그>_<필터>. 시각은 분류가 끝난 시각이고 최신이 위에 온다")
            path = Path(picked)
        st.divider()

    if not path.exists():
        st.error(f"결과 파일이 없습니다: {path}\n\n"
                 "먼저 src/run.py 로 분류를 돌리세요.")
        st.stop()

    df = load(str(path))
    org = load_org(args.dept_class, args.job_class, flat_records(str(path)))
    if df.empty:
        st.warning("분류된 턴이 없습니다.")
        st.stop()

    others = len(runs) - 1
    stamp = f"  ·  다른 실행 {others}건 더 있음" if others > 0 else ""
    source = getattr(args, "config_source", "(기본값)")
    st.caption(f"{path}  ·  {len(df)}건{stamp}  ·  설정 {source}")

    # --- 필터 ---------------------------------------------------------------
    def _keep_valid(chosen: list[str], options: list[str]) -> list[str]:
        """위층을 바꿔 후보에서 사라진 선택을 흘려보낸다.

        대분류를 A 에서 B 로 갈면 A 밑에서 고른 중분류는 후보에 없다. 그대로
        두면 아무 데이터에도 안 맞아 0건이 나오는데, 화면에는 여전히 선택된
        것처럼 보인다.
        """
        return [c for c in chosen if c in options]

    def cascade(label: str) -> "set[str] | None":
        """대분류 → 중분류 → 소분류 로 좁혀 고른다. 각 층은 복수 선택.

        위층을 고르면 아래층 후보가 거기 매인다. 팀이 수십 개일 때 소분류만
        평평하게 늘어놓으면 고를 수 없기 때문이다.

        분류 체계가 안 붙은 축은 원래대로 값 하나만 고르게 둔다 - 없는 층을
        만들어 보여주면 고를 수 있는 것처럼 보인다.
        """
        from ragdiag.org import allowed_values, level_options, observed_tree

        info = org.get(label)
        table = info["table"] if info and info["field"] else None
        values = [str(v) for v in df[label].unique()]

        if table is None:
            chosen = st.multiselect(label, sorted(values))
            return set(chosen) if chosen else None

        tree = observed_tree(table, values)

        # 한 축의 세 층을 한 상자에 담는다. 층이 늘어날수록 사이드바가 길어지는데,
        # 상자가 없으면 "직급 소분류" 가 부서 것인지 직급 것인지 스크롤하며 세게 된다.
        # 라벨에서 축 이름을 뺄 수 있는 것도 이득이다 - 좁은 화면에서 줄바꿈이 준다.
        with st.container(border=True):
            st.markdown(f"**{label}**")

            # 아래층은 위층을 고른 뒤에만 보인다. 셋을 한꺼번에 늘어놓으면 무엇이
            # 무엇에 매이는지 안 보이고, 소분류만 골랐을 때 위층이 비어 있는
            # 조합이 생겨 "왜 이것만 나오지"가 된다.
            majors = st.multiselect("대분류", level_options(tree, [], [])[0],
                                    key=f"{label}:대분류")

            middles: list[str] = []
            if majors:
                options = level_options(tree, majors, [])[1]
                middles = _keep_valid(
                    st.multiselect("중분류", options, key=f"{label}:중분류"), options)

            items: list[str] = []
            if middles:
                options = level_options(tree, majors, middles)[2]
                items = _keep_valid(
                    st.multiselect("소분류", options, key=f"{label}:소분류"), options)

        return allowed_values(tree, majors, middles, items)

    with st.sidebar:
        st.header("좁히기")
        narrowed = {axis: cascade(axis) for axis in ORG_AXES}
        # 번호만 보고 무엇인지 아는 사람은 없다. 고르는 자리에 이름을 붙이고,
        # 고른 뒤에는 옆 라벨과 가르는 기준까지 펼쳐 준다.
        # 문자열로 정렬하면 G1 이 U1 앞에 온다. 표(crosstab)는 묶음순(N U C T D G S I)
        # 이라 어긋나서, 표에서 본 라벨을 고르는 자리에서 못 찾는다.
        cases = st.multiselect("case", tx.ordered(df["case"].unique()),
                               format_func=tx.label)
        for cid in cases:
            if tx.desc(cid):
                st.caption(f"**{cid}** {tx.desc(cid)}")
        confs = st.multiselect(
            "신뢰도", [c for c in CONF_ORDER if c in set(df["신뢰도"])],
            format_func=lambda c: CONF_LABEL.get(c, c))
        st.divider()
        if org:
            st.divider()
            st.caption("조직 분류")
            for label, info in org.items():
                if info["field"]:
                    cov = info["scores"][info["field"]]
                    st.caption(f"· {label} ← `{info['field']}` {cov.rate:.0%}")
                    if cov.unmapped:
                        st.caption(f"  체계에 없는 값 {len(cov.unmapped)}종 → (미분류)")
                elif info.get("orphan"):
                    st.caption(f"· {label} → `{info['orphan']}` 에 붙었지만 "
                               f"화면에 그 축이 없다")
                else:
                    st.caption(f"· {label} 매칭 실패 — 원래 값으로 표시")
        st.divider()
        hide_low = st.checkbox(
            "등급 ≤1 제외", value=False,
            help="증거 등급 1(확률만 기울어진 G3 등) · 0(unclassified) 을 뺀다. "
                 "표본 검토 대상이라 다른 등급과 같은 무게로 집계하면 안 되는 값이다.")

    view = df
    # None 은 "안 좁혔다", 빈 집합은 "골랐는데 해당 없음"이다. 둘을 같게 다루면
    # 조건을 걸었는데 전체가 나온다.
    for column, chosen in [*narrowed.items(),
                           ("case", cases or None), ("신뢰도", confs or None)]:
        if chosen is not None:
            view = view[view[column].isin(chosen)]
    if hide_low:
        # 등급이 없는 옛 결과(NaN)는 남긴다 - 낮은 것이 아니라 모르는 것이다.
        view = view[~(view["등급"] <= LOW_GRADE_MAX)]

    if view.empty:
        st.warning("조건에 맞는 케이스가 없습니다. 좁히기를 완화하세요.")
        st.stop()

    # --- 판정 건강 지표 (라벨 분포보다 먼저) ---------------------------------
    st.subheader("판정 건강")
    st.caption("라벨 분포보다 먼저 볼 숫자다. 여기가 나쁘면 아래 집계를 믿을 수 없다.")
    fabricated = int(view["지어낸인용"].sum())
    low = int((view["등급"] <= LOW_GRADE_MAX).sum())
    unclassified = int((view["case"] == tx.UNCLASSIFIED).sum())

    # 서비스 자원 부족(I1)은 모델이 답을 만든 적이 없는 턴이다. 품질 분포에
    # 섞어 두면 "챗봇이 나쁘다"로 읽히는데 실제로는 인프라가 모자랐던 것이다.
    service = int((view["case"] == SERVICE_ERROR).sum())
    # 생성 붕괴(I2)도 모델이 답을 만든 적이 없는 것과 같다 - 품질 분포에서 뺀다.
    collapsed = int((view["case"] == COLLAPSED).sum())

    # N0 은 실패가 아니다. 필터가 넓게 잡아 들어온 정상 턴이라 실패율 분모에서
    # 빼야 하고, 이 숫자가 가리키는 것은 챗봇이 아니라 필터다.
    normal = int((view["case"] == NORMAL).sum())

    # 분모 밖의 둘. 플래그는 그 턴의 기록을 믿을 수 없다는 표시고, 이벤트는
    # 사용자 쪽 사건이다. 라벨이 아니라 셀을 만들지 않지만 몇 건인지는 보여야 한다.
    flags = Counter(f for fs in view["플래그"] for f in fs)
    events = Counter(e for es in view["이벤트"] for e in es)

    cols = st.columns(7)
    cols[0].metric("분류된 턴", len(view),
                   delta=f"-{normal} 정상" if normal else None, delta_color="off",
                   help="N0(정상)을 빼면 실제 실패 건수가 된다.")
    cols[1].metric("지어낸 인용", fabricated,
                   help=f"태그 {FABRICATED_QUOTE_TAG} 가 붙은 턴 — 답변이 인용부호로 제시한 "
                        "문장이 근거 어디에도 없다. 코드 검증기(quoted_spans)가 잡는다.")
    cols[2].metric("등급 ≤1", low,
                   help="증거 등급 1(확률만 기울어짐) · 0(불일치). 표본 검토 대상이라 "
                        "다른 등급과 같은 무게로 집계하지 말 것.")
    cols[3].metric("미분류", unclassified,
                   help="분류 실패(unclassified). '문제 없음'이 아니라 수동 검토 대상이다.")
    cols[4].metric("서비스 오류", service,
                   help="I1 — 모델 자원 부족으로 서비스가 안내 문구를 낸 턴. "
                        "검색·생성 품질과 무관하므로 아래 분포를 읽을 때 빼고 봐야 한다.")
    cols[5].metric("생성 붕괴", collapsed,
                   help="I2 — 5555… 같은 반복이나 읽을 수 없는 글. 코드 규칙이 잡으면 등급 4, "
                        "읽기 판정(kev)이 잡으면 등급 2. 고칠 곳은 모델·서빙이다.")
    cols[6].metric("정상", normal,
                   help="N0 — 후속 발화가 앞 답변을 문제 삼지 않은 턴. "
                        "필터가 넓게 잡아 들어온 것이라 챗봇이 아니라 필터를 가리킨다.")
    if normal:
        st.info(f"필터가 고른 {len(view)}건 중 {normal}건({normal/len(view):.0%})은 "
                "불만이 아니었다. 실패율에서 빼고 읽고, 이 비율이 크면 필터를 "
                "좁힐 신호다 — 다만 0 이라고 좋은 것은 아니다. 너무 좁아서 놓치고 "
                "있을 수도 있어 필터 리포트와 짝으로 봐야 한다.", icon="✅")
    if service:
        st.info(f"서비스 자원 부족 응답이 {service}건이다 "
                f"(전체의 {service/len(view):.0%}). 모델이 답을 만든 적이 없는 턴이라 "
                "검색·생성 품질 지표에서 빼고 읽어야 한다 — 고칠 곳은 인프라다.", icon="🔌")
    if fabricated:
        st.warning(f"지어낸 인용이 {fabricated}건 있다. 해당 케이스의 판정을 먼저 확인할 것.")
    if flags or events:
        parts = [f"{k} {tx.describe(k)['case_name']} {n}건"
                 for k, n in [*sorted(flags.items()), *sorted(events.items())]]
        st.caption("실패율 분모 밖 — " + " · ".join(parts))
        if flags.get("C1"):
            st.caption("C1 이 선 턴은 G2(맥락) 를 판정하지 않았다. 많으면 G2 집계를 보류할 것.")

    # --- 분포 ---------------------------------------------------------------
    # 절을 탭으로 가른다. 한 화면에 다 쌓으면 태블릿에서 계속 스크롤해야 하고,
    # 어디가 끝이고 어디가 시작인지 알 수 없다. 사이드바 필터는 탭과 무관하게
    # 계속 걸리므로 탭을 옮겨도 보고 있던 범위가 유지된다.
    #
    # **판정 건강은 탭 밖에 둔다.** 탭 안에 넣으면 건너뛸 수 있는데, 그 숫자가
    # 나쁘면 나머지 집계를 믿을 수 없다는 것이 이 화면의 전제다.
    # 순서가 곧 훑는 순서다: 무엇이 얼마나 -> 어디가 -> 그 한 건 -> (문서팀에 넘길 것).
    # 코퍼스 보강은 결과물을 넘기는 자리라 다른 셋과 성격이 다르고, 넘길 때만
    # 열면 되므로 끝에 둔다.
    tab_dist, tab_org, tab_case, tab_gap = st.tabs(
        ["분포", "조직", "개별 케이스", "코퍼스 보강"])

    with tab_dist:
        _distribution(view)
    with tab_org:
        _by_org(view, org)
    with tab_case:
        _cases(view)
    with tab_gap:
        _corpus_gaps(view)


def bar_height(bars: int) -> int:
    """막대 하나에 26px.

    고정 높이를 주면 3종일 때는 막대가 통통해지고 20종일 때는 라벨이 겹친다.
    종 수는 필터에 따라 매번 달라진다.
    """
    return max(160, 26 * bars + 60)


def hbar(data: pd.DataFrame, y: str, x: str, color: str, height: int) -> None:
    """가로 막대. 많은 것부터, 같은 y 는 색으로 쌓는다.

    st.bar_chart 를 쓰지 않는 이유는 축 라벨이다. 180px 에서 잘라서 19종 case 이름이
    전부 "case20 · Retrieve …" 로 끝났다 - 무엇이 제일 많은지 보려고 그린 차트에서
    무엇인지가 안 보였다. altair 는 st.bar_chart 가 안에서 쓰는 그 패키지라 설치가
    늘지 않는다.
    """
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

    # 분모에서 둘을 뺀다.
    #
    # N0 은 실패가 아니고(필터가 넓게 잡아 딸려온 턴), unclassified 는 판정이
    # 실패한 것이라 어느 유형인지 모른다. 둘을 섞어 두면 "D1 22%" 가 "실패 중
    # 22%" 로 읽히는데 실제로는 "판정된 턴 중 22%" 다. 다른 숫자를 같은 말로
    # 읽게 만드는 것이라, 보기 좋고 나쁘고의 문제가 아니다.
    is_zero = view["case"] == NORMAL
    is_unjudged = view["case"] == tx.UNCLASSIFIED
    failures = view[~is_zero & ~is_unjudged]

    head = st.columns(3)
    head[0].metric("실패", f"{len(failures):,}건",
                   help="아래 차트의 분모다. 아래 둘을 뺀 수다.")
    head[1].metric("필터 오탐", f"{int(is_zero.sum()):,}건",
                   help="N0 — 후속 발화가 앞 답변을 문제 삼지 않는다. "
                        "챗봇이 아니라 필터를 볼 것.")
    head[2].metric("판정 실패", f"{int(is_unjudged.sum()):,}건",
                   help="어느 유형인지 모르는 턴. 유형별 집계에 넣으면 "
                        "'없는 유형'이 하나 생긴 것처럼 읽힌다.")

    # 분모에서 뺐는데 볼 방법이 없으면 "필터를 고치라" 는 신호가 숫자로만 남는다.
    # 어떤 발화가 오탐인지 봐야 필터의 어느 조건이 넓은지 알 수 있다. 탭을
    # 프로그램으로 바꿀 수 없어 여기서 편다.
    if is_zero.any():
        with st.expander(f"필터 오탐 {int(is_zero.sum()):,}건 — 어떤 발화가 걸렸나"):
            st.caption("앞 답변을 문제 삼지 않은 후속 발화다. 챗봇이 아니라 "
                       "필터의 어느 조건이 이걸 골랐는지를 본다.")
            false_positives = pd.DataFrame({
                "부서": view.loc[is_zero, "부서"],
                "앞 답변": view.loc[is_zero, "_원본"].map(
                    lambda o: str(o.get("llm_ans_on_last_q", ""))[:120]),
                "후속 발화": view.loc[is_zero, "_원본"].map(
                    lambda o: str(o.get("current_query", ""))),
            })
            st.dataframe(
                false_positives, **WIDE, hide_index=True,
                column_config={
                    "후속 발화": st.column_config.TextColumn("후속 발화", width="large"),
                    "앞 답변": st.column_config.TextColumn("앞 답변", width="medium")})
            download(false_positives, "filter_false_positives")

    if failures.empty:
        st.info("실패로 분류된 턴이 없습니다.")
        return

    counts = (failures.groupby(["case", "case명", "신뢰도"])
              .size().reset_index(name="건수"))
    counts["라벨"] = counts["case"] + " · " + counts["case명"]
    counts["신뢰"] = counts["신뢰도"].map(CONF_LABEL).fillna("—")

    # 둘을 나란히 두면 19종짜리 가로 막대가 반 폭에 눌려 라벨이 잘린다. 이 탭에서
    # 읽는 것은 "무엇이 제일 많나" 하나인데, 그걸 보려고 잘린 라벨을 짚어야 했다.
    # 세로로 쌓으면 스크롤이 늘지만 한 눈에 읽힌다 - 스크롤이 더 싸다.
    #
    # 색은 신뢰도(= 증거 등급)다. G3(의도와 다른 답)은 확률만 기울어진 등급 1 이고
    # I1(서비스 오류)은 코드가 확정한 등급 4 인데, 같은 길이의 막대로 나란히 있으면
    # 같은 무게로 읽힌다. "이 숫자는 덜 믿어라"가 차트 안에 있어야 한다.
    st.caption("라벨 별 — 많은 것부터 · 색은 신뢰도(증거 등급)")
    hbar(counts, y="라벨", x="건수", color="신뢰", height=bar_height(len(counts)))

    # 위 차트를 묶음으로 묶은 것이다. 그냥 막대로 그리면 위와 같은 말을 한 번 더
    # 하는 셈이라, 라벨로 쌓아서 "생성(G) 이 크고 그 안은 G5 가 대부분" 까지
    # 한 번에 읽히게 한다. 묶음이 곧 고칠 곳이다.
    st.caption("묶음(고칠 곳) 별 — 라벨을 쌓은 것")
    by_type = (failures.assign(type=failures["type"].replace("", "(미분류)"))
               .groupby(["type", "case"]).size().reset_index(name="건수"))
    hbar(by_type, y="type", x="건수", color="case",
         height=bar_height(by_type["type"].nunique()))

    _pareto(counts)


def _pareto(counts: pd.DataFrame) -> None:
    """상위 몇 종이 실패의 절반인가.

    19종을 다 고칠 수는 없다. 막대만 보면 "D1 이 제일 많다"까지는 알겠는데
    다음에 무엇을 할지는 안 나온다 - 몇 개를 고치면 어디까지 덮이는지가 그 답이다.

    순위를 x 축으로 둔다. case 이름을 축에 두면 위 막대 차트와 순서가 어긋날 때
    두 그림이 다른 이야기를 하게 되는데, 순위는 어긋날 수가 없다.
    """
    ranked = counts.sort_values("건수", ascending=False).reset_index(drop=True)
    total = int(ranked["건수"].sum())
    curve = pd.DataFrame({
        "상위 n종": range(1, len(ranked) + 1),
        "누적 비율": (ranked["건수"].cumsum() / total).round(3),
    })

    def cover(n: int) -> str:
        return f"{curve['누적 비율'][min(n, len(curve)) - 1]:.0%}"

    st.caption(f"누적 — 상위 3종이 실패의 **{cover(3)}**, "
               f"5종이 **{cover(5)}**, 10종이 **{cover(10)}** ({len(ranked)}종 중)")
    # 세로 축 제목을 뺀다. 세로로 세운 한글은 글자가 따로 놀아 읽을 수 없고, 무엇인지는
    # 위 캡션이 이미 말한다.
    st.line_chart(curve, x="상위 n종", y="누적 비율", y_label="", height=220)


# 전사 기준선 행의 이름. 부서 이름과 섞이지 않게 표시를 붙인다.
BASELINE = "■ 전체"

# 개별 케이스 탭에서 "유형을 안 좁혔다"를 뜻하는 값. case id 와 겹치지 않는다.
ALL_CASES = "(전체)"


def _suspect_first(view: pd.DataFrame) -> pd.DataFrame:
    """판정을 믿기 어려운 순서.

    지어낸 인용이 있으면 답변이 근거에 없는 문장을 인용부호로 냈다는 뜻이라 제일
    먼저 본다 — 다른 가중치를 다 더해도 못 넘게 8 이다. 그 다음이 등급 ≤1(확률만 기울어짐), 무결성 플래그(기록을 믿을 수
    없음), 분류 실패, 부가 라벨이 붙은 것.
    """
    return view.assign(_의심=(view["지어낸인용"].fillna(0) * 8
                             + (view["등급"] <= LOW_GRADE_MAX) * 3
                             + view["플래그"].map(bool) * 2
                             + (view["case"] == tx.UNCLASSIFIED) * 2
                             + view["부가"].map(bool))
                       ).sort_values("_의심", ascending=False).drop(columns="_의심")


# 훑는 순서. 기본은 파일 순서 - 로그에 있던 그대로다.
CASE_ORDERS = {
    "로그 순서": lambda v: v,
    "의심스러운 순": _suspect_first,
    "부서 순": lambda v: v.sort_values(["부서", "case"]),
    "case 순": lambda v: v.sort_values("case", key=lambda c: c.map(tx.sort_key)),
}

# 관측÷기대가 이 값이면 색이 꽉 찬다. 2배까지는 흔하고 3배부터가 눈에 띄는
# 편중이라, 여기서 포화시켜야 상위가 다 같은 색으로 뭉개지지 않는다.
LIFT_FULL = 3.0

# 이상치 목록에 올릴 최소 턴 수. 기대가 0.2인데 3건 나오면 15배가 되지만
# 그건 표본이 말하는 것이 아니라 우연이 말하는 것이다.
MIN_OUTLIER_TURNS = 5


def expected(counts: pd.DataFrame) -> pd.DataFrame:
    """부서 규모와 전사 case 비율만으로 예상되는 건수.

    "이 부서에 D1 이 많다"는 그 부서가 크기만 해도 성립한다. 규모를 빼고
    남는 것이 편중이다.
    """
    rows, cols = counts.sum(axis=1), counts.sum(axis=0)
    total = float(cols.sum()) or 1.0
    return pd.DataFrame({c: rows * (cols[c] / total) for c in counts.columns},
                        index=counts.index)


def _by_org(view: pd.DataFrame, org: dict) -> None:
    st.subheader("어느 팀이 무엇을 겪나")
    st.caption(
        "**이 표가 이 도구의 핵심이다.** D1(검색 근거에 답 없음)은 '검색기가 못 찾음'과 "
        "'코퍼스에 문서가 없음'을 합친 라벨이라 로그만으로는 가를 수 없다. "
        "특정 부서에 몰려 있으면 후자, 즉 그 도메인 문서가 비어 있다는 뜻이다.")

    # 실패만 센다. N0 은 실패가 아니고 unclassified 는 어느 유형인지 모르는데,
    # **그 비중이 부서마다 다르다.** 분모에 남겨 두면 부서마다 다르게 왜곡되어
    # 부서 간 비교 자체가 흔들린다 - 이 탭의 존재 이유가 그 비교다.
    dropped = view["case"].isin([NORMAL, tx.UNCLASSIFIED])
    failures = view[~dropped]
    if failures.empty:
        st.info("실패로 분류된 턴이 없습니다.")
        return

    picker = st.columns([2, 3, 2])
    with picker[0]:
        axis = st.radio("기준", list(ORG_AXES), horizontal=True,
                        label_visibility="collapsed")
    with picker[2]:
        # 라벨은 열이 열일곱 개라 한 화면에 안 들어오고, 옆 칸과 한 건씩 나뉘어
        # 편중이 흐려진다. 묶음으로 묶으면 여덟 열이라 다 보이고 표본도 커져서
        # 배수가 덜 흔들린다 - "G 가 통째로 많다" 는 라벨 단위로는 잘 안 보인다.
        # 선택지 이름(case별 · type별)은 그대로 둔다 - 손에 익은 자리다.
        #
        # 다른 조직 축을 열로 두면 축 두 개가 교차한다. "특정 직급이 특정 부서에서"
        # 는 한 축씩 봐서는 안 보인다 - 다만 칸이 잘게 쪼개지므로 건수를 함께 본다.
        grouping = st.selectbox(
            "묶기", ["case별", "type별"] + [f"{a}별" for a in ORG_AXES if a != axis],
            label_visibility="collapsed")
    org_for_axis = org.get(axis)
    level_label = {"major": "대분류", "middle": "중분류", "item": "소분류"}
    if org_for_axis and org_for_axis["field"]:
        with picker[1]:
            level = st.radio(
                "층", ["major", "middle", "item"], index=0, horizontal=True,
                format_func=lambda x: level_label[x], label_visibility="collapsed")
        table_source = failures.assign(
            **{axis: failures[axis].map(
                lambda v: org_for_axis["table"].rollup(v, level))})
        st.caption(f"{level_label[level]} 기준 · "
                   f"{org_for_axis['field']} 필드로 매칭")
    else:
        table_source = failures
        if org_for_axis:
            st.caption("이 축에 붙는 분류 체계를 찾지 못해 원래 값으로 표시한다.")

    crossed = grouping[:-1] if grouping.endswith("별") else grouping
    if crossed in ORG_AXES:
        source = table_source.assign(_열=table_source[crossed])
    else:
        to_column = column_label if grouping == "case별" else type_label
        source = table_source.assign(_열=table_source["case"].map(to_column))
    table = crosstab(source, axis, "_열")
    counts = table.drop(columns="계")
    share = counts.div(table["계"], axis=0)
    ratio = counts / expected(counts)

    st.caption(f"실패 {len(failures):,}건 기준 · "
               f"N0·판정 실패 {int(dropped.sum()):,}건은 뺐다")
    st.dataframe(baseline_row(table, table.sum(axis=0)),
                 **WIDE,
                 column_config=case_tooltips(table.columns))

    # 색이 무엇을 가리킬지 고르게 한다.
    #
    # 비율로 칠하면 상위가 전부 D1 이 된다 - 전사 실패의 4분의 1이라 어느
    # 부서를 봐도 크게 나오기 때문이다. 그건 분포 탭에서 이미 아는 사실이고,
    # 여기서 알고 싶은 것은 "이 부서에서 **유독** 많은가"다.
    mode = st.radio("색 기준", ["관측÷기대", "행 내 비율"], horizontal=True,
                    label_visibility="collapsed")
    if mode == "관측÷기대":
        text = _cells(ratio, counts, lambda v: f"{v:.1f}×")
        paint = (ratio / LIFT_FULL).clip(upper=1.0)
        body = baseline_row(text, _cells(_ones(ratio), counts, lambda v: f"{v:.1f}×",
                                         totals=counts.sum(axis=0)))
        paint = baseline_row(paint, pd.Series(1.0 / LIFT_FULL, index=ratio.columns))
        st.caption(f"**관측÷기대** — 부서 규모와 전사 case 비율로 예상되는 건수 대비. "
                   f"1.0× 가 평균이고 {LIFT_FULL:g}× 에서 색이 꽉 찬다 · 괄호는 건수")
    else:
        body = baseline_row(_cells(share, counts, "{:.0%}".format),
                            _cells(_global_share(counts), counts,
                                   "{:.0%}".format, totals=counts.sum(axis=0)))
        paint = baseline_row(share, _global_share(counts))
        st.caption("**행 내 비율** — 그 부서 실패 중 몇 %인가 · 괄호는 건수")

    st.caption("맨 윗줄이 전사 기준선이다 — 없으면 61% 가 높은지 낮은지 "
               "나머지 행을 눈으로 평균 내야 한다 · 열 머리글에 마우스를 올리면 "
               "무슨 문제인지 나온다")
    st.dataframe(
        body.style.apply(lambda _: paint.map(heat), axis=None),
        **WIDE,
        column_config=case_tooltips(body.columns, numeric=False))

    _outliers(counts, ratio, axis, crossed if crossed in ORG_AXES else "무엇이")


def _ones(like: pd.DataFrame) -> pd.Series:
    return pd.Series(1.0, index=like.columns)


def _global_share(counts: pd.DataFrame) -> pd.Series:
    cols = counts.sum(axis=0)
    return cols / (float(cols.sum()) or 1.0)


def _cells(values, counts: pd.DataFrame, fmt, totals=None):
    """값과 건수를 한 칸에 넣는다.

    비율만 있으면 "50%" 가 2건 중 1건인지 40건 중 20건인지 알 수 없다. 성향을
    보려고 비율을 쓰지만, 몇 건 위에서 나온 비율인지 모르면 그 성향을 믿을 수 없다.
    """
    if isinstance(values, pd.Series):     # 기준선 한 줄
        return pd.Series({c: "—" if not totals[c] else f"{fmt(values[c])} ({int(totals[c])})"
                          for c in values.index})
    return values.combine(counts, lambda col, n: pd.Series(
        ["—" if not c else f"{fmt(v)} ({int(c)})" for v, c in zip(col, n)],
        index=col.index))


def baseline_row(table, row):
    """맨 위에 전사 기준선을 붙인다.

    61% 가 높은지 낮은지 판단하려면 나머지 열네 행을 눈으로 평균 내야 했다.
    한 줄이면 모든 행이 그것과 비교된다.
    """
    head = pd.DataFrame([row], index=[BASELINE])[table.columns]
    return pd.concat([head, table])


def _outliers(counts: pd.DataFrame, ratio: pd.DataFrame, axis: str,
              column_name: str = "무엇이") -> None:
    """유독 많은 것만 뽑아 목록으로.

    코퍼스 탭은 문서팀에 그대로 넘길 목록을 낸다. 이 탭은 표만 냈다 - 285칸을
    눈으로 훑어 편중을 찾는 일이 읽는 사람 몫이었는데, 그건 계산할 수 있는 것이다.
    """
    found = [{axis: group,
              column_name: tx.label(case_of(case)) if tx.get(case_of(case)) else case,
              "배수": round(float(ratio.loc[group, case]), 1),
              "턴": int(counts.loc[group, case]),
              "전사에서는": f"{_global_share(counts)[case]:.0%}"}
             for group in counts.index for case in counts.columns
             if counts.loc[group, case] >= MIN_OUTLIER_TURNS
             and ratio.loc[group, case] >= 1.5]

    st.subheader("유독 많은 것")
    if not found:
        st.info(f"턴 {MIN_OUTLIER_TURNS}건 이상이면서 기대의 1.5배를 넘는 조합이 없습니다.")
        return

    st.caption(f"기대의 1.5배를 넘고 턴이 {MIN_OUTLIER_TURNS}건 이상인 것만. "
               "표본이 작으면 배수는 쉽게 커지므로 건수를 함께 본다.")
    st.dataframe(
        pd.DataFrame(found).sort_values("배수", ascending=False),
        **WIDE, hide_index=True,
        column_config={
            "배수": st.column_config.NumberColumn(
                "기대 대비", format="%.1f×",
                help="부서 규모와 전사 case 비율로 예상되는 건수 대비"),
            "턴": st.column_config.NumberColumn("턴"),
            "전사에서는": st.column_config.TextColumn(
                "전사 비율", help="이 case 가 전체 실패에서 차지하는 비율")})
    download(pd.DataFrame(found).sort_values("배수", ascending=False), "outliers")


def _corpus_gaps(view: pd.DataFrame) -> None:
    """문서에 없어서 답할 수 없었던 것.

    부서로 먼저 묶으면 같은 요구가 부서 수만큼 쪼개진다. 그런데 **여러 부서가
    같은 것에 막혔다는 사실이 가장 강한 신호다** - "연차 이월 예외 조건"이 세
    부서에서 나왔는데 부서별로 나누면 세 줄로 흩어져 안 보인다.
    문서팀이 받는 것은 "쓸 문서 목록"이므로 요구를 축으로 세운다.
    """
    gaps = view[(view["case"] == CORPUS_GAP) & (view["없던것"] != "")]
    # 묶는 축은 코드로 좁힌 요구(③ 충족도가 실제로 본 것)다. 없던것은 관측이 적은
    # unmet_need 라 더 정확한 문장이지만 표현이 매번 달라 묶는 축으로는 못 쓴다 - 대표로 보인다.
    grouped = (gaps.groupby("요구")
               .agg(건수=("질문", "size"),
                    부서=("부서", lambda x: " · ".join(sorted(set(x)))),
                    부서수=("부서", lambda x: len(set(x))),
                    없던것=("없던것", "first"),
                    질문=("질문", "first"))
               .reset_index()
               .sort_values(["부서수", "건수", "요구"], ascending=[False, False, True]))

    st.subheader(f"코퍼스 보강 목록 ({len(grouped)}종)")
    st.caption("문서에 없어서 답할 수 없었던 것. 문서팀에 그대로 넘길 수 있는 목록이다. "
               "**막힌 부서 수**로 정렬돼 있다 — 여러 부서가 같은 것에 막혔으면 "
               "특정 부서 업무가 아니라 공통 문서가 비어 있다는 뜻이고, 그게 우선순위다.")
    if grouped.empty:
        st.info("해당 케이스가 없습니다.")
        return

    if len(gaps) > len(grouped):
        st.caption(f"턴 {len(gaps)}건이 요구 {len(grouped)}종으로 묶였다. "
                   "판정자가 같은 요구를 조금 다르게 적으면 따로 잡히므로, "
                   "비슷한 항목이 이웃해 있으면 한 문서로 묶어 볼 것.")

    # 마크다운 목록이었다. 항목이 스무 개면 회색 잔글씨 마흔 줄이 되어 읽히지
    # 않고, 정렬도 검색도 복사도 안 된다. 문서팀에 그대로 넘기는 목록이라
    # 표가 맞다 - 정렬 축(막힌 부서 수)이 곧 우선순위다.
    table = grouped[["요구", "없던것", "부서수", "건수", "부서", "질문"]]
    st.dataframe(
        table,
        **WIDE, hide_index=True,
        column_config={
            "요구": st.column_config.TextColumn("필요한 문서", width="large"),
            "없던것": st.column_config.TextColumn(
                "문서에 없던 것", width="medium",
                help="관측이 적은 unmet_need. 같은 요구라도 표현이 조금씩 다르다"),
            "부서수": st.column_config.NumberColumn(
                "막힌 부서", help="여러 부서가 같은 것에 막혔으면 공통 문서가 비어 있다"),
            "건수": st.column_config.NumberColumn("턴"),
            "부서": st.column_config.TextColumn("어느 부서", width="medium"),
            "질문": st.column_config.TextColumn("대표 질문", width="large")})
    download(table.rename(columns={"요구": "필요한 문서", "없던것": "문서에 없던 것",
                                   "부서수": "막힌 부서", "건수": "턴"}), "corpus_gaps")


def _cases(view: pd.DataFrame) -> None:
    with st.expander(f"라벨 설명 — 이 데이터에 나온 {view['case'].nunique()}종"):
        st.caption("묶음은 **고치는 사람**이다. 같은 묶음 안의 '무엇을 어겼나'는 라벨이 "
                   "아니라 태그(G1:언어 · G5:어긋남 …)에 있고, 무엇이 아닌가까지 적었다.")
        counts = view["case"].value_counts()
        st.dataframe(pd.DataFrame([
            {"case": cid,
             "이름": case.name if (case := tx.get(cid)) else cid,
             "건수": int(n),
             "묶음": f"{case.type_id} · {case.type_name}" if case else "—",
             "고칠 곳": case.group.owner if case else "—",
             "설명": tx.desc(cid)}
            for cid, n in counts.items()
        ]), **WIDE, hide_index=True)

    st.subheader("개별 케이스")
    st.caption("**행을 누르면** 그 케이스의 판정 근거가 아래에 펼쳐진다. "
               "집계만 보고 근거를 못 보면 '왜 이 라벨이지'에서 막힌다.")

    state = st.session_state

    # 한 유형만 훑는 것과 전부 섞어 훑는 것은 다른 일이다. "D1 이 왜 이렇게
    # 많지"는 D1 만 연달아 봐야 답이 나오고, "이 데이터가 대체로 어떤가"는
    # 섞어 봐야 한다. 사이드바 case 필터로도 좁힐 수 있지만 그건 모든 탭에 걸려서,
    # 분포와 조직 탭까지 한 유형으로 좁아진다 - 비교 대상이 사라진다.
    per_case = view["case"].value_counts()
    # format_func 은 나중에 불린다. view 를 그대로 잡아 두면 아래에서 좁힌 뒤의
    # 건수로 라벨을 그려서 "전체 (8건)" 이 "전체 (2건)" 이 된다 - 고르는 자리가
    # 고른 결과를 보여주는 셈이라, 무엇을 고를지 판단할 근거가 사라진다.
    whole = len(view)
    picked = st.selectbox(
        "케이스", [ALL_CASES] + tx.ordered(per_case.index),
        format_func=lambda c: (f"전체 ({whole:,}건)" if c == ALL_CASES
                               else f"{tx.label(c)} ({per_case[c]:,}건)"),
        label_visibility="collapsed")
    if picked != ALL_CASES:
        view = view[view["case"] == picked]

    # 503건에서 특정 대화를 찾는 방법이 이전/다음뿐이었다. "출입증 관련 사례" 를
    # 보려면 쉰 번을 눌러야 한다. 사람이 친 말(불만)까지 훑어야 찾아진다 -
    # 정리된 질문은 판정자가 다시 쓴 것이라 원래 표현이 남아 있지 않다.
    found = st.text_input("찾기", placeholder="질문 · 불만 · 부서 · 라벨에서 찾기",
                          label_visibility="collapsed")
    if found:
        needle = found.strip().lower()
        hay = (view["질문"].fillna("") + " " + view["부서"].fillna("")
               + " " + view["case명"].fillna("") + " " + view["case"].fillna("")
               + " " + view["_원본"].map(lambda o: str(o.get("current_query", ""))))
        view = view[hay.str.lower().str.contains(needle, regex=False)]
        if view.empty:
            st.info(f"'{found}' 에 걸리는 케이스가 없습니다.")
            return

    # 파일 순서는 사실상 무작위다. 이 화면을 여는 이유의 절반이 "라벨이 맞나"
    # 인데, 그렇다면 의심스러운 것부터 훑는 편이 같은 시간에 더 많이 잡는다.
    order = st.selectbox(
        "정렬", list(CASE_ORDERS), label_visibility="collapsed",
        help="의심스러운 순: 지어낸 인용 · 등급 ≤1 · 무결성 플래그 · 분류 실패 · 부가 라벨")
    view = CASE_ORDERS[order](view)

    if (found, order, picked) != state.get("case_scope"):
        # 목록이 통째로 달라졌다. 자리를 그대로 두면 엉뚱한 케이스를 보게 된다.
        state.case_scope = (found, order, picked)
        state.case_idx = 0
        state.case_nonce = state.get("case_nonce", 0) + 1

    # 열 열 개를 늘어놓으면 좁은 화면에서 질문이 끝까지 밀려 안 보인다.
    # 고르는 데 필요한 것만 남기고 나머지는 아래 상세가 편다.
    total = len(view)
    state.setdefault("case_idx", 0)
    # 표를 새 위젯으로 만들면 선택이 지워진다. 버튼으로 옮겼는데 표에는 옛 행이
    # 계속 칠해져 있으면 어느 쪽이 지금 보고 있는 것인지 알 수 없다.
    state.setdefault("case_nonce", 0)
    # 필터가 바뀌면 행 수가 준다. 손대지 않으면 없는 행을 가리킨다.
    state.case_idx = max(0, min(state.case_idx, total - 1))

    # st.dataframe 의 선택은 **프로그램으로 못 옮긴다** - session_state 에 넣어도
    # 조용히 무시된다(실제로 확인했다). 버튼으로 옮긴 자리에 표시가 따라오게
    # 하려면 체크 상태를 우리가 쥐고 있어야 해서 data_editor 를 쓴다.
    compact = view[["부서", "턴", "case명", "등급", "문서수", "질문"]].copy()
    compact.insert(0, "보기", False)
    compact.iloc[state.case_idx, 0] = True

    edited = st.data_editor(
        compact, **WIDE, height=280, hide_index=True,
        key=f"cases-{state.case_nonce}",
        disabled=[c for c in compact.columns if c != "보기"],
        column_config={
            "보기": st.column_config.CheckboxColumn(
                "보기", help="체크한 행이 아래에 펼쳐진다. 이전/다음 버튼도 여기를 옮긴다"),
            "case명": st.column_config.TextColumn("무엇이", width="medium"),
            "등급": st.column_config.NumberColumn(
                "등급", width="small",
                help="증거 등급. 4 코드 확정 · 3 근거 확정 · 2 확신(p≥0.9) · 1 기울어짐 · 0 불일치"),
            # 열어보지 않고도 검색 0건 턴을 훑을 수 있어야 한다 - 그게 T1 의 갈림길이다.
            "문서수": st.column_config.NumberColumn(
                "문서", help="그때 검색된 청크 수. 0 이면 검색 결과가 없었다 (T1 의 갈림길)"),
            "질문": st.column_config.TextColumn(
                "질문(정리)", width="large",
                help="대명사와 생략을 푼 것. 사용자가 실제로 친 말은 아래 상세에 있다")})

    # 새로 체크한 행이 있으면 그쪽으로 간다. 한 번에 하나만 켜지도록, 다음 실행에
    # 데이터를 다시 만들면서 나머지가 꺼진다.
    checked = [i for i, on in enumerate(edited["보기"]) if on]
    moved_by_click = [i for i in checked if i != state.case_idx]
    if moved_by_click:
        state.case_idx = moved_by_click[0]
        state.case_nonce += 1
        st.rerun()

    # 표에서 고르는 것만으로는 스무 건을 훑을 수 없다. 한 건 보고 다음 건으로
    # 가는 것이 이 화면에서 가장 잦은 동작이라 버튼을 둔다.
    if _navigate(state, total, "top"):
        st.rerun()

    detail(view.iloc[state.case_idx])

    # 상세를 다 읽고 나면 화면 맨 아래다. 다음 건으로 가려고 표까지 다시 올라가는
    # 것이 이 화면에서 제일 잦은 왕복이라 여기도 둔다.
    st.divider()
    if _navigate(state, total, "bottom"):
        st.rerun()


def _navigate(state, total: int, where: str) -> bool:
    """이전 / 위치 / 다음. 눌렸으면 True.

    같은 버튼을 위아래에 두므로 key 를 나눈다 - 라벨이 같은 위젯 둘은
    streamlit 이 거절한다.
    """
    back, position, forward = st.columns([1, 2, 1])
    moved = False
    if back.button("← 이전", key=f"prev-{where}", **WIDE,
                   disabled=state.case_idx <= 0):
        state.case_idx -= 1
        moved = True
    position.markdown(f"**{state.case_idx + 1} / {total}**")
    if forward.button("다음 →", key=f"next-{where}", **WIDE,
                      disabled=state.case_idx >= total - 1):
        state.case_idx += 1
        moved = True
    if moved:
        # 표를 새 위젯으로 만든다. data_editor 는 사용자가 만진 것을 위젯 상태에
        # 들고 있어서, 새로 그린 데이터보다 그쪽이 이긴다 - 그러면 버튼으로
        # 옮겨도 체크가 옛 행에 남는다.
        state.case_nonce += 1
    return moved


# 앞 질문 · 답변 · 불만 상자. 넘치면 이 높이 안에서 스크롤한다.
ANSWER_BOX_PX = 300

# 폭 1칸이 그 높이에 담는 글자 수. 세 상자가 1:3:1 이라 좁은 칸은 한 줄에
# 3분의 1밖에 안 들어간다 - 같은 임계값을 쓰면 좁은 칸은 넘쳐도 안 잡히고,
# 넓은 칸은 안 넘쳤는데 잘린 것처럼 보인다. 그래서 폭에 비례시킨다.
# 한글 40자쯤이 3칸 폭 한 줄, 여덟 줄에 문단 사이가 붙어 300px 다.
FITS_PER_WEIGHT = 100


def history_text(prior: list[str]) -> str:
    """앞 질문 전부를 한 상자에. 마지막 것이 판정 대상의 질문이라 굵게 친다.

    직전 질문만 보이면 "미주 말고 유럽" 처럼 요구가 좁혀진 것이나 앞 조건을 잊은
    것(G2:조건)을 화면에서 확인할 수 없다 - 관측은 이 질문들을 전부 보고 판정했다.
    """
    if not prior:
        return "—"
    if len(prior) == 1:
        return prior[0]
    lines = [f"{i}. {q}" for i, q in enumerate(prior[:-1], 1)]
    lines.append(f"**{len(prior)}. {prior[-1]}**  ← 이 답이 판정 대상")
    return "\n\n".join(lines)


def _bordered(text: str) -> None:
    with st.container(border=True):
        st.write(text)


def boxed(text: str, weight: int, paint) -> None:
    """폭에 비해 길면 고정 높이 안에서 스크롤한다.

    긴 글 하나가 세로로 늘어나면 양옆 상자는 저 위에 남고 아래 Step 1·2·3 이
    화면 밖으로 밀린다 - 판정 경로를 보려고 연 패널인데 정작 경로가 안 보인다.

    streamlit 에 max-height 가 없어서(높이는 고정이거나 내용에 맞추거나 둘뿐)
    넘칠 때만 상자를 씌운다. 짧은 글까지 고정 높이로 두면 아래가 비어서 더
    읽기 나쁘다.
    """
    if len(text) <= FITS_PER_WEIGHT * weight:
        paint(text)
        return
    with st.container(height=ANSWER_BOX_PX, border=False):
        paint(text)
    # 잘린 상자에 아무 표시가 없으면 "여기서 끝났나"로 읽힌다.
    st.caption(f"{len(text):,}자 — 상자 안에서 스크롤")


def chunk_table(chunks: list, row: pd.Series) -> None:
    """검색된 청크를 표로. 전문은 고른 하나만 펼친다.

    전에는 상세 맨 아래 접힘 상자에 청크를 통째로 늘어놓았다. 문서가 있었는지조차
    스크롤해서 봐야 했고, 열면 500자짜리 열 개가 쏟아져 어느 것이 판정에 쓰였는지
    알 수 없었다. 표로 두면 개수 · 길이 · 근거 여부가 한 화면에 들어오고, 전문은
    필요한 것만 본다.

    근거는 인용문이 아니라 청크 인덱스와 확률이다 - ③ 충족도가 청크마다 "답하나"
    를 묻고 p 가 임계를 넘은 것만 근거로 선다.
    """
    suf = (row["_원본"].get("classification", {}).get("evidence") or {}).get("sufficiency") or {}
    evidence = {e.get("chunk_index"): e for e in suf.get("evidence") or []}

    if not chunks:
        st.warning("그때 검색된 문서가 0건이다. 서비스가 '검색 없이 답할 수 있다' 고 "
                   "판단했을 수 있다 (T1) — 충족도는 물어볼 것도 없이 insufficient 다.", icon="🔍")
        return

    table = pd.DataFrame([{
        "번호": i,
        "근거": "✓" if i in evidence else "",
        "p": evidence[i].get("p") if i in evidence else None,
        "길이": len(c),
        "첫 줄": c.strip().splitlines()[0][:120] if c.strip() else "(빈 청크)",
    } for i, c in enumerate(chunks)])
    st.markdown(f"**그때 검색된 문서 {len(chunks)}개** — ③ 충족도가 이것만 보고 청크마다 판정했다")
    st.dataframe(
        table, **WIDE, hide_index=True, height=min(240, 40 + 36 * len(chunks)),
        column_config={
            "번호": st.column_config.NumberColumn("청크", width="small"),
            "근거": st.column_config.TextColumn(
                "근거", width="small",
                help="③ 충족도가 근거로 세운 청크 (p 가 임계를 넘은 것)"),
            "p": st.column_config.NumberColumn(
                "p", width="small", format="%.2f",
                help="이 청크가 질문에 답하는 내용을 담고 있을 확률"),
            "길이": st.column_config.NumberColumn("글자", width="small"),
            "첫 줄": st.column_config.TextColumn("첫 줄", width="large")})

    # 전문은 하나씩. 열 개를 다 펼치면 아래 코드 검증이 화면 밖으로 밀린다.
    picked = st.selectbox(
        "청크 전문", range(len(chunks)), label_visibility="collapsed",
        format_func=lambda i: (f"청크 {i}" + (" · 근거" if i in evidence else "")
                               + f" · {len(chunks[i])}자"),
        key=f"chunk-{row.get('대화', '')}-{row.get('턴', 0)}")
    with st.container(border=True, height=ANSWER_BOX_PX):
        st.write(chunks[picked])
    if picked in evidence:
        st.success(_evidence_line(evidence[picked]))


def _evidence_line(ev: dict) -> str:
    """근거 청크 한 줄 — `청크 3 · p=0.93 · 출처 retrieved`."""
    p = ev.get("p")
    parts = [f"청크 {ev.get('chunk_index')}"]
    if p is not None:
        parts.append(f"p={float(p):.2f}")
    if ev.get("source"):
        parts.append(f"출처 {ev['source']}")
    if ev.get("scope"):
        parts.append(f"범위 {ev['scope']}")
    return " · ".join(parts)


def detail(row: pd.Series) -> None:
    """한 케이스의 판정 경로를 원본 값 그대로 보여준다."""
    st.markdown(f"### {row['case']} · {row['case명']}")
    if tx.desc(row["case"]):
        st.caption(tx.desc(row["case"]))
    meta = st.columns(5)
    # 신뢰도는 증거 등급에서 나온다. 등급을 보이고 신뢰도는 그 옆에 적는다 -
    # "high" 보다 "4 코드 확정" 이 왜 믿을 수 있는지를 말한다.
    grade = None if pd.isna(row["등급"]) else int(row["등급"])
    meta[0].metric("증거 등급", GRADE_LABEL.get(grade, "—"),
                   delta=CONF_LABEL.get(row["신뢰도"], row["신뢰도"]) or None, delta_color="off",
                   help="4 코드 확정 · 3 근거 확정(⑦ 2차 일치 · 주장 대조) · 2 확신(p≥0.9) · "
                        "1 기울어짐(0.6≤p<0.9) · 0 불일치. 주 라벨은 등급이 제일 높은 후보다.")
    meta[1].metric("충족도", row["충족도"] or "—",
                   help="③ 청크마다 '답하나' 를 물어 p≥임계인 청크가 있으면 sufficient, "
                        "max p 가 중간이면 partial, 그 외 insufficient. 태그 2차불일치가 "
                        "붙었으면 ⑦ 되물음이 1차와 어긋나 등급이 내려간 것이다.")
    meta[2].metric("근거 활용", row["근거활용"] or "—")
    # llm_calls 는 **이번 실행에서 실제로 부른 횟수**다. 캐시가 맞으면 0 이 된다.
    # 그대로 "LLM 호출 0" 이라 적으면 G5 처럼 판정이 여러 번 필요한 라벨도
    # 모델이 관여 안 한 것처럼 읽힌다. 어디까지 봤는지를 evidence 로 보여준다.
    ran = [name for name, key in [("읽기", "legibility"), ("관측", "observation"),
                                  ("충족도", "sufficiency"), ("주장", "claims"),
                                  ("memory", "memory"), ("일관성", "consistency")]
           if (row["_원본"].get("classification", {}).get("evidence") or {}).get(key)]
    meta[3].metric("판정 단계", " · ".join(ran) if ran else "코드만",
                   help=f"이번 실행의 LLM 호출 {row['LLM호출']}회 · 결정(kev) 호출 {row['kev호출']}회. "
                        "0 이면 캐시에 있었거나 코드만으로 판정된 것이다.")
    # 문서가 있었나는 스크롤해서 찾을 것이 아니다. 0 건은 T1 의 갈림길이고,
    # 근거 건수가 옆에 있어야 "문서는 있었는데 안 썼다" 가 한 줄에서 읽힌다.
    chunk_n = int(row["문서수"])
    meta[4].metric("검색 문서", f"{chunk_n}개" if chunk_n else "0개",
                   delta=f"근거 {int(row['인용수'])}" if chunk_n else "검색 결과 없음",
                   delta_color="off" if chunk_n else "inverse",
                   help="③ 충족도가 이 청크만 보고 판정했다. 0 이면 서비스가 "
                        "'검색 없이 답할 수 있다' 고 판단했을 수 있다 (T1).")

    # 판정 대상인 답변과 사용자의 불만은 접어두면 안 된다. 이 패널은 "왜 이
    # 라벨이지"에 답하는 자리인데, 무엇을 보고 판정했는지가 없으면 답이 안 된다.
    # 전에는 "원본 로그" 접힘 상자 안에 있어서 한 번 더 눌러야 나왔다.
    original = row["_원본"]
    prior = original.get("pre_queries") or []

    # 한 턴의 이야기를 시간순으로 늘어놓는다: 물었다 → 답했다 → 불만이다.
    # 앞 질문을 caption 으로 흘리면 배경으로 읽혀서, 답변이 무엇에 대한
    # 답이었는지가 안 보인다. 셋 다 상자에 넣되 색으로 역할을 가른다.
    # 셋 중 답변이 제일 길고, 판정 대상이기도 하다. 같은 폭을 주면 답변만
    # 여러 줄로 접히고 양옆은 비어서, 정작 봐야 할 것이 제일 읽기 나쁘다.
    asked, said, complained = st.columns([1, 3, 1])
    with asked:
        st.markdown("**앞 질문**")
        st.caption("마지막 질문에 대한 답이 판정 대상이다. 그 앞 질문들은 관측이 "
                   "맥락으로 봤다 — 요구가 좁혀졌는지 · 앞 조건을 잊었는지(G2)가 여기서 갈린다")
        boxed(history_text(prior), 1, _bordered)
    with said:
        st.markdown("**비판받은 답변**")
        st.caption("이것이 판정 대상이다")
        boxed(original.get("llm_ans_on_last_q", "") or "—", 3, st.info)
    with complained:
        st.markdown("**사용자의 불만**")
        st.caption("이 발화가 라벨을 정한다")
        boxed(original.get("current_query", "") or "—", 1, st.warning)

    st.info(f"**판정 근거** — {row['판정근거']}")
    evidence = row["_원본"].get("classification", {}).get("evidence") or {}
    legibility = evidence.get("legibility")
    if legibility and legibility.get("illegible_p") is not None:
        # ① 읽기 판정의 확률. I2 가 됐으면 왜 그랬는지, 안 됐으면 얼마나 가까웠는지.
        p = float(legibility["illegible_p"])
        line = f"① 읽기 판정 — 읽을 수 없을 확률 {p:.2f}"
        (st.error if row["case"] == COLLAPSED else st.caption)(line)

    # 플래그는 경고다 - 이 턴의 기록을 믿을 수 없고, G2 를 묻지 않았다는 뜻이다.
    # 이벤트 · 태그 · 부가는 주 라벨에 딸린 사실이라 caption 으로 흘린다.
    for flag in row["플래그"]:
        st.warning(f"무결성 플래그 {tx.label(flag)} — {tx.desc(flag)}", icon="🚩")
    if row["이벤트"]:
        st.caption("이벤트: " + " · ".join(tx.label(e) for e in row["이벤트"])
                   + " (분모 밖 — 답변은 따로 끝까지 판정했다)")
    if row["태그"]:
        st.caption("태그: " + " · ".join(
            f"{t} ({tx.TAGS[t]})" if t in tx.TAGS else t for t in row["태그"]))
    if row["부가"]:
        st.caption(f"부가 라벨: {', '.join(row['부가'])} "
                   "(후보로 섰지만 등급에서 밀린 것 — 주 라벨과 별개로 성립한다)")
    for note in row["주의"]:
        st.warning(note, icon="⚠️")

    left, right, third = st.columns(3)
    with left:
        st.markdown("**Step 1 · 관측** — 문서를 주지 않고 사용자 쪽 신호만 본다")
        st.json({"정리된 질문": row["질문"], "원한 것": row["원한것"],
                 "불만 유형": row["불만유형"], "질문 성격": row["질문성격"]}, expanded=True)
    with right:
        st.markdown("**Step 2 · 충족도** — 챗봇 답변을 주지 않고 문서만 본다")
        suf = evidence.get("sufficiency")
        if suf:
            # 근거는 청크 인덱스와 확률이다. 인용 대조는 없어졌다.
            for ev in suf.get("evidence") or []:
                st.success(_evidence_line(ev))
            if not (suf.get("evidence") or []):
                st.caption("근거로 선 청크가 없다 (p 가 임계를 넘은 청크 없음).")
            if row["없던것"]:
                st.caption(f"없던 것: {row['없던것']}")
        else:
            st.caption("관측까지 가지 않았거나(확정 사건) 청크가 없어 판정하지 않았다.")
    with third:
        # Step 1·2 는 자기 칸이 있는데 Step 3 만 지표 하나로 끝났다. 무엇을
        # 봤고 무슨 뜻인지가 없으면 G5:안씀 과 G5:어긋남 이 왜 갈렸는지 알 수 없다.
        st.markdown("**Step 3 · 근거 활용** — 답변의 주장을 뽑아 근거 청크와 대조한다")
        used = row["근거활용"]
        meaning = {"used": "근거를 썼다. 그런데도 불만이면 기대와 다른 것이다",
                   "ignored": "근거에 답이 있는데 답변이 쓰지 않았다 (G5:안씀)",
                   "contradicted": "답변이 근거와 어긋나는 주장을 했다 (G5:어긋남)"}
        if used:
            st.metric("answer_used_rag", used)
            st.caption(meaning.get(used, ""))
        claims = evidence.get("claims")
        if claims:
            st.dataframe(
                pd.DataFrame(claims), **WIDE, hide_index=True,
                height=min(240, 40 + 36 * len(claims)),
                column_config={
                    "text": st.column_config.TextColumn("주장", width="large"),
                    "expected_source": st.column_config.TextColumn(
                        "출처", width="small", help="doc 만 근거와 대조한다. tool 은 수치 대조, "
                                                  "general 은 미검증주장 태그"),
                    "verdict": st.column_config.TextColumn("판정", width="small"),
                    "p": st.column_config.NumberColumn("p", width="small", format="%.2f")})
        if not used and not claims:
            st.caption("주장 추출까지 가지 않았다 — 확정 사건이거나 청크가 없었다.")
        memory = evidence.get("memory")
        if memory:
            st.caption(f"⑤ memory 반영: {memory.get('use')} (p={float(memory.get('p', 0)):.2f})")
        consistency = evidence.get("consistency")
        if consistency:
            st.caption("⑥ 앞 답변과 모순 확률: " + " · ".join(
                f"#{i} {float(p):.2f}" for i, p in consistency.items()))

    # 청크는 Step 1·2·3 아래다. 판정 경로를 먼저 읽고 "그래서 문서에 뭐가 있었나"
    # 로 내려가는 순서다 - 청크를 위에 두면 표 · 선택 상자 · 전문 상자가 화면을
    # 채워서, 정작 판정이 어떻게 갈렸는지가 스크롤 밖으로 밀린다.
    chunk_table(original.get("chunk_data", []), row)

    if row["검증"]:
        st.markdown("**코드 검증** — 모델 없이, 코드가 본 것")
        st.caption("I1(자원 부족 문구) · I2(붕괴 규칙) · S2(인젝션) · S3(정보 유출) · "
                   "G1(언어 · 포맷 · 길이) · G6(계산 · 코드) · U2(질문에 개인정보)는 "
                   "**여기서** 판정된다. 등급 4 인 이유이고, 모델 판정이 무엇을 말하든 "
                   "이쪽이 이긴다. 전 턴에 돌고 위반한 검증기 이름은 태그로도 남는다.")
        checks = pd.DataFrame(row["검증"])
        st.dataframe(
            checks, **WIDE, hide_index=True,
            column_config={
                "name": st.column_config.TextColumn("무엇을"),
                "verdict": st.column_config.TextColumn(
                    "결과", help="violated 면 그 라벨이 등급 4 후보로 선다"),
                "detail": st.column_config.TextColumn("근거", width="large")})



if __name__ == "__main__":
    main()
