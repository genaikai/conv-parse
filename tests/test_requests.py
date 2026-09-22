"""요구 확인기(`ragdiag.requests`)를 고정한다.

**우리 골든셋만으로 재지 않는다.** 이 모듈은 정규식이고, 우리가 쓴 145건에는 양성
표본이 형식 10 · 언어 3 · 길이 3 뿐이다. 그 표현을 보고 쓴 정규식이 그 셋에서 100%
를 내는 것은 아무것도 증명하지 않는다 - 같은 사람이 문제를 내고 푸는 셈이다.

실제로 그랬다. 처음에 "요구를 알아맞히는" 탐지기를 만들어 우리 셋에서 16/16 을
받았는데, 외부 데이터에 돌리니 형식 정밀도 64% · 언어 재현율 0% 였다.

그래서 외부 데이터셋을 함께 쓴다. `allganize/IFEval-Ko` 342건은 한국어 지시문에
`instruction_id_list` 라벨이 붙어 있고 우리가 표현을 손댄 적이 없다. 내려받은
사본을 `tests/data/` 에 두고, 없으면 그 테스트만 건너뛴다(에어갭에서도 나머지는 돈다).

두 셋이 서로 다른 구멍을 잡는다는 것도 실측으로 확인됐다. IFEval-Ko 는 번역체라
언어 이름이 길어서("구자라티어") 짧은 이름의 결함을 못 잡았고, 우리 셋의
"영어로 짧게 답해 주세요" 가 그걸 잡았다. 반대로 띄어쓰기 · 조사 경계 문제는
외부 셋에서만 드러났다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ragdiag.requests import (
    format_is_supported,
    language_was_requested,
    length_was_requested,
)

IFEVAL = Path(__file__).parent / "data" / "ifeval_ko.json"
HELDOUT = Path(__file__).parent / "data" / "ifeval_ko_heldout.json"
SNU = Path(__file__).parent / "data" / "ifeval_ko_snu.json"
FORMAT_KINDS = ("table", "numbered_list", "bullet_list", "json", "code_block", "prose")


# ---------------------------------------------------------------------------
# 손으로 고른 경계 — 실측에서 실제로 틀렸던 것들이다
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind,question", [
    ("table", "출장비 항목별 상한을 표로 정리해 주세요"),
    ("table", "출장비항목별상한을표로정리해주세요"),        # 띄어쓰기 없는 실제 로그
    ("table", "비교해서 표 형식으로 주세요"),
    ("table", "결과를 테이블로 보여줘"),
    ("numbered_list", "계정 잠김 풀기 순서 번호 매겨서 알려줘"),
    ("bullet_list", "정확히 3개의 글머리로 정리해줘"),
    ("bullet_list", "목록 형식으로 알려주세요"),
    ("json", "전체 출력을 JSON 형식으로 감싸세요"),
    ("code_block", "코드 블록으로 감싸서 주세요"),
    ("prose", "표 말고 줄글로 설명해 주세요"),
])
def test_a_stated_format_is_confirmed(kind, question):
    assert format_is_supported(kind, [question]), question


@pytest.mark.parametrize("question", [
    "큰따옴표로 감싸주세요",          # 따옴표의 꼬리
    "별표로 구분하세요",              # 별표
    "이번 분기 목표를 알려줘",         # 목표
    "임원 급여 테이블을 보여주세요",    # 자료 요청이지 형식 요구가 아니다
    "엑셀에서 피벗 테이블 만드는 방법",  # 도구 사용법
    "다음 런던행 기차 시간표를 알려줘",  # 시간표
])
def test_a_word_that_merely_ends_in_table_is_not_a_format_request(question):
    """"표" 는 다른 낱말의 꼬리이기도 하다. 전부 case12 오탐으로 이어졌다."""
    assert not format_is_supported("table", [question]), question


@pytest.mark.parametrize("question,want", [
    ("영어로 짧게 답해 주세요", True),         # 한 글자 언어명 - {2,10} 으로 막혀 떨어졌던 것
    ("일본어로 답해줘", True),
    ("한국어로 번역해 주세요", True),
    ("전적으로 스와힐리어로 작성하세요", True),
    ("Please answer in English", True),
    ("日本語で答えてください", True),
    ("영문으로 작성해 주세요", True),           # 문(文) 꼴 - 번역본마다 어/문이 갈린다
    ("영문으로 400자 이상의 블로그 글을 쓰세요", True),   # 쓰임 동사가 멀리 떨어진 꼴
    ("연차 규정을 단어로 설명해 주세요", False),   # 어(語)로 끝나는 보통명사
    ("전문 용어로 알려주세요", False),
    ("국어 교육 과정 알려줘", False),
    ("출장비 상한 알려주세요", False),
    ("논문으로 정리해줘", False),               # 문(文)으로 끝나는 보통명사
    ("주문으로 처리해주세요", False),
    ("질문으로 바꿔줘", False),
    ("설문으로 만들어줘", False),
])
def test_language_requests_are_told_apart_from_nouns_ending_in_eo(question, want):
    assert language_was_requested([question]) is want, question


@pytest.mark.parametrize("question,want", [
    ("세 줄 이내로 알려주세요", True),
    ("VPN 접속 방법 세줄로 요약해줘", True),
    ("500자 이내로 써주세요", True),
    ("최소 800단어를 사용해야 한다", True),
    ("정확히 3개의 단락으로 작성하세요", True),
    ("짧게 답해주세요", True),
    ("별명을 지어 줄 수 있나요", False),          # "줄 수"
    ("12개의 자리 표시자를 포함하세요", False),     # "개의 자"
    ("일하기 위한 자기소개서를 작성하세요", False),   # "한 자"
    ("두 사람의 줄거리를 써주세요", False),         # "줄거리"
    ("자세히 설명해 주세요", False),               # 상세함이지 분량이 아니다
    ("출장비 상한 알려주세요", False),
])
def test_length_requests_survive_korean_word_boundaries(question, want):
    assert length_was_requested([question]) is want, question


def test_only_the_prior_questions_count():
    """후속 발화에서 처음 나온 요구는 비판받은 답변이 따를 수 없었던 것이다."""
    assert not format_is_supported("table", ["연차 이월 규정 알려줘"])
    assert format_is_supported("table", ["연차 이월 규정 알려줘", "표로 정리해줘"])


# ---------------------------------------------------------------------------
# 외부 데이터셋 — 우리가 표현을 손댄 적이 없는 342건
# ---------------------------------------------------------------------------

FORMAT_LABELS = {"detectable_format:json_format": "json",
                 "detectable_format:number_bullet_lists": "bullet_list"}
LANGUAGE_LABEL = "language:response_language"
LENGTH_LABELS = {"length_constraints:number_sentences",
                 "length_constraints:number_words",
                 "length_constraints:number_paragraphs",
                 "length_constraints:nth_paragraph_first_word",
                 # SNU 판이 쓰는 한국어용 라벨. 글자 수를 센다.
                 "length_constraints:number_letters",
                 "length_constraints:number_letter_excluded"}


@pytest.fixture(scope="module")
def ifeval():
    if not IFEVAL.exists():
        pytest.skip(f"{IFEVAL} 가 없다 (scripts 로 내려받는다)")
    return json.loads(IFEVAL.read_text(encoding="utf-8"))


@pytest.mark.parametrize("label,kind,floor", [
    ("detectable_format:json_format", "json", 1.0),
    ("detectable_format:number_bullet_lists", "bullet_list", 0.95),
])
def test_stated_formats_are_confirmed_on_outside_data(ifeval, label, kind, floor):
    rows = [r for r in ifeval if label in r["instruction_id_list"]]
    ok = sum(format_is_supported(kind, [r["prompt"]]) for r in rows)
    assert ok / len(rows) >= floor, f"{kind} {ok}/{len(rows)}"


@pytest.mark.parametrize("kind,ceiling", [
    ("table", 0.02), ("numbered_list", 0.02), ("json", 0.02),
    ("bullet_list", 0.03), ("prose", 0.02), ("code_block", 0.03),
])
def test_formats_are_not_claimed_where_they_were_not_asked(ifeval, kind, ceiling):
    """확인기는 판정자의 주장을 받아 준다. 아무 글에나 통과하면 그 확인이 무의미하다.

    그 형식의 라벨이 붙은 행은 뺀다 - 거기서 통과하는 것은 맞는 일이다.
    IFEval-Ko 에 표 · 번호 · 줄글 라벨은 아예 없어서 342건 전부가 대상이 된다.
    통과한 소수는 사람이 읽어 실제 요구가 맞음을 확인했다 - 그래서 상한을 0 이
    아니라 2~3% 로 둔다.
    """
    label = next((k for k, v in FORMAT_LABELS.items() if v == kind), None)
    rows = [r for r in ifeval if label not in r["instruction_id_list"]]
    hit = sum(format_is_supported(kind, [r["prompt"]]) for r in rows)
    assert hit / len(rows) <= ceiling, f"{kind} {hit}/{len(rows)}"


def test_language_requests_are_found_on_outside_data(ifeval):
    pos = [r for r in ifeval if LANGUAGE_LABEL in r["instruction_id_list"]]
    neg = [r for r in ifeval if LANGUAGE_LABEL not in r["instruction_id_list"]]
    assert sum(language_was_requested([r["prompt"]]) for r in pos) / len(pos) >= 0.95
    assert sum(language_was_requested([r["prompt"]]) for r in neg) / len(neg) <= 0.02


def test_length_requests_are_found_on_outside_data(ifeval):
    """재현율 하한이 형식 · 언어보다 낮다.

    IFEval 의 길이 라벨 절반이 단락 · 섹션 수인데, 그건 우리 taxonomy 의 분량
    (자 · 문장 · 줄)과 층이 다르다. 못 잡는 것이 우리 판정에서는 손해가 아니다.
    """
    pos = [r for r in ifeval if set(r["instruction_id_list"]) & LENGTH_LABELS]
    neg = [r for r in ifeval if not (set(r["instruction_id_list"]) & LENGTH_LABELS)]
    assert sum(length_was_requested([r["prompt"]]) for r in pos) / len(pos) >= 0.85
    assert sum(length_was_requested([r["prompt"]]) for r in neg) / len(neg) <= 0.03


# ---------------------------------------------------------------------------
# 홀드아웃 테스트셋 — 패턴을 고칠 때 **보지 않은** 셋
# ---------------------------------------------------------------------------
#
# 위의 IFEval-Ko 는 검증셋(dev)이다. 그걸 보면서 정규식을 고쳤으므로 거기서 나온
# 수치는 낙관적이다. 일반화가 됐는지 말하려면 한 번도 안 본 셋이 있어야 한다 -
# 기계학습에서 검증셋과 테스트셋을 가르는 것과 같은 이유다.
#
#   dev   allganize/IFEval-Ko                        342건 (언어 라벨 25)
#   dev   danish-foundation-models/multi-ifeval `ko`  524건 (언어 라벨 0)
#   test  thunder-research-group/SNU_Ko-IFEval 의 **홀수 key 절반** 449건 (언어 라벨 67)
#
# 셋 다 같은 IFEval 원문을 다른 팀이 따로 번역한 것이다. 한국어 표현이 독립이라
# 우리 정규식이 특정 번역체에 맞춰진 것인지가 드러난다 - 실제로 드러났다:
# "영어로" 만 알던 규칙이 "영문으로" 를 쓰는 번역본에서 재현율 37% 였다.
#
# SNU 를 key 홀짝으로 갈랐다. 짝수(A)는 그 결함을 진단하는 데 썼으므로 검증셋이고,
# 홀수(B)만 테스트셋으로 남는다. **B 를 보고 패턴을 고치지 말 것.**
#
# multi-ifeval `ko` 는 언어 라벨이 0건이라 언어를 아예 못 잰다. 거기서 보이던
# "오탐 10%" 는 전부 라벨 누락이었다 - 라벨이 없는 셋으로 정밀도를 재면 안 된다.
#
# **이 셋을 보고 패턴을 고치지 말 것.** 고치는 순간 검증셋이 되고 남는 테스트셋이
# 없어진다. 아래 기준값은 2026-09-22 에 **한 번 재서** 적은 것이고, 회귀를 잡으려고
# 두는 것이지 목표가 아니다. 패턴을 바꿔 이 수치를 올리려 들면 이 파일의 뜻이 사라진다.
# 새 기능을 넣어 여기가 나빠지면, 기준값을 낮추지 말고 기능을 고쳐라.

@pytest.fixture(scope="module")
def heldout():
    """SNU_Ko-IFEval 의 홀수 key 절반. 패턴을 고칠 때 보지 않은 쪽이다."""
    if not SNU.exists():
        pytest.skip(f"{SNU} 가 없다 (scripts/fetch-eval-data.sh 로 내려받는다)")
    rows = json.loads(SNU.read_text(encoding="utf-8"))
    return [r for r in rows if int(r["key"]) % 2 == 1]


@pytest.fixture(scope="module")
def multi_ifeval():
    """번역본이 또 다르다. 형식 · 길이만 본다 - 언어 라벨이 0건이라 언어는 못 잰다."""
    if not HELDOUT.exists():
        pytest.skip(f"{HELDOUT} 가 없다")
    return json.loads(HELDOUT.read_text(encoding="utf-8"))


@pytest.mark.parametrize("label,kind,floor", [
    ("detectable_format:json_format", "json", 1.0),
    ("detectable_format:number_bullet_lists", "bullet_list", 0.95),
])
def test_formats_generalize_to_an_unseen_translation(heldout, label, kind, floor):
    """2026-09-22 실측 (SNU B 449건): json 16/16 · 불릿 26/26."""
    rows = [r for r in heldout if label in r["instruction_id_list"]]
    ok = sum(format_is_supported(kind, [r["prompt"]]) for r in rows)
    assert ok / len(rows) >= floor, f"{kind} {ok}/{len(rows)}"


@pytest.mark.parametrize("kind,ceiling", [
    ("table", 0.02), ("numbered_list", 0.02), ("bullet_list", 0.03),
    ("json", 0.02), ("code_block", 0.04), ("prose", 0.04),
])
def test_formats_stay_quiet_on_an_unseen_translation(heldout, kind, ceiling):
    """2026-09-22 실측 (SNU B): json 0% · 불릿 1.4% · 나머지 2~3%."""
    label = next((k for k, v in FORMAT_LABELS.items() if v == kind), None)
    rows = [r for r in heldout if label not in r["instruction_id_list"]]
    hit = sum(format_is_supported(kind, [r["prompt"]]) for r in rows)
    assert hit / len(rows) <= ceiling, f"{kind} {hit}/{len(rows)}"


def test_language_generalizes_to_an_unseen_translation(heldout):
    """2026-09-22 실측 (SNU B): 54/67 (81%).

    고치기 전에는 37% 였다. 이 번역본은 "영어" 가 아니라 "영문" 을 쓰는데 규칙이
    어(語) 꼴만 알고 있었다. 검증셋(allganize)에서는 100% 라 드러나지 않던 결함이다.

    오탐 하한을 8% 로 둔 것은 이 셋의 라벨 누락 때문이다 - 통과한 것들을 읽어 보면
    "영문으로 작성해야" 처럼 진짜 언어 요구인데 instruction_id_list 에 없다.
    """
    pos = [r for r in heldout if LANGUAGE_LABEL in r["instruction_id_list"]]
    neg = [r for r in heldout if LANGUAGE_LABEL not in r["instruction_id_list"]]
    assert sum(language_was_requested([r["prompt"]]) for r in pos) / len(pos) >= 0.75
    assert sum(language_was_requested([r["prompt"]]) for r in neg) / len(neg) <= 0.08


def test_length_generalizes_to_an_unseen_translation(heldout):
    """2026-09-22 실측 (SNU B): 재현율 81/97 (84%) · 오탐 33/352 (9.4%).

    번역체가 달라지면 분량 어휘의 경계가 흔들린다 - 알려진 약점이다. 오탐 쪽은
    라벨 누락도 섞여 있다(길이 라벨을 안 단 "200단어 에세이" 류).
    """
    pos = [r for r in heldout if set(r["instruction_id_list"]) & LENGTH_LABELS]
    neg = [r for r in heldout if not (set(r["instruction_id_list"]) & LENGTH_LABELS)]
    assert sum(length_was_requested([r["prompt"]]) for r in pos) / len(pos) >= 0.78
    assert sum(length_was_requested([r["prompt"]]) for r in neg) / len(neg) <= 0.12


def test_formats_hold_on_a_third_translation(multi_ifeval):
    """셋째 번역본에서도 형식이 버티는지. 2026-09-22 실측: json 17/17 · 불릿 29/31."""
    for label, kind, floor in (("detectable_format:json_format", "json", 1.0),
                               ("detectable_format:number_bullet_lists", "bullet_list", 0.90)):
        rows = [r for r in multi_ifeval if label in r["instruction_id_list"]]
        ok = sum(format_is_supported(kind, [r["prompt"]]) for r in rows)
        assert ok / len(rows) >= floor, f"{kind} {ok}/{len(rows)}"
