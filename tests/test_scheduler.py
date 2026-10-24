import pytest

from auctionbot.bot.scheduler import Unannounceable, announce_pending, tick
from auctionbot.clock import FakeClock
from auctionbot.core.models import Status
from auctionbot.service import AuctionService
from auctionbot.storage.repository import Repository

SELLER = 100


class RecordingAnnouncer:
    def __init__(self, failures=None):
        self.announced = []
        self.failures = failures or {}  # auction id -> list of exceptions to raise, in order

    async def announce(self, auction, ref):
        queue = self.failures.get(auction.id)
        if queue:
            raise queue.pop(0)
        self.announced.append((auction.id, auction.status))


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


async def create(service, duration_s=10):
    return await service.create_auction(1, 10, SELLER, "Lamp", 10, duration_s)


async def test_closed_auction_announced_once(service, clock):
    auction = await create(service)
    clock.advance(10)
    announcer = RecordingAnnouncer()
    await tick(service, announcer)
    assert announcer.announced == [(auction.id, Status.CLOSED)]


async def test_second_tick_does_not_reannounce(service, clock):
    await create(service)
    clock.advance(10)
    announcer = RecordingAnnouncer()
    await tick(service, announcer)
    await tick(service, announcer)
    assert len(announcer.announced) == 1


async def test_cancelled_auction_is_announced(service):
    auction = await create(service, duration_s=100)
    await service.cancel(auction.id, SELLER, False)
    announcer = RecordingAnnouncer()
    await tick(service, announcer)
    assert announcer.announced == [(auction.id, Status.CANCELLED)]


async def test_unannounceable_marks_announced_and_continues_with_others(service, clock):
    first = await create(service)
    second = await create(service)
    clock.advance(10)
    announcer = RecordingAnnouncer({first.id: [Unannounceable("channel deleted")]})
    await tick(service, announcer)
    assert [a for a, _ in announcer.announced] == [second.id]
    assert await service.list_unannounced() == []


async def test_transient_error_leaves_unannounced_and_retries_next_tick(service, clock):
    auction = await create(service)
    clock.advance(10)
    announcer = RecordingAnnouncer({auction.id: [RuntimeError("discord hiccup")]})
    await service.close_due()
    assert await announce_pending(service, announcer) == 0
    assert [a.id for a in await service.list_unannounced()] == [auction.id]
    assert await announce_pending(service, announcer) == 1
    assert await service.list_unannounced() == []


async def test_one_failing_auction_does_not_block_the_next(service, clock):
    first = await create(service)
    second = await create(service)
    clock.advance(10)
    announcer = RecordingAnnouncer({first.id: [RuntimeError("boom")]})
    await tick(service, announcer)
    assert [a for a, _ in announcer.announced] == [second.id]
    assert [a.id for a in await service.list_unannounced()] == [first.id]


async def test_auction_closed_while_offline_is_announced_on_first_tick(tmp_path, clock):
    path = str(tmp_path / "auctions.db")
    repo_a = await Repository.open(path)
    auction = await create(AuctionService(repo_a, clock), duration_s=10)
    await repo_a.close()

    clock.advance(60)  # the bot was down past the deadline
    repo_b = await Repository.open(path)
    announcer = RecordingAnnouncer()
    await tick(AuctionService(repo_b, clock), announcer)
    assert announcer.announced == [(auction.id, Status.CLOSED)]
    await repo_b.close()


async def test_open_auctions_untouched(service):
    auction = await create(service, duration_s=100)
    announcer = RecordingAnnouncer()
    await tick(service, announcer)
    assert announcer.announced == []
    assert (await service.get(auction.id)).status is Status.OPEN
