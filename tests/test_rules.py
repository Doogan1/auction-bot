from dataclasses import replace

import pytest

from auctionbot.core.models import AuctionConfig, Bid, Status
from auctionbot.core.results import (
    BidAccepted,
    BidRejected,
    CancelRejected,
    CancelRejectReason,
    Cancelled,
    RejectReason,
)
from auctionbot.core.rules import MAX_AMOUNT, cancel, close_if_due, place_bid
from conftest import make_auction

SELLER = 1
ALICE = 2
BOB = 3


def assert_rejected(auction, bidder_id, amount, now, reason):
    new, result = place_bid(auction, bidder_id, amount, now)
    assert result == BidRejected(reason)
    assert new == auction


# --- evaluation order -------------------------------------------------------


def test_closed_status_rejected_first():
    auction = make_auction(status=Status.CLOSED)
    assert_rejected(auction, SELLER, 0, 10.0, RejectReason.AUCTION_CLOSED)


def test_invalid_amount_before_seller():
    assert_rejected(make_auction(), SELLER, 0, 10.0, RejectReason.INVALID_AMOUNT)


def test_seller_before_already_high():
    auction = make_auction(bids=(Bid(SELLER, 10, 1.0),))
    assert_rejected(auction, SELLER, 15, 10.0, RejectReason.SELLER_CANNOT_BID)


def test_already_high_before_below_minimum():
    auction = make_auction(bids=(Bid(ALICE, 10, 1.0),))
    assert_rejected(auction, ALICE, 11, 10.0, RejectReason.ALREADY_HIGH_BIDDER)


# --- each reason on its own -------------------------------------------------


def test_cancelled_auction_rejects_as_closed():
    auction = make_auction(status=Status.CANCELLED)
    assert_rejected(auction, ALICE, 10, 10.0, RejectReason.AUCTION_CLOSED)


def test_negative_amount_invalid():
    assert_rejected(make_auction(), ALICE, -5, 10.0, RejectReason.INVALID_AMOUNT)


@pytest.mark.parametrize("amount", [MAX_AMOUNT + 1, 2**70])
def test_amount_above_max_invalid(amount):
    assert_rejected(make_auction(), ALICE, amount, 10.0, RejectReason.INVALID_AMOUNT)


@pytest.mark.parametrize("amount", [10.5, float("nan"), True, "15"])
def test_non_int_amount_invalid(amount):
    assert_rejected(make_auction(), ALICE, amount, 10.0, RejectReason.INVALID_AMOUNT)


def test_max_amount_itself_is_accepted():
    _, result = place_bid(make_auction(), ALICE, MAX_AMOUNT, 10.0)
    assert isinstance(result, BidAccepted)


def test_seller_cannot_bid():
    assert_rejected(make_auction(), SELLER, 10, 10.0, RejectReason.SELLER_CANNOT_BID)


def test_current_high_bidder_cannot_bid_again():
    auction = make_auction(bids=(Bid(ALICE, 10, 1.0),))
    assert_rejected(auction, ALICE, 50, 10.0, RejectReason.ALREADY_HIGH_BIDDER)


# --- minimums ---------------------------------------------------------------


def test_first_bid_equal_to_starting_bid_accepted():
    new, result = place_bid(make_auction(), ALICE, 10, 10.0)
    assert isinstance(result, BidAccepted)
    assert new.bids == (Bid(ALICE, 10, 10.0),)


def test_first_bid_below_starting_bid_rejected():
    assert_rejected(make_auction(), ALICE, 9, 10.0, RejectReason.BELOW_MINIMUM)


def test_bid_below_high_plus_increment_rejected_and_exact_accepted():
    auction = make_auction(bids=(Bid(ALICE, 10, 1.0),))
    assert_rejected(auction, BOB, 14, 10.0, RejectReason.BELOW_MINIMUM)
    new, result = place_bid(auction, BOB, 15, 10.0)
    assert isinstance(result, BidAccepted)
    assert new.high_bid == 15 and new.high_bidder_id == BOB


def test_equal_amount_to_high_bid_rejected():
    auction = make_auction(bids=(Bid(ALICE, 10, 1.0),))
    assert_rejected(auction, BOB, 10, 10.0, RejectReason.BELOW_MINIMUM)


# --- time boundaries --------------------------------------------------------


def test_bid_just_before_ends_at_accepted():
    _, result = place_bid(make_auction(), ALICE, 10, 999.999)
    assert isinstance(result, BidAccepted)


def test_bid_exactly_at_ends_at_rejected():
    assert_rejected(make_auction(), ALICE, 10, 1000.0, RejectReason.AUCTION_CLOSED)


def test_bid_after_ends_at_rejected():
    assert_rejected(make_auction(), ALICE, 10, 1000.5, RejectReason.AUCTION_CLOSED)


