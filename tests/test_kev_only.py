"""kev 만 있고 일반 LLM 이 없어도 돈다 — 2차 판정만 건너뛴다. 서버 여러 대면 돌아가며 보낸다."""

import json
import os

from ragdiag.fixtures.synth import generate

from test_decide import _KevServer


def _unset_llm(monkeypatch):
    for name in ("LLM_API_URL", "API_URL", "RAGDIAG_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE",
                 "LLM_API_KEY", "API_KEY", "RAGDIAG_API_KEY", "OPENAI_API_KEY", "RAGDIAG_MODEL"):
        monkeypatch.delenv(name, raising=False)


def test_kev_only_run_spreads_requests_and_skips_the_second_pass(tmp_path, monkeypatch):
    from ragdiag.__main__ import main

    _unset_llm(monkeypatch)
    log = tmp_path / "conv.json"
    log.write_text(json.dumps(generate(n=3, seed=1), ensure_ascii=False), encoding="utf-8")
    with _KevServer() as a, _KevServer() as b:
        cfg = tmp_path / "env.yaml"
        cfg.write_text(f"kev:\n  url:\n    - {a.url}\n    - {b.url}\n", encoding="utf-8")
        code = main(["--conv-data", str(log), "--config", str(cfg), "--limit", "4", "--no-cache",
                     "--no-progress", "--output-dir", str(tmp_path / "out")])
        assert code == 0
        assert a.received and b.received, "두 대가 다 요청을 받아야 한다"
    [out] = [p for p in (tmp_path / "out").iterdir() if p.suffix == ".json"]
    run = json.loads(out.read_text(encoding="utf-8"))["run"]
    assert run["kev_kind"] == "kev" and run["kev_servers"] == [a.url, b.url]
    assert run["second_pass"] == ""
