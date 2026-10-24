import asyncio
from dataclasses import replace

import pytest

from auctionbot.core.models import AuctionConfig, Bid, Status
from auctionbot.storage.repository import AuctionRef, Repository

GUILD = 1
CHANNEL = 10
SELLER = 100


def create_args(**overrides):
    args = dict(
        guild_id=GUILD,
        channel_id=CHANNEL,
        seller_id=SELLER,
        title="Lamp",
        description="",
        starting_bid=10,
        config=AuctionConfig(min_increment=5),
        ends_at=1000.0,
    )
    args.update(overrides)
    return args


@pytest.fixture
async def repo():
    repository = await Repository.open(":memory:")
    yield repository
    await repository.close()


async def test_create_then_get_round_trips_all_fields(repo):
    config = AuctionConfig(min_increment=7, anti_snipe_window_s=20, extension_s=15, max_extensions=4)
    created = await repo.create(**create_args(description="an old lamp", config=config))
    assert created.status is Status.OPEN
    assert created.bids == ()
    assert created.extensions_used == 0
    assert await repo.get(created.id) == created
    assert created.description == "an old lamp"
    assert created.config == config
    assert created.seller_id == SELLER and created.starting_bid == 10 and created.ends_at == 1000.0


async def test_get_missing_returns_none(repo):
    assert await repo.get(999) is None
    assert await repo.get_ref(999) is None


async def test_save_appends_only_new_bids(repo):
    created = await repo.create(**create_args())
    one = replace(created, bids=(Bid(2, 10, 1.0),))
    await repo.save(one)
    two = replace(one, bids=one.bids + (Bid(3, 15, 2.0),), ends_at=1030.0, extensions_used=1)
    await repo.save(two)
    await repo.save(two)  # saving again must not duplicate bids
    assert await repo.get(created.id) == two


async def test_list_open_filters_by_guild_and_status(repo):
    mine = await repo.create(**create_args())
    await repo.create(**create_args(guild_id=2))
    closed = await repo.create(**create_args())
    await repo.save(replace(closed, status=Status.CLOSED))
    assert [a.id for a in await repo.list_open(GUILD)] == [mine.id]


async def test_list_due_boundary(repo):
    due = await repo.create(**create_args(ends_at=100.0))
    await repo.create(**create_args(ends_at=100.5))
    already_closed = await repo.create(**create_args(ends_at=50.0))
    await repo.save(replace(already_closed, status=Status.CLOSED))
    assert [a.id for a in await repo.list_due(100.0)] == [due.id]


async def test_list_unannounced_and_mark_announced(repo):
    open_one = await repo.create(**create_args())
    closed = await repo.create(**create_args())
    cancelled = await repo.create(**create_args())
    await repo.save(replace(closed, status=Status.CLOSED))
    await repo.save(replace(cancelled, status=Status.CANCELLED))
    assert {a.id for a in await repo.list_unannounced()} == {closed.id, cancelled.id}
    assert open_one.id not in {a.id for a in await repo.list_unannounced()}
    await repo.mark_announced(closed.id)
    assert [a.id for a in await repo.list_unannounced()] == [cancelled.id]


async def test_set_message_id_and_get_ref(repo):
    created = await repo.create(**create_args())
    assert await repo.get_ref(created.id) == AuctionRef(GUILD, CHANNEL, None)
    await repo.set_message_id(created.id, 555)
    assert await repo.get_ref(created.id) == AuctionRef(GUILD, CHANNEL, 555)


async def test_transaction_rolls_back_on_exception(repo):
    with pytest.raises(RuntimeError):
        async with repo.transaction() as tx:
            await tx.create(**create_args())
            raise RuntimeError("boom")
    assert await repo.list_open(GUILD) == []


async def test_transactions_do_not_interleave(repo):
    order = []

    async def worker(name):
        async with repo.transaction() as tx:
            order.append(f"{name}-start")
            await asyncio.sleep(0)
            await tx.create(**create_args(title=name))
            order.append(f"{name}-end")

    await asyncio.gather(worker("a"), worker("b"))
    assert order == ["a-start", "a-end", "b-start", "b-end"]
    assert len(await repo.list_open(GUILD)) == 2


async def test_cancelled_tasks_do_not_poison_the_connection(repo):
    created = await repo.create(**create_args())
    for ticks in range(200):
        task = asyncio.ensure_future(repo.get(created.id))
        for _ in range(ticks % 7):
            await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    assert await repo.get(created.id) == created
