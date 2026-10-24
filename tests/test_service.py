import pytest

from auctionbot.clock import FakeClock
from auctionbot.core.models import AuctionConfig, Status
from auctionbot.core.results import (
    BidAccepted,
    BidRejected,
    Cancelled,
    RejectReason,
)
from auctionbot.core.rules import MAX_AMOUNT
from auctionbot.service import AuctionNotFound, AuctionService
from auctionbot.storage.repository import Repository

GUILD = 1
CHANNEL = 10
SELLER = 100
ALICE = 2
BOB = 3


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


async def create(service, **overrides):
    args = dict(
        guild_id=GUILD,
        channel_id=CHANNEL,
        seller_id=SELLER,
        title="Lamp",
        starting_bid=10,
        duration_s=100,
        config=AuctionConfig(min_increment=5),
    )
    args.update(overrides)
    return await service.create_auction(**args)


async def test_create_sets_ends_at_from_clock(service):
    auction = await create(service, duration_s=250)
    assert auction.ends_at == 1250.0
    assert auction.status is Status.OPEN


async def test_create_strips_title(service):
    assert (await create(service, title="  Lamp  ")).title == "Lamp"


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 257},
        {"description": "x" * 1001},
        {"starting_bid": 0},
        {"starting_bid": -1},
        {"starting_bid": MAX_AMOUNT + 1},
        {"duration_s": 0},
        {"duration_s": -5},
        {"config": AuctionConfig(min_increment=0)},
    ],
)
async def test_create_rejects_invalid_inputs(service, overrides):
    with pytest.raises(ValueError):
        await create(service, **overrides)


async def test_place_bid_accepted_persists(service):
    auction = await create(service)
    result = await service.place_bid(auction.id, ALICE, 10)
    assert isinstance(result, BidAccepted)
    stored = await service.get(auction.id)
    assert stored.high_bid == 10 and stored.high_bidder_id == ALICE


async def test_rejected_bid_persists_nothing(service):
    auction = await create(service)
    result = await service.place_bid(auction.id, ALICE, 9)
    assert result == BidRejected(RejectReason.BELOW_MINIMUM)
    assert await service.get(auction.id) == auction


async def test_huge_bid_rejected_not_crash(service):
    auction = await create(service)
    result = await service.place_bid(auction.id, ALICE, 2**70)
    assert result == BidRejected(RejectReason.INVALID_AMOUNT)


async def test_unknown_auction_raises(service):
    with pytest.raises(AuctionNotFound):
        await service.place_bid(999, ALICE, 10)
    with pytest.raises(AuctionNotFound):
        await service.cancel(999, SELLER, False)
    with pytest.raises(AuctionNotFound):
        await service.get(999)


async def test_anti_snipe_extension_persists(service, clock):
    auction = await create(service, duration_s=100)  # ends_at 1100
    clock.advance(80)  # now 1080, inside the 30s window
    result = await service.place_bid(auction.id, ALICE, 10)
    assert result == BidAccepted(extended=True, new_ends_at=1110.0)
    stored = await service.get(auction.id)
    assert stored.ends_at == 1110.0 and stored.extensions_used == 1


async def test_close_due_closes_only_expired(service, clock):
    soon = await create(service, duration_s=10)
    later = await create(service, duration_s=100)
    clock.advance(10)
    closed = await service.close_due()
    assert [a.id for a in closed] == [soon.id]
    assert closed[0].status is Status.CLOSED
    assert (await service.get(later.id)).status is Status.OPEN


async def test_close_due_is_idempotent(service, clock):
    await create(service, duration_s=10)
    clock.advance(10)
    assert len(await service.close_due()) == 1
    assert await service.close_due() == []


async def test_cancel_then_bid_rejected_as_closed(service):
    auction = await create(service)
    assert await service.cancel(auction.id, SELLER, False) == Cancelled()
    result = await service.place_bid(auction.id, ALICE, 10)
    assert result == BidRejected(RejectReason.AUCTION_CLOSED)


async def test_cancelled_auction_appears_in_unannounced_not_open(service):
    auction = await create(service)
    await service.cancel(auction.id, SELLER, False)
    assert await service.list_open(GUILD) == []
    assert [a.id for a in await service.list_unannounced()] == [auction.id]


async def test_mark_announced_removes_from_unannounced(service, clock):
    auction = await create(service, duration_s=10)
    clock.advance(10)
    await service.close_due()
    await service.mark_announced(auction.id)
    assert await service.list_unannounced() == []


async def test_message_id_round_trips_through_ref(service):
    auction = await create(service)
    await service.set_message_id(auction.id, 777)
    ref = await service.get_ref(auction.id)
    assert (ref.guild_id, ref.channel_id, ref.message_id) == (GUILD, CHANNEL, 777)
