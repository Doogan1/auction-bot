import time

import pytest

from auctionbot.clock import FakeClock, SystemClock


def test_fake_clock_starts_at_given_time():
    assert FakeClock(10.0).now() == 10.0


def test_advance_moves_forward():
    clock = FakeClock(10)
    clock.advance(2.5)
    assert clock.now() == 12.5


def test_advance_negative_raises():
    with pytest.raises(ValueError):
        FakeClock().advance(-1)


def test_set_backwards_raises():
    clock = FakeClock(5)
    with pytest.raises(ValueError):
        clock.set(4)


def test_system_clock_is_close_to_time_time():
    assert abs(SystemClock().now() - time.time()) < 1
