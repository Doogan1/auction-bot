from auctionbot.bot.views import BidButton, CustomBidButton, auction_view
from auctionbot.core.models import AuctionConfig, Status
from conftest import make_auction


def test_custom_ids_encode_auction_id():
    assert BidButton.__discord_ui_compiled_template__.pattern.startswith("auction:bid:")


async def test_bid_button_custom_id_and_label():
    button = BidButton(42, min_increment=5)
    assert button.item.custom_id == "auction:bid:42"
    assert button.item.label == "Bid +5"


async def test_custom_bid_button_custom_id_and_label():
    button = CustomBidButton(42)
    assert button.item.custom_id == "auction:custom:42"
    assert button.item.label == "Custom bid"


def test_bid_button_template_matches_only_its_custom_id():
    template = BidButton.__discord_ui_compiled_template__
    assert template.fullmatch("auction:bid:42").group("id") == "42"
    assert template.fullmatch("auction:custom:42") is None
    assert template.fullmatch("auction:bid:abc") is None


def test_custom_bid_button_template_matches_its_custom_id():
    template = CustomBidButton.__discord_ui_compiled_template__
    assert template.fullmatch("auction:custom:7").group("id") == "7"
    assert template.fullmatch("auction:bid:7") is None


async def test_auction_view_has_two_enabled_items_for_open_auction():
    view = auction_view(make_auction(id=9, config=AuctionConfig(min_increment=5)))
    assert [c.item.custom_id for c in view.children] == ["auction:bid:9", "auction:custom:9"]
    assert not any(c.item.disabled for c in view.children)
    assert view.children[0].item.label == "Bid +5"


async def test_auction_view_disabled_when_closed_or_cancelled():
    for status in (Status.CLOSED, Status.CANCELLED):
        view = auction_view(make_auction(status=status))
        assert all(c.item.disabled for c in view.children)


async def test_auction_view_can_be_forced_disabled():
    view = auction_view(make_auction(), disabled=True)
    assert all(c.item.disabled for c in view.children)


async def test_view_has_no_timeout():
    assert auction_view(make_auction()).timeout is None
