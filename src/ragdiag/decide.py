"""결정 백엔드 — 범주 판정을 분류 모델(kev)에 묻는다.

kev (https://github.com/jaredpalmer/kev) 는 텍스트 하나(state)에 대해 yes/no · 택일 · 점수
문항에 **보정된 확률**로 답하는 작은 모델이다. 문장을 만들지 않는다. 이 파이프라인의
판정 결정은 전부 범주 답이라 여기로 간다 — 일반 LLM 은 문장을 만들어야 하는 자리에만
남는다 (docs/design/taxonomy_v3.md).

세 구현이 같은 모양을 가진다.

  KevBackend         POST /v1/systemone. 운영.
  LLMDecisionBackend 일반 LLM 이 같은 문항에 JSON 으로 답한다. kev 서버가 없을 때의
                     에뮬레이션이다. 확률은 self-report 라 보정돼 있지 않다 — 실행 요약에
                     "kev 에뮬레이션" 으로 찍혀야 한다.
  ScriptedBackend    테스트. 문항 id → 답 을 함수로 준다.

답은 Answer 로 통일한다. noul 은 p(yes), choice 는 확률 분포와 최빈 선택지.
"""

from __future__ import annotations

import itertools
import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional, Protocol

from pydantic import BaseModel, Field, create_model

from ragdiag.backends import JudgeError, Usage


@dataclass
class Answer:
    type: str                                  # noul · choice · score
    p: float = 0.0                             # noul: P(yes). choice: 최빈 선택지의 확률
    choice: str = ""                           # choice 의 최빈 선택지
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0

    @property
    def yes(self) -> bool:
        # 반반은 "예" 가 아니다. 에뮬레이션이 확신 없는 "아니오" 를 0.5 로 내는데, 그걸 예로
        # 읽으면 복합질문 · 거절 같은 플래그가 전부 켜진다.
        return self.type == "noul" and self.p > 0.5

    def as_dict(self) -> dict:
        out: dict[str, Any] = {"type": self.type, "p": round(self.p, 3)}
        if self.type == "choice":
            out["choice"] = self.choice
            out["probabilities"] = {k: round(v, 3) for k, v in self.probabilities.items()}
        return out


class DecisionBackend(Protocol):
    model: str
    kind: str          # "kev" · "emulated" · "scripted"

    def decide(self, state: Any, questions: dict[str, dict]) -> tuple[dict[str, Answer], Usage]: ...


def _answer_from_kev(raw: dict) -> Answer:
    kind = raw.get("type", "")
    if kind == "noul":
        return Answer("noul", p=float(raw.get("noul", 0.0)))
    if kind == "choice":
        probs = {k: float(v) for k, v in (raw.get("probabilities") or {}).items()}
        best = raw.get("choice") or (max(probs, key=probs.get) if probs else "")
        return Answer("choice", p=probs.get(best, 0.0), choice=best, probabilities=probs,
                      confidence=float(raw.get("confidence", 0.0)))
    if kind == "score":
        probs = {k: float(v) for k, v in (raw.get("probabilities") or {}).items()}
        best = max(probs, key=probs.get) if probs else ""
        return Answer("score", p=probs.get(best, 0.0), choice=best, probabilities=probs,
                      confidence=float(raw.get("confidence", 0.0)))
    raise JudgeError(f"kev 가 모르는 답 유형을 냈다: {kind}")


