"""실무 전달본이 약속한 모양을 지키는지 (v4).

약속 다섯 — 실무가 **잘못 읽으면 엉뚱한 곳을 고치게 되는** 것들이라 조용히 깨지면 안 된다.

  - 묶음은 고치는 사람 단위이고 건수 많은 순. 정상은 빼고, 검토는 맨 뒤에 따로
  - 사례마다 왜 그 묶음인지(사유) 와 어떤 길로 왔는지(지나온 단계) 가 말로 적힌다
  - 확률 숫자(p) 는 싣지 않는다
  - 플래그는 정상 · 검토를 포함한 전부에서 센다
  - 본문이 없는 결과 파일(--no-text)도 받는다 — 사례의 말 칸이 비는 것으로
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ragdiag.features import handover

ROOT = Path(__file__).resolve().parents[1]


def turn(bucket, *, stopped_at="근거 판정", because="근거 어디에도 질문의 답이 없었다", where=(),
         sure=True, flags=None, text=True, steps=None, chat="C-1", no=3):
    t = {
        "chat_id": chat, "turn": no, "event_time": f"t{no}", "target_turn": no - 1, "target_event_time": f"t{no - 1}",
        "verdict": {"bucket": bucket, "sure": sure, "stopped_at": stopped_at, "because": because,
                    "where": list(where)},
        "steps": steps if steps is not None else [
            {"step": "코드 확정", "rules": {"자원 부족 문구": "아니오", "빈 답변": "아니오", "붕괴": "아니오"}},
            {"step": "불만 판정", "answers": {"후속 발화가 답변을 문제 삼는다": {"answer": "예", "p": 0.97},
                                            "정책·권한 거절이고 그걸 불평한다": {"answer": "아니오", "p": 0.95}}},
            {"step": "근거 판정", "answers": {"이번 턴 검색 청크에 답이 있다": {"answer": "아니오", "p": 0.92},
                                            "이번 턴 도구 결과에 답이 있다": "비어 있어 묻지 않음",
                                            "근거 전체에 답이 있다": {"answer": "없음", "p": 0.94}}},
        ],
        "flags": flags or {"앞 턴 누락": False, "history 재구성 턴 수": 0, "질문에 개인정보": False},
        "axes": {"부서": "해외영업팀", "직급": "책임", "직무": "영업", "answered_by": "rag", "ask_on": "web", "fallback": ""},
    }
    if text:
        t["text"] = {"question": "해외 출장 숙박비 상한은?", "answer": "규정을 확인해 보시기 바랍니다.",
                     "followup": "금액을 물었는데요", "history": [],
                     "이번 턴 검색 청크": ["[출장규정 제3조] 국내 출장 식비는 1일 3만원을 상한으로 한다."],
                     "이번 턴 도구 결과": [], "앞 턴 근거": [], "메모리": []}
    return t


def result(*turns):
    return {"run": {"started": "2026-10-29T10:00:00", "kev": "kev-latest"},
            "summary": {}, "turns": list(turns)}


def test_groups_are_owner_first_and_ordered_by_count():
    out = handover.build(result(turn("근거"), turn("근거", no=5), turn("생성", stopped_at="근거 판정",
                                                                 because="근거에 답이 전부 있었는데 답변이 살리지 못했다")))
    assert [g["묶음"] for g in out["분류"]] == ["근거", "생성"]
    assert out["분류"][0]["고칠_곳"] == "검색기 · 도구 연동 · 문서" and out["분류"][0]["건수"] == 2
    assert out["분류"][0]["들어온_길"] == {"근거 어디에도 질문의 답이 없었다": 2}


def test_normal_is_left_out_but_counted_and_review_goes_last():
    out = handover.build(result(
        turn("정상", stopped_at="불만 판정", because="후속 발화가 앞 답변을 문제 삼지 않는다 — 필터가 넓게 잡은 턴"),
        turn("검토", sure=False, stopped_at="불만 판정 · 정책·권한 거절이고 그걸 불평한다",
             because="정책·권한 거절이고 그걸 불평한다 — 확신이 없다 (p 0.55)"),
        turn("근거")))
    assert out["대상"] == {"로그": "", "분석한 턴": 3, "실패로 판정": 1, "정상으로 판정": 1, "검토": 1, "오류": 0}
    assert [g["묶음"] for g in out["분류"]] == ["근거"]
    assert list(out)[-1] == "검토"
    assert out["검토"]["건수"] == 1
    assert out["검토"]["막힌_문항"] == {"불만 판정 · 정책·권한 거절이고 그걸 불평한다": 1}


def test_an_example_says_why_and_which_way_it_came():
    ex = handover.build(result(turn("근거")))["분류"][0]["사례"][0]
    assert list(ex) == ["질문", "답변", "사용자_반응", "분석"]
    assert ex["질문"] == "해외 출장 숙박비 상한은?"
    assert ex["분석"]["사유"] == "근거 어디에도 질문의 답이 없었다"
    assert ex["분석"]["지나온_단계"] == [
        "코드 확정: 자원 부족 문구 아니오 · 빈 답변 아니오 · 붕괴 아니오",
        "불만 판정: 후속 발화가 답변을 문제 삼는다 예 · 정책·권한 거절이고 그걸 불평한다 아니오",
        "근거 판정: 이번 턴 검색 청크에 답이 있다 아니오 · 이번 턴 도구 결과에 답이 있다 비어 있어 묻지 않음 · 근거 전체에 답이 있다 없음",
    ]
    assert ex["분석"]["meta_data"] == {"대화": "C-1", "턴": 3, "부서": "해외영업팀", "직급": "책임", "직무": "영업"}


def test_where_is_said_when_the_verdict_has_one():
    ex = handover.build(result(turn("생성", because="근거에 답이 전부 있었는데 답변이 살리지 못했다",
                                    where=["이번 턴 검색 청크"])))["분류"][0]["사례"][0]
    assert ex["분석"]["근거_위치"] == ["이번 턴 검색 청크"]
    assert ex["분석"]["근거_구절"] == {"이번 턴 검색 청크": ["[출장규정 제3조] 국내 출장 식비는 1일 3만원을 상한으로 한다."]}


def test_confidence_never_travels():
    out = handover.build(result(turn("근거"), turn("검토", sure=False, because="x — 확신이 없다 (p 0.55)")))
    flat = str(out)
    assert "0.97" not in flat and "0.92" not in flat and "'p'" not in flat
    assert "확신이 없다" in str(out["검토"])            # 문장은 남고 숫자는 사유에서 지운다
    assert "(p 0.55)" not in str(out["검토"]["사례"])


def test_flags_are_counted_over_every_turn():
    out = handover.build(result(
        turn("정상", flags={"앞 턴 누락": True, "history 재구성 턴 수": 3, "질문에 개인정보": False}),
        turn("근거", flags={"앞 턴 누락": False, "history 재구성 턴 수": 0, "질문에 개인정보": True}),
        turn("근거", flags={"앞 턴 누락": "옛 로그 — 판정 안 함", "history 재구성 턴 수": 1, "질문에 개인정보": False})))
    assert out["플래그"] == {"앞 턴 누락": 1, "history 재구성": 2, "질문에 개인정보": 1,
                            "옛 로그 (앞 턴 누락 판정 안 함)": 1}


def test_no_text_result_is_accepted():
    ex = handover.build(result(turn("근거", text=False)))["분류"][0]["사례"][0]
    assert ex["질문"] == ex["답변"] == ex["사용자_반응"] == "(본문 없음 — --no-text)"


def test_errors_are_counted_not_listed():
    bad = {"chat_id": "C-9", "turn": 2, "event_time": "t", "target_turn": 1, "target_event_time": "t",
           "error": "[complaint] JudgeError: x"}
    out = handover.build(result(turn("근거"), bad))
    assert out["대상"]["오류"] == 1 and out["대상"]["분석한 턴"] == 1


def test_entry_point_refuses_a_file_without_turns(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text('{"analysis_results": []}', encoding="utf-8")
    proc = subprocess.run([sys.executable, str(ROOT / "src" / "handover.py"), str(bad)],
                          capture_output=True, text=True)
    assert proc.returncode == 2 and "turns" in proc.stderr


def test_entry_points_are_exactly_the_four_scripts():
    scripts = sorted(p.name for p in (ROOT / "src").glob("*.py"))
    assert scripts == ["assemble.py", "dashboard.py", "handover.py", "run.py"]


def test_missing_prior_turns_put_a_caution_in_the_head():
    out = handover.build(result(
        turn("근거", flags={"앞 턴 누락": True, "history 재구성 턴 수": 3, "질문에 개인정보": False}),
        turn("사용자", because="후속 발화가 감정 표출뿐이라 무엇이 틀렸는지 단서가 없다")))
    assert "주의" in out and "사용자" in out["주의"][0] and "앞 턴 누락" in out["주의"][0]
    assert list(out).index("주의") < list(out).index("분류"), "머리에 적는다"
    assert "주의" not in handover.build(result(turn("근거")))