# --- anti-snipe -------------------------------------------------------------


def test_bid_outside_window_does_not_extend():
    new, result = place_bid(make_auction(), ALICE, 10, 900.0)
    assert result == BidAccepted(extended=False, new_ends_at=1000.0)
    assert new.ends_at == 1000.0 and new.extensions_used == 0


def test_bid_inside_window_extends_to_now_plus_extension():
    new, result = place_bid(make_auction(), ALICE, 10, 980.0)
    assert result == BidAccepted(extended=True, new_ends_at=1010.0)
    assert new.ends_at == 1010.0
    assert new.extensions_used == 1


def test_bid_at_exact_window_edge_does_not_move_deadline():
    new, result = place_bid(make_auction(), ALICE, 10, 970.0)
    assert result == BidAccepted(extended=False, new_ends_at=1000.0)
    assert new.ends_at == 1000.0 and new.extensions_used == 0


def test_deadline_never_moves_earlier():
    config = AuctionConfig(min_increment=5, anti_snipe_window_s=30, extension_s=5)
    new, result = place_bid(make_auction(config=config), ALICE, 10, 990.0)
    assert result == BidAccepted(extended=False, new_ends_at=1000.0)
    assert new.ends_at == 1000.0


def test_extension_cap_stops_moving_the_deadline_but_accepts_bid():
    config = AuctionConfig(min_increment=5, max_extensions=2)
    auction = make_auction(config=config, extensions_used=2)
    new, result = place_bid(auction, ALICE, 10, 995.0)
    assert result == BidAccepted(extended=False, new_ends_at=1000.0)
    assert new.ends_at == 1000.0
    assert new.extensions_used == 2
    assert new.high_bid == 10


def test_rejected_bid_does_not_count_as_extension():
    auction = make_auction(bids=(Bid(ALICE, 10, 1.0),))
    new, _ = place_bid(auction, BOB, 11, 995.0)
    assert new == auction


# --- close_if_due -----------------------------------------------------------


def test_close_if_due_before_ends_at_does_nothing():
    auction = make_auction()
    new, closed = close_if_due(auction, 999.9)
    assert closed is False and new == auction


def test_close_if_due_at_ends_at_closes():
    new, closed = close_if_due(make_auction(), 1000.0)
    assert closed is True and new.status is Status.CLOSED


def test_close_if_due_is_idempotent():
    closed_auction, _ = close_if_due(make_auction(), 1000.0)
    again, closed = close_if_due(closed_auction, 2000.0)
    assert closed is False and again == closed_auction


def test_close_if_due_ignores_cancelled():
    auction = make_auction(status=Status.CANCELLED)
    new, closed = close_if_due(auction, 2000.0)
    assert closed is False and new == auction


def test_close_with_bids_keeps_them_and_winner_is_max_bid():
    auction = make_auction(bids=(Bid(ALICE, 10, 1.0), Bid(BOB, 15, 2.0)))
    new, _ = close_if_due(auction, 1000.0)
    assert new.bids == auction.bids
    assert new.winning_bid() == Bid(BOB, 15, 2.0)


def test_close_without_bids_has_no_winner():
    new, closed = close_if_due(make_auction(), 1000.0)
    assert closed is True and new.winning_bid() is None


# --- cancel -----------------------------------------------------------------


def test_seller_can_cancel_and_bids_are_kept():
    auction = make_auction(bids=(Bid(ALICE, 10, 1.0),))
    new, result = cancel(auction, SELLER, False, 10.0)
    assert result == Cancelled()
    assert new.status is Status.CANCELLED and new.bids == auction.bids


def test_admin_non_seller_can_cancel():
    new, result = cancel(make_auction(), 99, True, 10.0)
    assert result == Cancelled() and new.status is Status.CANCELLED


def test_other_user_cannot_cancel():
    auction = make_auction()
    new, result = cancel(auction, ALICE, False, 10.0)
    assert result == CancelRejected(CancelRejectReason.NOT_ALLOWED)
    assert new == auction


def test_cancel_closed_auction_not_open_even_for_non_seller():
    auction = make_auction(status=Status.CLOSED)
    new, result = cancel(auction, ALICE, False, 10.0)
    assert result == CancelRejected(CancelRejectReason.NOT_OPEN)
    assert new == auction


def test_cancel_open_but_past_deadline_is_not_open():
    auction = make_auction()
    new, result = cancel(auction, SELLER, False, 1000.0)
    assert result == CancelRejected(CancelRejectReason.NOT_OPEN)
    assert new == auction


def test_bid_after_cancel_rejected_as_closed():
    cancelled, _ = cancel(make_auction(), SELLER, False, 10.0)
    assert_rejected(cancelled, ALICE, 10, 11.0, RejectReason.AUCTION_CLOSED)
