"""llm_eval / llm_emotion 라벨 테이블.

**표는 저장소의 `configs/query_taxonomy.md` · `configs/emotion_taxonomy.md` 에 있고,
import 할 때 거기서 읽는다.** 한동안 이름·점수를 빼고 자리표시자만 두었는데, 기밀이
아니라는 판단이 서서 되돌렸다. 빼 두는 값이 실제로 비쌌다 — 운영 세팅에서 문서
두 개를 따로 챙겨야 했고, 안 챙기면 필터가 **에러 없이 0건**을 돌려주는 가장
찾기 어려운 실패가 났다. 그 실패를 막으려고 둔 가드도 같이 사라졌다.

코드가 아니라 문서에 두는 이유는 분류 체계가 바뀔 때 고치는 자리가 .md 한 곳이어야
하기 때문이다. 사본에도 `configs/` 째로 실려 나가므로 실행 환경에서 따로 챙길 것은
없다. 다른 점수표로 돌려보고 싶으면 설정으로 덮어쓴다 (선택):

    labels:
      query:   configs/query_taxonomy.md
      emotion: configs/emotion_taxonomy.md

형식은 한 줄에 `A. 이름 -> 점수`, `#` 줄로 그룹을 묶는다.

각 라벨에는 점수가 붙어 있고, 이 점수가 **만족도 대리 지표**다. 명시적 부정
피드백이 0점, 명시적 긍정 피드백이 100점인 척도라 방향이 분명하다. 낮은 점수 =
직전 답변이 만족스럽지 않았다는 신호이므로, 필터가 여기에 걸린다.

기록된 점수의 계산식(예시 데이터로 검증함):

    *_score       = Σ(확률 × 라벨점수) / Σ확률      확률가중 기대점수
    *_score_top1  = argmax 라벨의 점수

필터 파일이 `query_scores`를 들고 있는 이유가 이것이다. 점수표를 바꾸면 기록된
`llm_eval_score`는 낡은 값이 되므로 `llm_eval_alternatives`에서 다시 계산해야 한다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Label:
    letter: str
    name: str
    score: float
    group: str = ""
    # 문서·로그에서 다르게 쓰이는 표기. 오타도 포함한다.
    # eval 시스템이 문서의 오타를 그대로 뱉을 수 있는데, 어느 쪽이 실제인지
    # 확인할 방법이 없으므로 둘 다 받는 편이 안전하다.
    aliases: tuple[str, ...] = ()


def normalize_name(name: str) -> str:
    """라벨 이름 대조용 정규화.

    같은 라벨이 세 군데에서 다르게 적힌다. 필터 파일은 "I. 어떤라벨"(붙여쓰기),
    taxonomy 문서는 "어떤 라벨"(띄어쓰기), 로그의 result 값은 또 다를 수 있다.
    공백을 지우고 맞춘다 — 안 하면 필터가 에러 없이 0건을 돌려준다.
    가장 찾기 어려운 실패다.
    """
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", name)).lower()


# ---------------------------------------------------------------------------
# taxonomy 문서 파서
# ---------------------------------------------------------------------------

_LINE = re.compile(r"^([A-Z])\.\s*(.+?)\s*->\s*([\d.]+)", re.M)


def parse_markdown_table(text: str) -> dict[str, Label]:
    """taxonomy .md 를 파싱한다. 이 파서가 읽은 것이 곧 라벨 표다."""
    table = {}
    group = ""
    for line in text.splitlines():
        if line.startswith("#"):
            group = line.lstrip("# ").strip()
            continue
        match = _LINE.match(line.strip())
        if match:
            letter, name, score = match.groups()
            table[letter] = Label(letter, name.strip(), float(score), group)
    return table


def load_markdown_table(path: str | Path) -> dict[str, Label]:
    return parse_markdown_table(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 테이블 — 저장소의 taxonomy 문서에서 읽는다
#
# 글자(A~R / A~I)는 형식이다 — 파서가 alternatives 의 글자를 읽는다. 이름과 점수는
# 로그에 적힌 값과 같아야 한다. 다르면 필터가 에러 없이 0건을 돌려준다.
# ---------------------------------------------------------------------------

QUERY_LETTERS = "ABCDEFGHIJKLMNOPQR"
EMOTION_LETTERS = "ABCDEFGHI"

# 저장소 루트의 configs/. 사본에도 그대로 실려 나가므로 실행 위치와 무관하게 여기다.
_CONFIGS = Path(__file__).resolve().parents[2] / "configs"

# 문서에 적을 수 없는 것 하나 — 표기 변형. eval 시스템이 문서의 오타를 그대로
# 뱉은 적이 있는데, 어느 쪽이 실제인지 확인할 방법이 없어 둘 다 받는다.
_EXTRA_ALIASES = {"D": ("예시 요첟",)}


def _load_shipped(name: str, letters: str, aliases: dict = None) -> dict[str, "Label"]:
    path = _CONFIGS / name
    if not path.exists():
        raise RuntimeError(
            f"라벨 문서가 없습니다: {path}\n"
            f"  저장소에 함께 다니는 파일입니다. 사본이 깨졌는지 확인하세요.")
    table = load_markdown_table(path)
    missing = [x for x in letters if x not in table]
    if missing:
        raise RuntimeError(f"{path} 에 라벨이 빠졌습니다: {''.join(missing)}")
    for letter, extra in (aliases or {}).items():
        table[letter] = replace(table[letter], aliases=extra)
    return table


QUERY_LABELS: dict[str, Label] = _load_shipped(
    "query_taxonomy.md", QUERY_LETTERS, _EXTRA_ALIASES)
EMOTION_LABELS: dict[str, Label] = _load_shipped(
    "emotion_taxonomy.md", EMOTION_LETTERS)

DEFAULT_QUERY_SCORES = {letter: label.score for letter, label in QUERY_LABELS.items()}
DEFAULT_EMOTION_SCORES = {letter: label.score for letter, label in EMOTION_LABELS.items()}


def install(query: Optional[dict] = None, emotion: Optional[dict] = None) -> list[str]:
    """테이블을 덮어쓴다. 무엇이 들어왔는지 돌려준다.

    모듈 전역을 바꾸는 것은 config.apply() 와 같은 방식이다 - 필터·조사기가 이미
    이 전역을 읽고 있어서, 그쪽을 전부 인자로 바꾸는 것보다 얕게 끝난다.
    """
    changed = []
    for name, table, target in (("query", query, QUERY_LABELS),
                                ("emotion", emotion, EMOTION_LABELS)):
        if not table:
            continue
        target.clear()
        target.update(table)
        changed.append(f"labels.{name} ({len(table)}개)")
    DEFAULT_QUERY_SCORES.clear()
    DEFAULT_QUERY_SCORES.update({k: v.score for k, v in QUERY_LABELS.items()})
    DEFAULT_EMOTION_SCORES.clear()
    DEFAULT_EMOTION_SCORES.update({k: v.score for k, v in EMOTION_LABELS.items()})
    return changed


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------

def resolve(spec: str, table: dict[str, Label]) -> Optional[Label]:
    """라벨 지정자를 Label 로 바꾼다.

    받아들이는 형태:
      "I"              글자만
      "I. 어떤라벨"     필터 파일 형태 (붙여쓰기)
      "어떤 라벨"       로그의 result 값 (띄어쓰기)
    """
    if not spec:
        return None
    text = spec.strip()

    match = re.match(r"^([A-Z])[.)]\s*(.*)$", text)
    if match and match.group(1) in table:
        return table[match.group(1)]
    if len(text) == 1 and text.upper() in table:
        return table[text.upper()]

    wanted = normalize_name(match.group(2) if match else text)
    for label in table.values():
        names = (label.name,) + label.aliases
        if any(normalize_name(n) == wanted for n in names):
            return label
    return None


def resolve_all(specs, table: dict[str, Label]) -> tuple[set[str], list[str]]:
    """지정자 목록을 글자 집합으로. 못 찾은 것은 따로 돌려준다.

    조용히 버리면 오타 하나로 필터가 통째로 빗나간다.
    """
    letters, unknown = set(), []
    for spec in specs or []:
        label = resolve(str(spec), table)
        if label:
            letters.add(label.letter)
        else:
            unknown.append(str(spec))
    return letters, unknown


def expected_score(
    alternatives: list[dict],
    scores: dict[str, float],
    fallback: Optional[float] = None,
) -> Optional[float]:
    """확률가중 기대점수. 기록된 *_score 와 같은 계산이다.

    점수표를 바꿔가며 필터를 걸 수 있게 하려면 기록값이 아니라 이 함수로 다시 계산해야
    한다. alternatives 가 비어 있으면 재계산할 수 없으므로 기록값을 그대로 쓴다.
    """
    usable = [
        (a["label"], a["probability"])
        for a in alternatives
        if a.get("label") in scores and a.get("probability")
    ]
    mass = sum(p for _, p in usable)
    if not usable or mass <= 0:
        return fallback
    return sum(scores[letter] * p for letter, p in usable) / mass


