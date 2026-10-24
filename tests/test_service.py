import asyncio

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
        {"config": AuctionConfig(min_increment=2**70)},
        {"config": AuctionConfig(anti_snipe_window_s=-1)},
        {"config": AuctionConfig(extension_s=-1)},
        {"config": AuctionConfig(max_extensions=-1)},
        {"duration_s": 10**400},
        {"duration_s": float("nan")},
        {"duration_s": 10 * 365 * 86400},
        {"seller_id": 2**70},
        {"guild_id": 2**70},
        {"channel_id": -(2**70)},
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


async def test_out_of_range_bidder_id_raises_value_error(service):
    auction = await create(service)
    with pytest.raises(ValueError):
        await service.place_bid(auction.id, 2**70, 10)
    assert (await service.get(auction.id)).bids == ()


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


# --- concurrency and restart ------------------------------------------------


async def test_concurrent_bids_same_instant_exactly_one_winner(service):
    auction = await create(service)
    bidders = range(1000, 1050)
    results = await asyncio.gather(*(service.place_bid(auction.id, b, 10) for b in bidders))
    assert sum(isinstance(r, BidAccepted) for r in results) == 1
    assert results.count(BidRejected(RejectReason.BELOW_MINIMUM)) == 49
    assert len((await service.get(auction.id)).bids) == 1


async def test_concurrent_distinct_amounts_no_lost_updates(service):
    auction = await create(service)
    amounts = list(range(11, 41))
    results = await asyncio.gather(
        *(service.place_bid(auction.id, 1000 + a, a) for a in amounts)
    )
    accepted = [a for a, r in zip(amounts, results) if isinstance(r, BidAccepted)]
    stored = await service.get(auction.id)
    stored_amounts = [b.amount for b in stored.bids]
    assert stored_amounts == sorted(set(stored_amounts))  # strictly increasing
    assert sorted(stored_amounts) == sorted(accepted)  # nothing lost, nothing extra
    assert stored.high_bid == max(accepted)


async def test_concurrent_bids_on_different_auctions_stay_consistent(service):
    first = await create(service, title="first")
    second = await create(service, title="second")
    jobs = []
    for i in range(20):
        jobs.append(service.place_bid(first.id, 1000 + i, 10 + 5 * i))
        jobs.append(service.place_bid(second.id, 2000 + i, 10 + 5 * i))
    results = await asyncio.gather(*jobs)
    assert all(isinstance(r, BidAccepted) or isinstance(r, BidRejected) for r in results)
    for auction_id in (first.id, second.id):
        stored = await service.get(auction_id)
        amounts = [b.amount for b in stored.bids]
        assert amounts == sorted(set(amounts))
        assert all(1000 <= b.bidder_id < 1020 or 2000 <= b.bidder_id < 2020 for b in stored.bids)
    assert {b.bidder_id // 1000 for b in (await service.get(first.id)).bids} <= {1}
    assert {b.bidder_id // 1000 for b in (await service.get(second.id)).bids} <= {2}


async def test_restart_preserves_state(tmp_path, clock):
    path = str(tmp_path / "auctions.db")
    repo_a = await Repository.open(path)
    service_a = AuctionService(repo_a, clock)
    auction = await create(service_a)
    await service_a.place_bid(auction.id, ALICE, 10)
    before = await service_a.get(auction.id)
    await repo_a.close()

    repo_b = await Repository.open(path)
    service_b = AuctionService(repo_b, clock)
    assert await service_b.get(auction.id) == before
    assert isinstance(await service_b.place_bid(auction.id, BOB, 15), BidAccepted)
    assert await service_b.place_bid(auction.id, ALICE, 16) == BidRejected(RejectReason.BELOW_MINIMUM)
    await repo_b.close()


async def test_restart_close_due_closes_expired_while_offline(tmp_path, clock):
    path = str(tmp_path / "auctions.db")
    repo_a = await Repository.open(path)
    auction = await create(AuctionService(repo_a, clock), duration_s=10)
    await repo_a.close()

    clock.advance(10)  # the bot was offline past the deadline
    repo_b = await Repository.open(path)
    service_b = AuctionService(repo_b, clock)
    assert [a.id for a in await service_b.close_due()] == [auction.id]
    assert await service_b.close_due() == []
    assert [a.id for a in await service_b.list_unannounced()] == [auction.id]
    await service_b.mark_announced(auction.id)
    assert await service_b.list_unannounced() == []
    await repo_b.close()
