import json

import pytest

from auctionbot.bot.render import (
    auction_choice_label,
    auction_embed,
    bid_announcement,
    bidder_label,
    cancel_reject_message,
    cancelled_announcement,
    closed_announcement,
    format_amount,
    reject_message,
)
from auctionbot.core.models import Bid, Status
from auctionbot.core.results import CancelRejectReason, RejectReason
from conftest import make_auction


def embed_text(auction):
    return json.dumps(auction_embed(auction).to_dict())


def test_bidder_label_real_user_is_a_mention():
    assert bidder_label(5) == "<@5>"


def test_bidder_label_simulated_user_is_labeled():
    assert bidder_label(-3) == "SimBidder-3 (simulated)"


def test_format_amount_uses_thousands_separators():
    assert format_amount(1234567) == "1,234,567"


def test_embed_shows_deadline_as_relative_timestamp():
    assert "<t:1000:R>" in embed_text(make_auction(ends_at=1000.0))


def test_embed_shows_high_bid_and_bidder():
    text = embed_text(make_auction(bids=(Bid(7, 1500, 1.0),)))
    assert "1,500" in text and "<@7>" in text


def test_embed_without_bids_says_so():
    assert "No bids yet" in embed_text(make_auction())


def test_embed_shows_minimum_next_bid():
    assert "15" in embed_text(make_auction(bids=(Bid(7, 10, 1.0),)))


def test_closed_embed_names_the_winner():
    text = embed_text(make_auction(status=Status.CLOSED, bids=(Bid(7, 10, 1.0), Bid(8, 15, 2.0))))
    assert "<@8>" in text and "15" in text


def test_closed_embed_without_bids():
    assert "No bids" in embed_text(make_auction(status=Status.CLOSED))


def test_cancelled_embed_says_cancelled():
    assert "ancelled" in embed_text(make_auction(status=Status.CANCELLED))


def test_embed_footer_has_auction_id():
    assert auction_embed(make_auction(id=42)).footer.text == "Auction #42"


def test_extension_callout_only_when_extended():
    auction = make_auction(bids=(Bid(7, 10, 1.0),))
    callout = "Bid landed in the final 30 seconds. Deadline extended."
    assert callout in bid_announcement(auction, 7, 10, extended=True, window_s=30)
    assert callout not in bid_announcement(auction, 7, 10, extended=False, window_s=30)


def test_bid_announcement_labels_simulated_bidders():
    auction = make_auction(bids=(Bid(-2, 10, 1.0),))
    assert "SimBidder-2 (simulated)" in bid_announcement(auction, -2, 10, False, 30)


@pytest.mark.parametrize("reason", list(RejectReason))
def test_every_reject_reason_has_a_message(reason):
    assert reject_message(reason, make_auction())


def test_below_minimum_message_states_the_minimum():
    assert "10" in reject_message(RejectReason.BELOW_MINIMUM, make_auction())


@pytest.mark.parametrize("reason", list(CancelRejectReason))
def test_every_cancel_reject_reason_has_a_message(reason):
    assert cancel_reject_message(reason)


def test_closed_announcement_names_winner_and_amount():
    auction = make_auction(status=Status.CLOSED, bids=(Bid(8, 15, 2.0),))
    text = closed_announcement(auction)
    assert "<@8>" in text and "15" in text


def test_closed_announcement_without_bids():
    assert "no bids" in closed_announcement(make_auction(status=Status.CLOSED)).lower()


def test_cancelled_announcement_mentions_cancelled():
    assert "cancelled" in cancelled_announcement(make_auction(status=Status.CANCELLED)).lower()


def test_choice_label_truncated_to_100_chars():
    assert len(auction_choice_label(make_auction(title="x" * 300))) <= 100


def test_choice_label_has_id_title_and_amount():
    label = auction_choice_label(make_auction(id=3, title="Lamp"))
    assert label.startswith("#3 Lamp") and "10" in label


def test_titles_cannot_ping_in_announcement_text():
    auction = make_auction(title="@everyone", status=Status.CLOSED, bids=(Bid(8, 15, 2.0),))
    for text in (
        closed_announcement(auction),
        cancelled_announcement(auction),
        bid_announcement(auction, 8, 15, False, 30),
    ):
        assert "@everyone" not in text


def test_closed_announcement_opens_with_a_hammer():
    winner = make_auction(status=Status.CLOSED, bids=(Bid(8, 15, 2.0),))
    assert closed_announcement(winner).startswith("🔨")
    assert closed_announcement(make_auction(status=Status.CLOSED)).startswith("🔨")


def test_cancelled_announcement_has_no_hammer():
    assert "🔨" not in cancelled_announcement(make_auction(status=Status.CANCELLED))
