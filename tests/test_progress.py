"""진행 표시 — 사람이 보는 화면과 로그 파일에 각각 맞는 모양인가.

실행 환경에서 수십 분짜리를 돌릴 때 화면이 조용하면 멈춘 것과 구별이 안 된다.
반대로 로그 파일에 \\r 로 수천 번 덮어쓰면 그 파일은 읽을 수 없게 된다.
그 둘이 이 기능의 전부라 여기서 재는 것도 그 둘이다.
"""

import io

from ragdiag.progress import Progress, _clock


class _Tty(io.StringIO):
    def isatty(self):
        return True


def test_clock_reads_as_minutes_then_hours():
    assert _clock(0) == "0:00"
    assert _clock(72) == "1:12"
    assert _clock(3700) == "1:01:40"
    assert _clock(-5) == "0:00"          # 음수가 흘러들어와도 화면은 멀쩡해야 한다


def test_a_log_file_gets_whole_lines_not_carriage_returns():
    """nohup 으로 돌린 로그가 읽히는 파일이어야 한다."""
    out = io.StringIO()
    bar = Progress("observe", 100, stream=out)
    for _ in range(100):
        bar.done()
    bar.finish()

    text = out.getvalue()
    assert "\r" not in text, "로그 파일에 제자리 갱신을 쓰면 파일이 못 읽게 된다"
    lines = [ln for ln in text.splitlines() if ln]
    assert 2 <= len(lines) <= 12, f"줄 수가 로그로 쓸 만해야 한다: {len(lines)}"
    assert lines[-1].startswith("[관측] 100/100  100%"), lines[-1]


def test_a_terminal_overwrites_one_line_and_closes_it():
    out = _Tty()
    bar = Progress("sufficiency", 3, stream=out)
    bar._last_at = -999          # 갱신 간격(0.2초)을 기다리지 않는다
    for _ in range(3):
        bar.done()
    bar.finish()

    text = out.getvalue()
    assert "\r" in text and text.endswith("\n"), "마지막 줄은 닫아야 다음 출력이 안 겹친다"
    assert "[충족도] 3/3  100%" in text


def test_failures_are_counted_on_the_line():
    out = io.StringIO()
    bar = Progress("grounding", 2, stream=out)
    bar.done(ok=False)
    bar.done()
    bar.finish()
    assert "(실패 1)" in out.getvalue()


def test_nothing_is_printed_when_disabled_or_empty():
    for bar in (Progress("observe", 10, stream=(out1 := io.StringIO()), enabled=False),
                Progress("observe", 0, stream=(out2 := io.StringIO()))):
        bar.done()
        bar.finish()
    assert out1.getvalue() == "" and out2.getvalue() == ""


def test_each_turn_shows_progress_only_for_the_llm_stages(monkeypatch, capsys):
    """코드 검증기는 눈 깜빡할 새에 끝난다 - 줄만 깜빡이면 화면이 시끄럽다."""
    from types import SimpleNamespace

    from ragdiag.features._shared import each_turn

    def ctx_with(turns):
        return SimpleNamespace(turns=turns, workers=2, progress=True,
                               open_turns=lambda: turns)

    def turns(n):
        return [SimpleNamespace(error=None, case=None) for _ in range(n)]

    each_turn(ctx_with(turns(4)), "pii", lambda t: None)
    assert capsys.readouterr().err == ""

    each_turn(ctx_with(turns(4)), "observe", lambda t: None, parallel=True)
    assert "[관측] 4/4" in capsys.readouterr().err


def test_progress_can_be_turned_off_through_the_context(capsys):
    from types import SimpleNamespace

    from ragdiag.features._shared import each_turn

    turns = [SimpleNamespace(error=None) for _ in range(3)]
    ctx = SimpleNamespace(turns=turns, workers=2, progress=False,
                          open_turns=lambda: turns)
    each_turn(ctx, "observe", lambda t: None, parallel=True)
    assert capsys.readouterr().err == ""
