"""분류 체계 v3 — 묶음 라벨 · 플래그 · 이벤트 · 태그 · 증거 등급.

설계는 docs/design/taxonomy_v3.md. 여기는 그 표를 코드로 옮긴 것이다.

라벨은 `묶음글자 + 번호` 다 (`G5`). 묶음은 **고치는 사람**이다 — 같은 증상도 문서팀이
고칠 일과 프롬프트 담당이 고칠 일은 다르고, 증상으로 묶으면 집계가 아무도 지목하지
못한다. 같은 묶음 안의 "무엇을 어겼나" 는 라벨이 아니라 태그다 — 라벨이 많으면 셀이
비어 표가 안 읽힌다.

세 종류를 가른다.
  failure  실패 라벨. 실패율 분모에 들어간다
  flag     무결성 플래그 (C). 그 턴의 기록을 믿을 수 없다. 분모 밖
  event    이벤트 (U2). 챗봇 실패가 아닌 사건. 분모 밖, 카운트만

신뢰도는 고정값이 아니라 **주 라벨의 증거 등급**에서 나온다 (features/arbitrate).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Group:
    group_id: str      # "G"
    name: str          # "생성"
    word: str          # "generation" — 문서 표기 G(generation)
    owner: str         # 고칠 곳


GROUPS: dict[str, Group] = {
    g.group_id: g for g in [
        Group("N", "실패 아님", "none", "필터"),
        Group("U", "입력", "user", "질문 유도 · UI"),
        Group("C", "맥락 기록", "context", "로그 · 적재 · 맥락 관리"),
        Group("T", "도구 호출", "tool", "오케스트레이션 · 도구 연동"),
        Group("D", "검색 근거", "document", "검색기 · 문서"),
        Group("G", "생성", "generation", "생성 프롬프트 · 모델"),
        Group("S", "정책 · 보안", "safety", "권한 정책 · 입력 방어 · 출력 필터"),
        Group("I", "서빙", "infra", "인프라 · 모델 서빙"),
    ]
}


@dataclass(frozen=True)
class Label:
    label_id: str
    name: str
    kind: str                  # failure · flag · event
    desc: str = ""

    @property
    def group_id(self) -> str:
        return self.label_id[0]

    @property
    def group(self) -> Group:
        return GROUPS[self.group_id]

    # ---- 옛 이름과의 호환. 대시보드 · 전달본이 case_id · type_id 로 읽는다 ----
    @property
    def case_id(self) -> str:
        return self.label_id

    @property
    def type_id(self) -> str:
        return self.group_id

    @property
    def type_name(self) -> str:
        return self.group.name

    @property
    def category(self) -> str:
        return self.group.word

    @property
    def diagnosable(self) -> bool:
        return True


_ROWS = [
    # (라벨, 이름, 종류, 설명)
    ("N0", "정상 후속", "failure",
     "후속 발화가 앞 답변을 문제 삼지 않는다. 새 질문이거나 수긍이다. 실패율 분모에서 빼고, "
     "쌓이면 필터를 좁힐 신호로 읽는다. unclassified(판정이 안 섬)와 다르다."),

    ("U1", "낼 수 없는 형태 요구", "failure",
     "링크 · 이미지 · 파일 첨부처럼 이 서비스가 낼 수 없는 형태를 요구했다. "
     "낼 수 있는 형식인데 안 지킨 것은 G1."),
    ("U2", "질문에 개인정보", "event",
     "사용자가 질문에 주민번호 · 연락처 등 개인정보를 넣었다. 챗봇 실패가 아니라 입력 "
     "사건이다 — 그 턴의 답변은 따로 끝까지 판정한다."),

    ("C1", "앞 턴 누락", "flag",
     "대화에 앞 턴이 있는데 history_chat 에 빠져 있다. 모델이 못 본 것인지 로그/적재가 "
     "떨어뜨린 것인지 로그만으로 못 가른다. 이 턴의 G2(맥락) 는 판정하지 않는다."),
    ("C2", "memory 어긋남", "flag",
     "memory 가 있는데 그 내용이 대화 어디에도 없다. memory 모듈이나 적재의 결함이다. "
     "이 턴의 G2[memory] 는 판정하지 않는다."),

    ("T1", "호출 없음", "failure",
     "업무 질문인데 도구(검색 포함)를 하나도 부르지 않고 답했다. tool_calls 와 "
     "retrieved_data 가 모두 비어 있다. 가져왔는데 빗나간 D1 · T2 와 고칠 곳이 다르다."),
    ("T2", "결과가 질문과 무관", "failure",
     "업무 도구를 불렀고 결과도 왔는데 그 내용이 질문에 답하지 못한다. 도구 선택 · 인자의 "
     "문제다. 검색 도구 결과에 답이 없는 것은 D1."),
    ("T3", "빈 결과에 단정", "failure",
     "도구 결과가 비었는데(0건 · 빈 값) 답변이 수치 · 사실을 단정했다. 도구로 증명되는 "
     "유일한 할루시네이션이다."),

    ("D1", "검색 근거에 답 없음", "failure",
     "검색이 가져온 청크 어디에도 요구에 답하는 내용이 없다. 검색기가 못 찾은 것인지 "
     "문서가 애초에 없는 것인지는 코퍼스 전체를 봐야 갈린다 — 부서 편중으로만 추정."),

    ("G1", "명시 요구 불이행", "failure",
     "언어 · 길이 · 포맷 · 어조 요구를 지키지 않았다. 어느 요구인지는 태그(G1:언어 …)."),
    ("G2", "맥락 불이행", "failure",
     "앞에서 정한 조건 · 앞 답변의 약속 · memory 의 사용자 정보를 어겼거나 앞 답변과 "
     "모순된다. 어느 맥락인지는 태그(G2:조건 …). C1 플래그가 선 턴에서는 내지 않는다."),
    ("G3", "의도와 다른 답", "failure",
     "물은 것과 다른 것을 답했다. 다른 라벨에 걸리지 않은 내용 불만의 잔여다 — "
     "구조적으로 다른 원인을 삼키지 못하게 맨 뒤에 둔다."),
    ("G4", "복합 일부만 답", "failure",
     "복합 질문의 일부만 답했다. 사용자가 복합 질문을 한 것 자체는 태그(복합질문)."),
    ("G5", "근거 활용 실패", "failure",
     "근거가 충분했는데 안 썼거나, 어긋나는 주장을 했거나, 인용을 지어냈다. "
     "어느 쪽인지는 태그(G5:안씀 · G5:어긋남 · G5:지어낸인용 · G5:과거근거)."),
    ("G6", "일반 지식 · 계산 · 코드 오류", "failure",
     "문서와 무관한 질문의 오답. 등식 · 날짜 · 코드 문법처럼 코드가 확인한 것만 센다."),

    ("S1", "정책 거절", "failure",
     "정책 · 권한을 이유로 거절했고 사용자가 불만을 표했다. 불만 없는 거절은 정당한 "
     "거절이라 N0 다. 권한 부족 거절과 로그상 구분되지 않는다."),
    ("S2", "인젝션 수행", "failure",
     "문서 안에 숨은 지시를 모델이 그대로 수행했다. 지시문이 있기만 한 것은 아니다."),
    ("S3", "답변 정보 유출", "failure",
     "질문에 없던 개인정보 패턴이 답변에 나왔다."),

    ("I1", "자원 부족 문구", "failure",
     "모델 자원을 확보하지 못해 서비스가 정해진 안내 문구를 대신 내보냈다. 모델이 답을 "
     "만든 적이 없다."),
    ("I2", "붕괴 · 읽을 수 없음", "failure",
     "같은 글자의 반복, 토큰 잡탕, 내부 유출처럼 사람이 읽을 수 없는 답변이다. "
     "코드 규칙이 잡으면 high, 읽기 판정이 잡으면 medium."),
]

LABELS: dict[str, Label] = {row[0]: Label(*row) for row in _ROWS}
CASES = LABELS                   # 옛 이름

FAILURES = [l for l in LABELS.values() if l.kind == "failure"]
FLAGS = [l for l in LABELS.values() if l.kind == "flag"]
EVENTS = [l for l in LABELS.values() if l.kind == "event"]

# 중재의 동률 깨기. 같은 등급이면 앞이 이긴다. 이유는 설계 문서의 "후보와 중재".
ORDER = ["I1", "I2", "S2", "S3", "N0", "S1", "U1", "T1", "T3", "D1", "T2",
         "G1", "G5", "G6", "G4", "G2", "G3"]
assert set(ORDER) == {l.label_id for l in FAILURES}

UNCLASSIFIED = "unclassified"
OUT_OF_TAXONOMY = "out_of_taxonomy"     # 옛 이름. v3 에서는 내지 않는다 — unclassified 로 합친다
UNDIAGNOSABLE: set[str] = set()         # v3 에는 판정 불가 라벨을 두지 않는다

# 태그. 라벨 꼴(`G1:언어`)과 단독 꼴(`복합질문`)이 있다. 코드 검증기 이름도 태그가 된다.
TAGS: dict[str, str] = {
    "U3": "질문 불완전 — 모호하거나 지시 대상이 안 풀린다",
    "되묻기없음": "질문이 불완전했는데 답변이 되묻지 않았다",
    "G1:언어": "요구한 언어로 답하지 않았다",
    "G1:길이": "분량 요구를 지키지 않았다",
    "G1:포맷": "요구한 형식으로 내지 않았다",
    "G1:어조": "말투 · 어조 · 용어 요구를 지키지 않았다",
    "G2:조건": "앞 질문에서 정한 조건을 어겼다",
    "G2:약속": "앞 답변이 약속한 것을 지키지 않았다",
    "G2:memory": "memory 의 사용자 정보를 반영하지 않았거나 어긋난다",
    "G2:모순": "앞 답변과 다른 사실을 말한다",
    "G5:안씀": "근거에 답이 있는데 쓰지 않았다",
    "G5:어긋남": "근거와 어긋나는 주장을 했다",
    "G5:지어낸인용": "답변이 인용부호로 제시한 문장이 근거에 없다",
    "G5:과거근거": "답은 history_input 으로 넘어온 과거 문서에만 있었다",
    "G6:계산": "등식 · 날짜 계산이 틀렸다",
    "G6:코드": "코드 문법이 깨졌다",
    "G6:일반": "일반 지식 질문의 불만 — 코드로 확인할 수 없다",
    "T:인자불일치": "질문의 고유명사가 도구 인자에 없다",
    "T:순서": "도구 호출 순서가 의존 관계와 어긋난다",
    "D:출처미상": "검색 도구 이름 목록이 없어 D1 과 T2 를 가르지 못했다",
    "복합질문": "질문이 복합이다",
    "미검증주장": "일반 지식 주장이 있어 근거와 대조하지 못했다",
    "2차불일치": "충족도 2차 검증이 1차와 어긋났다",
}

# 증거 등급 → 신뢰도. 등급의 뜻은 설계 문서.
GRADE_CONFIDENCE = {4: "high", 3: "high", 2: "medium", 1: "low", 0: "low"}


def confidence_of(grade: int) -> str:
    return GRADE_CONFIDENCE.get(grade, "low")


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------

def get(label_id: str) -> Optional[Label]:
    return LABELS.get(label_id)


def is_failure(label_id: str) -> bool:
    l = LABELS.get(label_id)
    return l is not None and l.kind == "failure"


def sort_key(label_id: str) -> tuple[int, int, int, str]:
    """묶음 순서(ORDER 의 묶음 등장 순) → 번호. taxonomy 밖은 뒤로."""
    group_rank = {g: i for i, g in enumerate("NUCTDGSI")}
    l = LABELS.get(label_id)
    if l is not None:
        return (0, group_rank.get(l.group_id, 50), int(label_id[1:]), "")
    return (1, 99, 0, label_id)


def ordered(label_ids) -> list[str]:
    return sorted(label_ids, key=sort_key)


def label(label_id: str) -> str:
    """`G5 · 근거 활용 실패`."""
    l = LABELS.get(label_id)
    if l is not None:
        return f"{label_id} · {l.name}"
    if label_id == UNCLASSIFIED:
        return "unclassified · 분류 실패"
    return label_id


def desc(label_id: str) -> str:
    l = LABELS.get(label_id)
    if l is not None:
        return l.desc
    if label_id == UNCLASSIFIED:
        return "어느 라벨에도 확신이 없다. '문제 없음'이 아니라 수동 검토 대상이다."
    return TAGS.get(label_id, "")


def tooltip(label_id: str) -> str:
    name = label(label_id)
    detail = desc(label_id)
    return f"{name}\n\n{detail}" if detail else name


def describe(label_id: str) -> dict:
    """출력에 실을 메타데이터. 키 이름은 옛 결과 파일과 같다 (case_id · type_id …)."""
    l = LABELS.get(label_id)
    if l is None:
        return {
            "case_id": label_id,
            "case_name": "분류 실패 (수동 검토 대상)" if label_id == UNCLASSIFIED
                         else TAGS.get(label_id, label_id),
            "type_id": "", "type_name": "", "category": "", "owner": "", "kind": "",
        }
    return {
        "case_id": l.label_id,
        "case_name": l.name,
        "type_id": l.group_id,
        "type_name": l.group.name,
        "category": l.group.word,
        "owner": l.group.owner,
        "kind": l.kind,
    }


# ---------------------------------------------------------------------------
# v2 (case0~30) → v3. 옛 결과 파일을 읽을 때만 쓴다.
# ---------------------------------------------------------------------------

V2_TO_V3: dict[str, Optional[str]] = {
    "case0": "N0",
    "case1": None, "case4": None,          # → U3 태그
    "case2": "U1",
    "case3": None,                         # → 복합질문 태그
    "case5": None, "case7": None, "case8": None, "case19": None, "case23": None,   # 제외
    "case6": "U2",
    "case9": "I1", "case30": "I2",
    "case10": "G1", "case11": "G1", "case12": "G1", "case16": "G1",
    "case13": "G3", "case17": "G3",
    "case14": "G2",
    "case15": "G4",
    "case18": "G5", "case22": "G5", "case24": "G5",
    "case20": "D1",
    "case21": "T1",
    "case25": "G6", "case26": "G6", "case27": "G6",
    "case28": "S1", "case29": "S2",
}

# v2 에 자리가 없던 라벨. 2026-10 로그의 history_input · tool_calls 가 있어야 보인다.
# V2_TO_V3 의 목적지가 아닌 라벨은 전부 여기 있어야 한다 (tests/test_spec_compliance.py).
NEW_IN_V3: set[str] = {"C1", "C2", "T2", "T3", "S3"}

V2_TAG: dict[str, str] = {
    "case1": "U3", "case4": "U3", "case3": "복합질문",
    "case10": "G1:언어", "case11": "G1:길이", "case12": "G1:포맷", "case16": "G1:어조",
    "case14": "G2:조건", "case18": "G5:어긋남", "case22": "G5:안씀", "case24": "G5:지어낸인용",
    "case26": "G6:계산", "case27": "G6:코드", "case25": "G6:일반",
}


def from_v2(case_id: str) -> tuple[Optional[str], Optional[str]]:
    """옛 case 번호 → (v3 라벨, 태그). 제외된 것은 (None, None), 태그로만 남는 것은 (None, 태그)."""
    if case_id in LABELS:
        return case_id, None
    return V2_TO_V3.get(case_id), V2_TAG.get(case_id)


def migrate(case_id: str) -> Optional[str]:
    """옛 호출부용. 라벨만."""
    return from_v2(case_id)[0]
