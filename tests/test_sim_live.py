import asyncio
import random

import pytest

from auctionbot.clock import FakeClock
from auctionbot.core.models import AuctionConfig, Status
from auctionbot.core.results import BidAccepted
from auctionbot.service import AuctionService
from auctionbot.sim.live import run_live
from auctionbot.sim.strategies import BiddingWar, Chaos, Incrementer, Sniper
from auctionbot.storage.repository import Repository

SELLER = 100
CONFIG = AuctionConfig(min_increment=5, anti_snipe_window_s=5, extension_s=5, max_extensions=3)


@pytest.fixture
async def repo():
    repository = await Repository.open(":memory:")
    yield repository
    await repository.close()


@pytest.fixture
def clock():
    return FakeClock(1000.0)


@pytest.fixture
def service(repo, clock):
    return AuctionService(repo, clock)


@pytest.fixture
def fake_sleep(clock):
    async def sleep(seconds):
        clock.advance(seconds)
        await asyncio.sleep(0)

    return sleep


async def new_auction(service, duration_s=30):
    return await service.create_auction(1, 10, SELLER, "Sim", 10, duration_s, CONFIG)


def standard_bidders():
    return [Incrementer(-1, 500), Incrementer(-2, 500), Sniper(-3, lead_s=2, ceiling=500), Chaos(-4)]


async def test_run_live_places_only_negative_id_bids(service, clock, fake_sleep):
    auction = await new_auction(service)

    async def on_accepted(*args):
        pass

    await run_live(service, auction.id, standard_bidders(), random.Random(1), clock, on_accepted, fake_sleep)
    stored = await service.get(auction.id)
    assert stored.bids and all(b.bidder_id < 0 for b in stored.bids)


async def test_run_live_stops_at_deadline_and_leaves_closing_to_scheduler(service, clock, fake_sleep):
    auction = await new_auction(service)

    async def on_accepted(*args):
        pass

    await run_live(service, auction.id, standard_bidders(), random.Random(2), clock, on_accepted, fake_sleep)
    assert (await service.get(auction.id)).status is Status.OPEN
    clock.set(max(clock.now(), (await service.get(auction.id)).ends_at))
    closed = await service.close_due()
    assert [a.id for a in closed] == [auction.id]
    assert closed[0].status is Status.CLOSED


async def test_run_live_stops_when_auction_is_cancelled(service, clock, fake_sleep):
    auction = await new_auction(service)
    seen = []

    async def on_accepted(after, bidder_id, amount, result):
        seen.append(amount)
        await service.cancel(auction.id, SELLER, False)

    await run_live(service, auction.id, standard_bidders(), random.Random(3), clock, on_accepted, fake_sleep)
    assert len(seen) == 1
    assert (await service.get(auction.id)).status is Status.CANCELLED


async def test_on_accepted_called_once_per_accepted_bid_in_order(service, clock, fake_sleep):
    auction = await new_auction(service)
    seen = []

    async def on_accepted(after, bidder_id, amount, result):
        assert isinstance(result, BidAccepted)
        assert after.high_bid == amount and after.high_bidder_id == bidder_id
        seen.append((bidder_id, amount))

    await run_live(service, auction.id, standard_bidders(), random.Random(4), clock, on_accepted, fake_sleep)
    stored = await service.get(auction.id)
    assert seen == [(b.bidder_id, b.amount) for b in stored.bids]


async def test_rejected_chaos_bids_are_not_reported(service, clock, fake_sleep):
    auction = await new_auction(service)
    seen = []

    async def on_accepted(after, bidder_id, amount, result):
        seen.append(amount)

    await run_live(service, auction.id, [Chaos(-1), Chaos(-2)], random.Random(5), clock, on_accepted, fake_sleep)
    assert len(seen) == len((await service.get(auction.id)).bids)


async def test_run_live_is_deterministic_for_a_seed(repo, fake_sleep):
    async def run(seed):
        clock = FakeClock(1000.0)
        service = AuctionService(repo, clock)
        auction = await new_auction(service)

        async def sleep(seconds):
            clock.advance(seconds)
            await asyncio.sleep(0)

        async def on_accepted(*args):
            pass

        await run_live(service, auction.id, standard_bidders(), random.Random(seed), clock, on_accepted, sleep)
        return [(b.bidder_id, b.amount, b.placed_at) for b in (await service.get(auction.id)).bids]

    assert await run(7) == await run(7)


async def test_max_steps_guard_raises(service, clock, fake_sleep):
    auction = await new_auction(service, duration_s=3600)

    async def on_accepted(*args):
        pass

    war = [BiddingWar(-1, ceiling=10**12), BiddingWar(-2, ceiling=10**12)]
    with pytest.raises(RuntimeError):
        await run_live(
            service, auction.id, war, random.Random(0), clock, on_accepted, fake_sleep, max_steps=5
        )
