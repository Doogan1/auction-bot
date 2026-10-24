import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float: ...


class SystemClock:
    def now(self) -> float:
        return time.time()


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("cannot advance by a negative amount")
        self._now += seconds

    def set(self, t: float) -> None:
        if t < self._now:
            raise ValueError("cannot set the clock backwards")
        self._now = t
