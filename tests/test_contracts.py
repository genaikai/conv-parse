"""입력 계약 대조 — 실행 환경의 로그 모양이 파서와 어긋날 때 무엇을 알려주는가."""

import json
from pathlib import Path

from ragdiag.contracts import check_log, shape
from ragdiag.fixtures.synth import generate

ROOT = Path(__file__).resolve().parents[1]


def _flattened(payload: dict) -> dict:
    """users → conversations → turns 를 users → turns 로 편다 (pseudo_input 의 모양)."""
    out = {"users": []}
    for user in payload["users"]:
        turns = []
        for conv in user["conversations"]:
            for turn in conv["turns"]:
                t = dict(turn, conversation_id=conv["conversation_id"])
                t["llm_eval_alternatives"] = t.pop("llm_alternatives", [])
                turns.append(t)
        out["users"].append({**{k: v for k, v in user.items() if k != "conversations"},
                             "turns": turns})
    return out


def test_two_level_log_is_reported_as_a_structure_mismatch():
    """실제로 겪었다 - pseudo_input 이 0건으로 읽혔는데 계약 검사는 사용자 키 셋만 잡았다.

    conversation · turn 층이 빈 목록이라 아무 줄도 안 뜨고, 화면에는 "필터 조건을
    확인하라" 만 남았다. 구조가 다르면 그렇다고 말해야 한다.
    """
    report = check_log(_flattened(generate(seed=0)))
    structural = [m for m in report.mismatches if m.field == "conversations"]
    assert structural, [m.line() for m in report.mismatches]
    assert structural[0].detail.startswith("turns 가 user 바로 아래라 파서가 0건으로 읽는다"), (
        "RUN SUMMARY 는 80칸에서 잘린다 - 할 일이 앞에 와야 한다")


def test_an_alias_key_is_named_next_to_the_missing_one():
    """llm_alternatives 가 없고 llm_eval_alternatives 가 있으면 같은 필드라고 알려준다.

    "없다" 와 "계약에 없는 키" 두 줄로 따로 뜨면 사람은 둘이 같은 것인 줄 모른다.
    """
    report = check_log(_flattened(generate(seed=0)))
    missing = [m for m in report.mismatches if m.field == "llm_alternatives"]
    assert missing and "llm_eval_alternatives" in missing[0].detail
    assert not [m for m in report.mismatches if m.field == "llm_eval_alternatives"], (
        "별칭은 '계약에 없는 키' 로 따로 세지 않는다")


def test_turn_fields_are_still_checked_in_a_two_level_log():
    """구조가 다르다고 턴 대조를 건너뛰면 구조를 고친 뒤에야 나머지 어긋남을 본다."""
    payload = _flattened(generate(seed=0))
    for user in payload["users"]:
        for turn in user["turns"]:
            turn["llm_eval_score"] = "문자열"
    report = check_log(payload)
    assert any(m.field == "llm_eval_score" and m.kind == "dtype" for m in report.mismatches)


def test_the_bundled_pseudo_log_is_caught():
    """저장소 옆의 pseudo_input 이 있으면 그 파일로 실제로 잡히는지 본다."""
    path = ROOT / "pseudo_input" / "conv-data.json"
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    report = check_log(payload)
    fields = {m.field for m in report.mismatches}
    assert {"conversations", "llm_alternatives"} <= fields, sorted(fields)
    assert shape(payload).endswith("0 conversations / 0 turns")
