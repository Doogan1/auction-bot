import asyncio

import pytest

from auctionbot.bot.refresher import MessageRefresher
from auctionbot.clock import FakeClock


async def settle():
    for _ in range(10):
        await asyncio.sleep(0)


@pytest.fixture
def env():
    clock = FakeClock(100.0)
    calls = []

    async def edit(auction_id):
        calls.append((auction_id, clock.now()))

    async def sleep(seconds):
        clock.advance(seconds)
        await asyncio.sleep(0)

    return clock, calls, MessageRefresher(edit, clock, min_interval=2.0, sleep=sleep)


async def test_first_request_edits_immediately(env):
    _, calls, refresher = env
    refresher.request(1)
    await settle()
    assert calls == [(1, 100.0)]


async def test_burst_in_the_same_instant_coalesces_to_one_edit(env):
    _, calls, refresher = env
    for _ in range(10):
        refresher.request(1)
    await settle()
    assert calls == [(1, 100.0)]


async def test_requests_during_the_interval_coalesce_to_one_trailing_edit(env):
    clock, calls, refresher = env
    refresher.request(1)
    await settle()
    clock.advance(0.5)
    refresher.request(1)
    refresher.request(1)
    await settle()
    assert calls == [(1, 100.0), (1, 102.0)]


async def test_request_after_the_interval_edits_immediately(env):
    clock, calls, refresher = env
    refresher.request(1)
    await settle()
    clock.advance(5)
    refresher.request(1)
    await settle()
    assert calls == [(1, 100.0), (1, 105.0)]


async def test_auctions_are_independent(env):
    _, calls, refresher = env
    refresher.request(1)
    refresher.request(2)
    await settle()
    assert sorted(calls) == [(1, 100.0), (2, 100.0)]


async def test_edit_error_is_swallowed_and_next_edit_still_runs():
    clock = FakeClock(100.0)
    calls = []

    async def edit(auction_id):
        calls.append(auction_id)
        if len(calls) == 1:
            raise RuntimeError("discord is down")

    async def sleep(seconds):
        clock.advance(seconds)

    refresher = MessageRefresher(edit, clock, min_interval=2.0, sleep=sleep)
    refresher.request(1)
    await settle()
    clock.advance(2)
    refresher.request(1)
    await settle()
    assert calls == [1, 1]


async def test_aclose_cancels_pending_trailing_edit():
    clock = FakeClock(100.0)
    calls = []

    async def edit(auction_id):
        calls.append(auction_id)

    async def blocked_sleep(seconds):
        await asyncio.Event().wait()

    refresher = MessageRefresher(edit, clock, min_interval=2.0, sleep=blocked_sleep)
    refresher.request(1)
    await settle()
    clock.advance(0.5)
    refresher.request(1)  # trailing edit now waits in the blocked sleep
    await settle()
    await refresher.aclose()
    await settle()
    assert calls == [1]
