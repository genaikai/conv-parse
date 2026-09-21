"""진행 표시. 표준 라이브러리만 쓴다.

수백 턴에 LLM 을 세 번씩 부르면 수십 분이 걸리는데, 그동안 화면이 조용하면
"도는 중인지 멈춘 건지"를 알 수 없다. 실행 환경에서는 붙어서 볼 수 있는 화면이
그것뿐이라 더 그렇다.

tqdm 을 쓰지 않는 이유는 공용 venv 다. 패키지 하나가 곧 설치 승인 하나이고,
여기서 필요한 것은 한 줄짜리라 표준 라이브러리로 충분하다.

**터미널인지 아닌지에 따라 모양이 다르다.**

    터미널   \r 로 같은 줄을 덮어쓴다. 사람이 보고 있으니 자주 갱신한다
    그 외    일정 간격으로 새 줄. nohup 으로 돌리면 로그가 남는데, \r 로 쓰면
             한 줄에 수천 번 덮어쓴 흔적이 그대로 파일에 남아 읽을 수 없게 된다

남은 시간은 지금까지의 평균 속도로만 잰다. 캐시 적중이 섞이면 실제보다 짧게
나오지만, 그래도 "몇 분짜리인지"는 알 수 있다.
"""

from __future__ import annotations

import sys
import threading
import time

# 기능 이름은 영어인데 화면은 한국어다. 사람이 읽는 자리라 아는 것만 옮긴다.
LABELS = {
    "observe": "관측",
    "sufficiency": "충족도",
    "grounding": "근거 활용",
    "legibility": "읽기",
}

# 터미널이 아닐 때 줄을 남기는 간격. 둘 중 하나라도 넘으면 찍는다.
LINE_EVERY_SEC = 30.0
LINE_EVERY_FRACTION = 0.1


def _clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


class Progress:
    """한 단계의 진행을 한 줄로 보여준다. 스레드에서 done() 을 불러도 된다."""

    def __init__(self, name: str, total: int, stream=None, enabled: bool = True):
        self.label = LABELS.get(name, name)
        self.total = total
        self.stream = stream if stream is not None else sys.stderr
        self.enabled = enabled and total > 0
        self.n = 0
        self.failed = 0
        self.abandoned = 0
        self.started = time.monotonic()
        self._lock = threading.Lock()
        self._last_at = 0.0
        self._last_n = 0
        self._tty = bool(getattr(self.stream, "isatty", lambda: False)())

    def done(self, ok: bool = True) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self.n >= self.total:
                return                        # 낙오로 닫은 턴의 늦은 응답 - 이미 셌다
            self.n += 1
            self.failed += not ok
            if self._should_draw():
                self._draw(end="\r" if self._tty else "\n")

    def abandon(self) -> None:
        """낙오로 닫은 턴. 완료로 세되 실패와 따로 보인다 - 서버 문제인지 판정 문제인지가 갈린다."""
        if not self.enabled:
            return
        with self._lock:
            self.n += 1
            self.abandoned += 1
            if self._should_draw():
                self._draw(end="\r" if self._tty else "\n")

    def finish(self) -> None:
        """마지막 줄을 끝낸다. 터미널이면 덮어쓰던 줄을 닫는다."""
        if not self.enabled:
            return
        with self._lock:
            self._draw(end="\n")

    # -----------------------------------------------------------------
    def _should_draw(self) -> bool:
        if self.n >= self.total:
            return False                      # 마지막 줄은 finish() 가 찍는다
        now = time.monotonic()
        if self._tty:
            return now - self._last_at >= 0.2
        return (now - self._last_at >= LINE_EVERY_SEC
                or (self.n - self._last_n) / self.total >= LINE_EVERY_FRACTION)

    def _draw(self, end: str) -> None:
        now = time.monotonic()
        self._last_at, self._last_n = now, self.n
        elapsed = now - self.started
        width = len(f"{self.total:,}")      # 자릿수를 고정해야 숫자가 흔들리지 않는다
        parts = [f"[{self.label}] {self.n:>{width},}/{self.total:,}",
                 f"{self.n * 100 // self.total:3d}%",
                 f"경과 {_clock(elapsed)}"]
        if self.n and self.n < self.total:
            parts.append(f"남음 ~{_clock(elapsed / self.n * (self.total - self.n))}")
        if self.failed or self.abandoned:
            bits = ([f"실패 {self.failed:,}"] if self.failed else []) + \
                   ([f"포기 {self.abandoned:,}"] if self.abandoned else [])
            parts.append("(" + " · ".join(bits) + ")")
        line = "  ".join(parts)
        # 터미널에서 줄이 짧아질 때 앞 줄의 꼬리가 남는다. 지우고 쓴다.
        self.stream.write(("\x1b[2K" if self._tty else "") + line + end)
        self.stream.flush()
