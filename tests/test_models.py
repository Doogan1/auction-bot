import dataclasses

import pytest

from auctionbot.core.models import Bid
from conftest import make_auction


def test_minimum_next_bid_is_starting_bid_when_no_bids():
    assert make_auction().minimum_next_bid == 10


def test_minimum_next_bid_adds_increment():
    auction = make_auction(bids=(Bid(2, 10, 1.0),))
    assert auction.minimum_next_bid == 15


def test_high_bid_and_bidder():
    auction = make_auction(bids=(Bid(2, 10, 1.0), Bid(3, 15, 2.0)))
    assert auction.high_bid == 15
    assert auction.high_bidder_id == 3


def test_high_bid_none_without_bids():
    auction = make_auction()
    assert auction.high_bid is None
    assert auction.high_bidder_id is None


def test_winning_bid_none_without_bids():
    assert make_auction().winning_bid() is None


def test_winning_bid_is_the_max_bid():
    auction = make_auction(bids=(Bid(2, 10, 1.0), Bid(3, 15, 2.0)))
    assert auction.winning_bid() == Bid(3, 15, 2.0)


def test_auction_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        make_auction().title = "other"
