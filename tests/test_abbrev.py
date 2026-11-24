"""④ 입력 축약 — kev 가 500 을 냈을 때만 칸별 상한으로 줄여 한 번 더 묻는다 (docs/abbrev.md)."""

from __future__ import annotations

import json

import pytest

from ragdiag import abbrev, questions, settings
from ragdiag.backends import JudgeError, Usage
from ragdiag.decide import KevHTTPError, ScriptedBackend
from ragdiag.judge import Judge

Q = {"illegible": questions.COMPLAINT["illegible"]}
CPT = settings.ABBREV_CHARS_PER_TOKEN


def chars(tokens: int) -> int:
    return int(tokens * CPT)


def long_text(tokens: int, seed: str = "가") -> str:
    return (seed * 10 + " ") * (chars(tokens) // 11 + 1)


def state(**kw) -> dict:
    base = {"history": [], "question": "연차 이월 되나요", "answer": "됩니다", "followup": "아니잖아요"}
    base.update(kw)
    return base


class _LLM:
    """abbrev 의 두 요약 프롬프트에 각본대로 답한다."""

    model = "llm-scripted"

    def __init__(self, question=None, history=None):
        self.question, self.history, self.calls = question, history, []

    def complete(self, system, user, out_model, hint=""):
        self.calls.append(user)
        fields = out_model.model_fields
        if "instruction" in fields:
            return out_model(**self.question), Usage(1, 1)
        return out_model(**self.history), Usage(1, 1)


def judge_with(llm=None) -> Judge:
    return Judge(backend=llm, cache_dir=None, decision=ScriptedBackend())


# -- 토큰 추정 ----------------------------------------------------------------

def test_tokens_follow_chars_per_token(monkeypatch):
    monkeypatch.setattr(settings, "ABBREV_CHARS_PER_TOKEN", 2.0)
    assert abbrev.tokens("가" * 100) == 50
    assert abbrev.tokens([{"role": "user", "content": "가" * 100}]) > 50, "목록은 JSON 길이로 잰다"


# -- answer · followup: 머리 · 꼬리 -----------------------------------------------

def test_answer_over_cap_is_elided_head_and_tail_without_llm():
    text = "머리" * chars(3000) + "꼬리" * chars(3000)
    small, notes, used, calls = abbrev.abbreviate("complaint", state(answer=text), judge_with())
    assert abbrev.tokens(small["answer"]) <= settings.ABBREV_ANSWER_TOKENS
    assert small["answer"].startswith("머리") and small["answer"].endswith("꼬리")
    assert "(중략" in small["answer"]
    assert notes == [{"field": "answer", "method": "elide", "before": len(text), "after": len(small["answer"])}]
    assert calls == 0


def test_followup_is_only_elided_as_a_safety_net():
    text = long_text(4000)
    small, notes, _, _ = abbrev.abbreviate("complaint", state(followup=text), judge_with())
    assert abbrev.tokens(small["followup"]) <= settings.ABBREV_FOLLOWUP_TOKENS
    assert [n["method"] for n in notes] == ["elide"]


def test_fields_under_cap_are_untouched():
    s = state()
    small, notes, used, calls = abbrev.abbreviate("complaint", s, judge_with())
    assert small == s and notes == [] and calls == 0


def test_other_stages_have_no_recipe_yet():
    assert abbrev.abbreviate("evidence", {"question": long_text(9000)}, judge_with()) is None


# -- history ---------------------------------------------------------------------

def history_of(n_pairs: int, user_tokens: int, assistant_tokens: int) -> list[dict]:
    out = []
    for i in range(n_pairs):
        out.append({"role": "user", "content": f"질문{i} " + long_text(user_tokens, "문")})
        out.append({"role": "assistant", "content": f"답{i} " + long_text(assistant_tokens, "답")})
    return out


def test_history_folds_assistant_turns_first_and_keeps_user_turns_verbatim():
    h = history_of(3, user_tokens=100, assistant_tokens=2000)
    small, notes, _, calls = abbrev.abbreviate("complaint", state(history=h), judge_with())
    assert abbrev.tokens(small["history"]) <= settings.ABBREV_HISTORY_TOKENS
    assert [m["content"] for m in small["history"] if m["role"] == "user"] == \
        [m["content"] for m in h if m["role"] == "user"]
    for m in small["history"]:
        if m["role"] == "assistant":
            assert "(답변 생략" in m["content"] and m["content"].startswith("답")
    assert notes == [{"field": "history", "method": "fold", "before": len(json.dumps(h, ensure_ascii=False)),
                      "after": len(json.dumps(small["history"], ensure_ascii=False))}]
    assert calls == 0, "접기만으로 풀리면 LLM 을 부르지 않는다"


def test_history_summarises_older_user_turns_with_the_llm_and_keeps_the_last_two():
    h = history_of(4, user_tokens=400, assistant_tokens=10)
    llm = _LLM(history={"requests": ["질문0 문문문 이월 한도를 물었다", "질문1 문문문 이 틀렸다고 했다"]})
    small, notes, used, calls = abbrev.abbreviate("complaint", state(history=h), judge_with(llm))
    users = [m for m in small["history"] if m["role"] == "user"]
    assert users[0]["content"].startswith("(앞 대화 요약)")
    assert [u["content"] for u in users[1:]] == [h[4]["content"], h[6]["content"]], "마지막 user 둘은 원문"
    assert [n["method"] for n in notes] == ["summarize"]
    assert calls == 1 and used.input_tokens == 1
    assert "질문0" in llm.calls[0] and h[4]["content"] not in llm.calls[0], "요약 대상은 앞의 것들만"


def test_history_summary_that_shares_no_words_with_the_original_is_rejected():
    h = history_of(4, user_tokens=400, assistant_tokens=10)
    llm = _LLM(history={"requests": ["전혀 다른 내용을 지어냈다"]})
    small, notes, _, calls = abbrev.abbreviate("complaint", state(history=h), judge_with(llm))
    assert [n["method"] for n in notes] == ["drop"]
    assert calls == 1
    users = [m["content"] for m in small["history"] if m["role"] == "user"]
    assert users[-2:] == [h[4]["content"], h[6]["content"]]
    assert abbrev.tokens(small["history"]) <= settings.ABBREV_HISTORY_TOKENS


def test_history_without_llm_drops_from_the_front():
    h = history_of(4, user_tokens=450, assistant_tokens=10)
    small, notes, _, calls = abbrev.abbreviate("complaint", state(history=h), judge_with())
    assert calls == 0 and [n["method"] for n in notes] == ["drop"]
    assert small["history"][-1] == h[-1] and small["history"][-2] == h[-2]
    assert abbrev.tokens(small["history"]) <= settings.ABBREV_HISTORY_TOKENS


def test_history_last_two_user_turns_alone_over_cap_are_elided():
    h = history_of(2, user_tokens=2000, assistant_tokens=10)
    small, notes, _, _ = abbrev.abbreviate("complaint", state(history=h), judge_with())
    assert [n["method"] for n in notes] == ["elide"]
    assert abbrev.tokens(small["history"]) <= settings.ABBREV_HISTORY_TOKENS
    assert all(m["role"] in ("user", "assistant") and "content" in m for m in small["history"])


# -- question --------------------------------------------------------------------

def test_question_is_split_into_verbatim_instruction_and_body_summary():
    body = long_text(3000, "본")
    q = "아래 메일을 세 줄로 요약해줘\n\n" + body
    llm = _LLM(question={"instruction": "아래 메일을 세 줄로 요약해줘", "body_summary": "출장 정산 기한 안내 메일"})
    small, notes, _, calls = abbrev.abbreviate("complaint", state(question=q), judge_with(llm))
    assert small["question"] == "아래 메일을 세 줄로 요약해줘\n\n(첨부 내용 요약) 출장 정산 기한 안내 메일"
    assert [n["method"] for n in notes] == ["split"] and calls == 1


def test_question_split_whose_instruction_is_not_verbatim_falls_back_to_elision():
    q = "아래 메일을 요약해줘\n\n" + long_text(3000, "본")
    llm = _LLM(question={"instruction": "메일 요약 요청", "body_summary": "…"})
    small, notes, _, calls = abbrev.abbreviate("complaint", state(question=q), judge_with(llm))
    assert [n["method"] for n in notes] == ["elide"] and calls == 1
    assert small["question"].startswith("아래 메일을") and abbrev.tokens(small["question"]) <= settings.ABBREV_QUESTION_TOKENS


def test_question_without_llm_is_elided():
    q = long_text(3000)
    small, notes, _, calls = abbrev.abbreviate("complaint", state(question=q), judge_with())
    assert [n["method"] for n in notes] == ["elide"] and calls == 0


# -- Judge: 500 이면 한 번 재시도 ----------------------------------------------------

class _Flaky(ScriptedBackend):
    """처음 n 번은 주어진 KevHTTPError, 그 뒤는 각본대로 답한다."""

    def __init__(self, errors: list[KevHTTPError]):
        super().__init__(lambda s, q: {"illegible": True})
        self.errors = list(errors)

    def decide(self, state, questions):
        if self.errors:
            raise self.errors.pop(0)
        return super().decide(state, questions)


def oom() -> KevHTTPError:
    return KevHTTPError(500, "http://kev", "CUDA out of memory")


def test_judge_retries_the_same_input_once_after_a_single_500():
    """500 은 겹침 OOM 일 수 있다 — 먼저 원문 그대로 한 번 더. 되면 축약 없이 그 답이다."""
    backend = _Flaky([oom()])
    judge = Judge(None, cache_dir=None, decision=backend)
    big = state(answer=long_text(8000))
    answers, _, retry = judge.decide("complaint", big, Q)
    assert answers["illegible"].p == 0.95
    assert retry["abbrev"] == [] and retry["kev_failed"] == 1
    assert [c[0] for c in backend.calls] == [big]        # 재시도도 원문


def test_judge_abbreviates_after_two_500s(tmp_path):
    backend = _Flaky([oom(), oom()])
    judge = Judge(None, cache_dir=tmp_path, decision=backend)
    big = state(answer=long_text(8000))
    answers, used, retry = judge.decide("complaint", big, Q)
    assert answers["illegible"].p == 0.95
    assert [n["field"] for n in retry["abbrev"]] == ["answer"]
    sent = backend.calls[-1][0]
    assert abbrev.tokens(sent["answer"]) <= settings.ABBREV_ANSWER_TOKENS and sent["question"] == big["question"]
    # 캐시는 원문 키로 — 재실행이 500 을 다시 맞지 않고 메모도 산다
    again, cached, retry2 = judge.decide("complaint", big, Q)
    assert len(backend.calls) == 1 and cached.input_tokens == 0
    assert retry2["abbrev"] == retry["abbrev"]


def test_judge_without_a_500_never_abbreviates():
    backend = ScriptedBackend(lambda s, q: {"illegible": True})
    judge = Judge(None, cache_dir=None, decision=backend)
    big = state(answer=long_text(8000))
    _, _, retry = judge.decide("complaint", big, Q)
    assert retry is None and backend.calls[0][0] == big


def test_judge_lets_a_500_through_when_no_field_is_over_cap():
    judge = Judge(None, cache_dir=None, decision=_Flaky([oom(), oom()]))
    with pytest.raises(KevHTTPError, match="CUDA"):
        judge.decide("complaint", state(), Q)


def test_judge_lets_a_500_after_abbreviation_through_with_a_note():
    judge = Judge(None, cache_dir=None, decision=_Flaky([oom(), oom(), oom()]))
    with pytest.raises(JudgeError, match="축약한 뒤에도"):
        judge.decide("complaint", state(answer=long_text(8000)), Q)


@pytest.mark.parametrize("status, detail", [
    (422, "state is 71,204 tokens; the limit is 65,536"),   # upstream kev: 한도 초과 거절
    (413, "Request Entity Too Large"),                        # 앞단 프록시: 본문 크기 제한
])
def test_judge_abbreviates_at_once_for_deterministic_too_large_codes(status, detail):
    backend = _Flaky([KevHTTPError(status, "http://kev", detail)])
    judge = Judge(None, cache_dir=None, decision=backend)
    answers, _, retry = judge.decide("complaint", state(answer=long_text(8000)), Q)
    assert answers["illegible"].p == 0.95
    assert [n["field"] for n in retry["abbrev"]] == ["answer"] and len(backend.calls) == 1


@pytest.mark.parametrize("status", [503, 400, 502, 504])
def test_judge_does_not_retry_or_abbreviate_for_other_http_codes(status):
    backend = _Flaky([KevHTTPError(status, "http://kev", "x")])
    judge = Judge(None, cache_dir=None, decision=backend)
    with pytest.raises(KevHTTPError):
        judge.decide("complaint", state(answer=long_text(8000)), Q)
    assert backend.calls == []


def test_judge_respects_the_enabled_switch(monkeypatch):
    monkeypatch.setattr(settings, "ABBREV_ENABLED", False)
    judge = Judge(None, cache_dir=None, decision=_Flaky([oom(), oom()]))
    with pytest.raises(KevHTTPError):
        judge.decide("complaint", state(answer=long_text(8000)), Q)


def test_judge_leaves_other_stages_alone():
    judge = Judge(None, cache_dir=None, decision=_Flaky([oom(), oom()]))
    with pytest.raises(KevHTTPError):
        judge.decide("evidence", {"question": long_text(9000)}, {"any": questions.EVIDENCE_ANY["any"]})


# -- 끝까지: 진짜 HTTP 500 → 축약 → 플래그가 결과에 남는다 ------------------------------

def test_a_real_kev_500_is_retried_and_flagged_end_to_end(tmp_path):
    import json as _json
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading

    from ragdiag.decide import KevBackend
    from ragdiag.features.handover import build as handover_build
    from ragdiag.output import build_output, build_turn
    from ragdiag.pipeline import judge_cases
    from stub_judge import make_case

    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = _json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(body)
            if abbrev.tokens(body["state"]) > 6000:         # 작은 컨텍스트의 kev 흉내
                payload = b"CUDA out of memory"
                self.send_response(500)
            else:
                answers = {qid: {"type": "noul", "noul": 0.02} for qid in body["questions"]}
                payload = _json.dumps({"answers": answers, "usage": {"input_tokens": 9, "output_tokens": 1}}).encode()
                self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        import dataclasses
        answer = " ".join(f"{i}번째 항목은 연차 이월 규정 제{i % 17}조의 적용 범위를 설명합니다." for i in range(300))
        assert abbrev.tokens(answer) > 6000
        case = dataclasses.replace(make_case("normal"), llm_ans_on_last_q=answer)
        judge = Judge(None, cache_dir=None, decision=KevBackend(f"http://127.0.0.1:{server.server_port}"))
        [r] = judge_cases([case], judge, workers=1, progress=False)
    finally:
        server.shutdown()
        server.server_close()
    assert r.error is None and r.verdict.bucket == "normal"
    assert len(received) == 3 and r.n_kev_calls == 3        # 원문 · 원문 재시도 · 축약
    assert [n["field"] for n in r.flags[abbrev.FLAG]] == ["answer"]
    conv = type("C", (), {"chat_id": "chat", "user": type("U", (), {"dept": "d", "job_grade": "g", "job_name": "j"})()})()
    turn = build_turn(r, conv)
    assert turn["flags"][abbrev.FLAG][0]["method"] == "elide"
    out = handover_build(build_output([(conv, r)], {}))
    assert out["플래그"] == {abbrev.FLAG: 1}