class KevBackend:
    """kev 서버. 요청 · 응답 모양은 README 의 System One API 그대로다.

    서버가 여러 대(사내는 8008~8011 네 대)면 url 을 목록으로 받아 요청을 **돌아가며** 보낸다.
    한 대가 안 받으면(연결 거부 · 타임아웃) 다음 대로 넘어가고, 전부 안 받을 때만 실패다. 죽은 대를
    목록에서 빼지는 않는다 — 다음 요청에서 다시 시도한다 (재기동하면 저절로 돌아온다). HTTP 오류
    (4xx · 5xx) 는 그 서버가 답한 것이라 넘기지 않고 그대로 올린다.
    """

    kind = "kev"

    def __init__(self, url: str | list[str], api_key: str = "", model: str = "kev-latest",
                 timeout: int = 120):
        urls = [url] if isinstance(url, str) else list(url)
        self.urls = [u.rstrip("/") for u in urls if u and u.strip()]
        if not self.urls:
            raise ValueError("kev 서버 주소가 비어 있다")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._next = itertools.count()
        self._lock = threading.Lock()

    def _order(self) -> list[str]:
        """이번 요청이 시도할 순서 — 돌아가며 시작점을 옮기고 나머지는 그 뒤로."""
        with self._lock:
            start = next(self._next) % len(self.urls)
        return self.urls[start:] + self.urls[:start]

    def _post(self, url: str, body: bytes) -> dict:
        req = urllib.request.Request(f"{url}/v1/systemone", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise JudgeError(f"kev {e.code} ({url}): {detail}") from e

    def decide(self, state: Any, questions: dict[str, dict]) -> tuple[dict[str, Answer], Usage]:
        body = json.dumps({"state": state, "model": self.model, "questions": questions},
                          ensure_ascii=False).encode("utf-8")
        failures: list[str] = []
        payload = None
        for url in self._order():
            try:
                payload = self._post(url, body)
                break
            except (urllib.error.URLError, TimeoutError, OSError) as e:    # 연결 자체가 안 됨 — 다음 대로
                reason = getattr(e, "reason", e)
                failures.append(f"{url}: {reason}")
        if payload is None:
            raise JudgeError(f"kev 서버 {len(self.urls)}대 어디에도 닿지 않는다 — " + " · ".join(failures))
        answers = {qid: _answer_from_kev(raw) for qid, raw in (payload.get("answers") or {}).items()}
        missing = set(questions) - set(answers)
        if missing:
            raise JudgeError(f"kev 가 답하지 않은 문항: {sorted(missing)}")
        usage = payload.get("usage") or {}
        return answers, Usage(input_tokens=int(usage.get("input_tokens", 0)),
                              output_tokens=int(usage.get("output_tokens", 0)))


# ---------------------------------------------------------------------------
# 일반 LLM 에뮬레이션
# ---------------------------------------------------------------------------

_EMULATE_SYSTEM = """\
너는 분류기다. 주어진 상태(state)에 대해 문항마다 답과 확신(0~1)을 낸다.
문장을 만들지 마라. 각 문항의 지시문과 선택지 설명을 기준으로만 답해라.
yes/no 문항은 true/false 로, 택일 문항은 선택지 이름 그대로 답해라.
확신은 그 답이 맞을 확률이다 — 애매하면 0.5~0.7, 분명하면 0.9 이상.
"""


# 출력 계약. API 경로(messages.parse)는 서버가 스키마를 강제하지만 CLI 경로에는 그런 장치가
# 없어 계약을 프롬프트에 싣는다. 손으로 쓰면 모델과 어긋나므로 Pydantic 모델에서 만든다.
_TYPE_NAMES = {"string": "문자열", "integer": "정수", "boolean": "true 또는 false",
               "number": "숫자"}


def _type_str(prop: dict, defs: dict) -> str:
    if "enum" in prop:
        return " | ".join(f'"{v}"' for v in prop["enum"])
    if prop.get("type") == "array":
        item = prop.get("items", {})
        if "$ref" in item:
            sub = defs[item["$ref"].rsplit("/", 1)[-1]]
            fields = ", ".join(f"{n}: {_type_str(p, defs)}" for n, p in sub["properties"].items())
            return f"배열. 각 원소는 {{{fields}}}"
        return f"배열 of {_TYPE_NAMES.get(item.get('type'), item.get('type'))}"
    return _TYPE_NAMES.get(prop.get("type", ""), prop.get("type", "값"))


def output_contract(model: type[BaseModel]) -> str:
    """Pydantic 모델에서 출력 계약 문구를 만든다. 필드 순서를 그대로 둔다."""
    schema = model.model_json_schema()
    defs = schema.get("$defs", {})
    lines = []
    for name, prop in schema["properties"].items():
        desc = prop.get("description", "")
        lines.append(f"  {name}: {_type_str(prop, defs)}" + (f"  // {desc}" if desc else ""))
    return ("## 출력 형식\n\n"
            "아래 필드를 **선언된 순서 그대로** 가진 JSON 객체 하나만 출력해라.\n"
            "설명, 인사말, 코드펜스 없이 JSON만 출력해라.\n\n"
            "{\n" + "\n".join(lines) + "\n}")


def _state_text(state: Any) -> str:
    if isinstance(state, str):
        return state
    return json.dumps(state, ensure_ascii=False, indent=1)


def _questions_text(questions: dict[str, dict]) -> str:
    lines = []
    for qid, q in questions.items():
        lines.append(f"### {qid} ({q['type']})")
        lines.append(q.get("instructions", ""))
        crit = q.get("criteria")
        if q["type"] == "choice" and isinstance(crit, dict):
            for k, v in crit.items():
                lines.append(f"  - {k}: {v or ''}")
        elif q["type"] == "noul" and isinstance(crit, dict):
            lines.append(f"  - true: {crit.get('true', '')}\n  - false: {crit.get('false', '')}")
        elif q["type"] == "score" and isinstance(crit, list):
            for i, v in enumerate(crit):
                lines.append(f"  - {i}: {v}")
        lines.append("")
    return "\n".join(lines)


def _emulation_model(questions: dict[str, dict]) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for qid, q in questions.items():
        if q["type"] == "noul":
            fields[qid] = (bool, Field(description=q.get("instructions", "")[:80]))
        elif q["type"] == "choice":
            options = tuple(q["criteria"].keys())
            fields[qid] = (Literal[options], Field(description="선택지 이름 그대로"))  # type: ignore[valid-type]
        else:
            n = len(q.get("criteria") or [])
            fields[qid] = (int, Field(description=f"0~{max(n - 1, 0)} 단계"))
        fields[f"{qid}__confidence"] = (float, Field(description="0~1"))
    return create_model("Decision", **fields)  # type: ignore[call-overload]


class LLMDecisionBackend:
    """kev 가 없을 때 일반 LLM 으로 같은 문항을 묻는다. 확률은 self-report 다."""

    kind = "emulated"

    def __init__(self, backend):
        self.backend = backend
        self.model = f"emulated:{getattr(backend, 'model', '?')}"

    def decide(self, state: Any, questions: dict[str, dict]) -> tuple[dict[str, Answer], Usage]:
        model = _emulation_model(questions)
        user = f"## 상태\n{_state_text(state)}\n\n## 문항\n{_questions_text(questions)}"
        parsed, usage = self.backend.complete(_EMULATE_SYSTEM, user, model,
                                              output_contract(model))
        data = parsed.model_dump()
        answers: dict[str, Answer] = {}
        for qid, q in questions.items():
            conf = min(max(float(data.get(f"{qid}__confidence", 0.5)), 0.0), 1.0)
            value = data.get(qid)
            # 답의 **방향**은 모델이 고른 쪽이고 확신은 그 방향을 날카롭게 할 뿐이다. 확신 0 을
            # "반대쪽이 확실하다" 로 읽으면 안 된다 - 그러면 "아니오, 확신 없음" 이 P(예)=1 이 된다.
            # 그래서 고른 쪽의 확률은 최소 반반(또는 1/K)이다.
            if q["type"] == "noul":
                p = max(conf, 0.5) if bool(value) else min(1.0 - conf, 0.5)
                answers[qid] = Answer("noul", p=p)
            elif q["type"] == "choice":
                options = list(q["criteria"].keys())
                k = len(options)
                p_pick = max(conf, 1.0 / k + 0.01) if k > 1 else 1.0
                rest = (1.0 - p_pick) / max(k - 1, 1)
                probs = {o: (p_pick if o == value else rest) for o in options}
                answers[qid] = Answer("choice", p=p_pick, choice=str(value), probabilities=probs,
                                      confidence=conf)
            else:
                n = len(q.get("criteria") or [])
                idx = int(value or 0)
                p_pick = max(conf, 1.0 / max(n, 1) + 0.01) if n > 1 else 1.0
                rest = (1.0 - p_pick) / max(n - 1, 1)
                probs = {str(i): (p_pick if i == idx else rest) for i in range(n)}
                answers[qid] = Answer("score", p=p_pick, choice=str(idx), probabilities=probs,
                                      confidence=conf)
        return answers, usage


# ---------------------------------------------------------------------------
# 테스트용
# ---------------------------------------------------------------------------

Script = Callable[[Any, dict[str, dict]], dict[str, Any]]


class ScriptedBackend:
    """script(state, questions) 가 문항 id → 값 을 돌려준다.

    값은 noul 이면 bool 또는 확률(float), choice 면 선택지 이름 또는 {선택지: 확률}.
    적지 않은 문항은 noul=False · choice=첫 선택지 로 채운다 (확률 0.95).
    """

    kind = "scripted"

    def __init__(self, script: Optional[Script] = None, model: str = "scripted"):
        self.script = script or (lambda state, questions: {})
        self.model = model
        self.calls: list[tuple[Any, list[str]]] = []

    def decide(self, state: Any, questions: dict[str, dict]) -> tuple[dict[str, Answer], Usage]:
        self.calls.append((state, list(questions)))
        given = self.script(state, questions) or {}
        answers: dict[str, Answer] = {}
        for qid, q in questions.items():
            value = given.get(qid)
            if q["type"] == "noul":
                if isinstance(value, bool):
                    p = 0.95 if value else 0.05
                elif isinstance(value, (int, float)):
                    p = float(value)
                else:
                    p = 0.05
                answers[qid] = Answer("noul", p=p)
            else:
                options = list(q["criteria"].keys()) if isinstance(q.get("criteria"), dict) \
                    else [str(i) for i in range(len(q.get("criteria") or []))]
                if isinstance(value, dict):
                    probs = {o: float(value.get(o, 0.0)) for o in options}
                else:
                    pick = str(value) if value is not None else options[0]
                    rest = 0.05 / max(len(options) - 1, 1)
                    probs = {o: (0.95 if o == pick else rest) for o in options}
                best = max(probs, key=probs.get)
                answers[qid] = Answer(q["type"], p=probs[best], choice=best, probabilities=probs,
                                      confidence=probs[best])
        return answers, Usage(input_tokens=1, output_tokens=1)
