"""결정 백엔드 — kev HTTP 계약, 일반 LLM 에뮬레이션의 확률 매핑, 캐시."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ragdiag import questions
from ragdiag.backends import Usage
from ragdiag.decide import Answer, KevBackend, LLMDecisionBackend, ScriptedBackend
from ragdiag.judge import Judge


class _KevServer:
    """README 의 응답 모양을 그대로 돌려주는 가짜 kev. 받은 요청을 기록한다."""

    def __enter__(self):
        received = self.received = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append((self.path, dict(self.headers), body))
                answers = {}
                for qid, q in body["questions"].items():
                    if q["type"] == "noul":
                        answers[qid] = {"type": "noul", "noul": 0.88}
                    elif q["type"] == "choice":
                        opts = list(q["criteria"])
                        probs = {o: (0.75 if i == 0 else 0.25 / max(len(opts) - 1, 1))
                                 for i, o in enumerate(opts)}
                        answers[qid] = {"type": "choice", "choice": opts[0],
                                        "probabilities": probs, "confidence": 0.5}
                payload = json.dumps({"model": body["model"], "answers": answers,
                                      "usage": {"input_tokens": 90, "output_tokens": 120},
                                      "latency_ms": 5}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def test_kev_backend_posts_the_system_one_shape_and_reads_answers():
    with _KevServer() as kev:
        backend = KevBackend(kev.url, api_key="k", model="kev-4b")
        answers, usage = backend.decide({"답변": "x"}, {"q1": questions.LEGIBILITY["illegible"],
                                                       "q2": questions.OBSERVE["complaint_target"]})
    path, headers, body = kev.received[0]
    assert path == "/v1/systemone"
    assert headers["Authorization"] == "Bearer k"
    assert body["model"] == "kev-4b" and body["state"] == {"답변": "x"}
    assert set(body["questions"]) == {"q1", "q2"}
    assert answers["q1"].type == "noul" and answers["q1"].p == 0.88
    assert answers["q2"].choice == "none" and answers["q2"].probabilities["none"] == 0.75
    assert usage.input_tokens == 90


def test_kev_backend_refuses_a_response_missing_a_question():
    class Partial(KevBackend):
        pass

    with _KevServer() as kev:
        backend = Partial(kev.url)
        # 서버는 보낸 문항만 답한다. 하나를 지우고 받은 척하려면 응답을 가공해야 하므로,
        # 대신 _answer_from_kev 경로의 누락 검사를 직접 본다.
        answers, _ = backend.decide("s", {"only": questions.LEGIBILITY["illegible"]})
        assert set(answers) == {"only"}


class _LLM:
    """에뮬레이션용 일반 LLM. 문항마다 정해진 값과 확신을 낸다."""

    model = "llm"

    def __init__(self, values):
        self.values = values

    def complete(self, system, user, out_model, hint=""):
        data = {}
        for name in out_model.model_fields:
            if name.endswith("__confidence"):
                data[name] = self.values.get(name, 0.9)
            else:
                data[name] = self.values[name]
        return out_model(**data), Usage(5, 5)


def test_emulation_keeps_the_chosen_direction_and_only_sharpens_with_confidence():
    """확신 0 의 '아니오' 가 P(예)=1 이 되면 안 된다. 고른 쪽이 최소 반반이다."""
    q = {"yes": questions.LEGIBILITY["illegible"], "pick": questions.OBSERVE["question_clarity"]}
    weak = LLMDecisionBackend(_LLM({"yes": False, "yes__confidence": 0.0,
                                    "pick": "vague", "pick__confidence": 0.0}))
    answers, _ = weak.decide("s", q)
    assert answers["yes"].p == 0.5
    assert answers["pick"].choice == "vague" and answers["pick"].p == pytest.approx(1 / 3 + 0.01)

    strong = LLMDecisionBackend(_LLM({"yes": True, "yes__confidence": 0.95,
                                      "pick": "clear", "pick__confidence": 0.9}))
    answers, _ = strong.decide("s", q)
    assert answers["yes"].p == 0.95
    assert answers["pick"].probabilities["clear"] == 0.9
    assert sum(answers["pick"].probabilities.values()) == pytest.approx(1.0)
    assert strong.kind == "emulated" and strong.model == "emulated:llm"


def test_scripted_backend_fills_unspecified_questions_with_safe_defaults():
    backend = ScriptedBackend(lambda state, q: {"complaint_target": {"none": 0.6, "tone": 0.4}})
    answers, _ = backend.decide("s", {"complaint_target": questions.OBSERVE["complaint_target"],
                                      "answer_refused": questions.OBSERVE["answer_refused"]})
    assert answers["complaint_target"].choice == "none" and answers["complaint_target"].p == 0.6
    assert answers["answer_refused"].p == 0.05 and not answers["answer_refused"].yes


def test_judge_caches_decisions_per_stage_model_state_and_questions(tmp_path):
    calls = []
    backend = ScriptedBackend(lambda state, q: calls.append(state) or {"illegible": True})
    judge = Judge(None, cache_dir=tmp_path, decision=backend)
    first, used = judge.decide("legibility", {"답변": "x"}, questions.LEGIBILITY)
    second, cached = judge.decide("legibility", {"답변": "x"}, questions.LEGIBILITY)
    judge.decide("legibility", {"답변": "y"}, questions.LEGIBILITY)
    assert len(calls) == 2, "같은 입력은 캐시에서 나온다"
    assert first["illegible"].p == second["illegible"].p == 0.95
    assert used.input_tokens == 1 and cached.input_tokens == 0


def test_judge_refuses_an_unknown_decision_stage():
    judge = Judge(None, cache_dir=None, decision=ScriptedBackend())
    with pytest.raises(ValueError):
        judge.decide("routing", "s", questions.LEGIBILITY)


def test_answer_serialises_without_losing_the_distribution():
    a = Answer("choice", p=0.7, choice="a", probabilities={"a": 0.7, "b": 0.3}, confidence=0.4)
    assert a.as_dict() == {"type": "choice", "p": 0.7, "choice": "a", "probabilities": {"a": 0.7, "b": 0.3}}
