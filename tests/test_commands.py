import pytest

from auctionbot.bot.actions import get_in_guild
from auctionbot.bot.client import AuctionBot
from auctionbot.bot.commands import autocomplete_choices, register
from auctionbot.clock import FakeClock
from auctionbot.config import Settings
from auctionbot.service import AuctionNotFound, AuctionService
from auctionbot.storage.repository import Repository
from conftest import make_auction


def make_bot():
    bot = AuctionBot(Settings("token", None, ":memory:"), service=None)
    register(bot)
    return bot


def test_autocomplete_filters_by_title_and_id():
    auctions = [make_auction(id=1, title="Lamp"), make_auction(id=2, title="Chair")]
    assert [c.value for c in autocomplete_choices(auctions, "lam")] == [1]
    assert [c.value for c in autocomplete_choices(auctions, "#2")] == [2]
    assert [c.value for c in autocomplete_choices(auctions, "")] == [1, 2]


def test_autocomplete_caps_at_25_and_names_at_100_chars():
    auctions = [make_auction(id=i, title="x" * 300) for i in range(1, 40)]
    choices = autocomplete_choices(auctions, "")
    assert len(choices) == 25
    assert all(len(c.name) <= 100 for c in choices)


def test_register_adds_auction_group_with_subcommands():
    group = make_bot().tree.get_command("auction")
    assert {c.name for c in group.commands} == {"start", "status", "list", "cancel"}


def test_register_adds_bid_command():
    assert make_bot().tree.get_command("bid") is not None


def test_commands_are_guild_only():
    tree = make_bot().tree
    assert tree.get_command("auction").guild_only
    assert tree.get_command("bid").guild_only


async def test_get_in_guild_rejects_auctions_from_other_guilds():
    repo = await Repository.open(":memory:")
    try:
        service = AuctionService(repo, FakeClock(1000.0))
        auction = await service.create_auction(1, 10, 100, "Lamp", 10, 60)
        assert (await get_in_guild(service, auction.id, 1)).id == auction.id
        with pytest.raises(AuctionNotFound):
            await get_in_guild(service, auction.id, 2)
        with pytest.raises(AuctionNotFound):
            await get_in_guild(service, 999, 1)
    finally:
        await repo.close()
