"""Auction invariants shared by the property tests and the simulator.

Every check raises AssertionError with a descriptive message.
"""

from auctionbot.core.models import Auction, Status
from auctionbot.core.results import BidAccepted, BidResult


def check_bid_step(
    before: Auction,
    after: Auction,
    result: BidResult,
    bidder_id: int,
    amount: int,
    now: float,
) -> None:
    if not isinstance(result, BidAccepted):
        assert after == before, f"rejected bid ({result}) changed the auction"
        return

    assert before.status is Status.OPEN, f"bid accepted while {before.status}"
    assert now < before.ends_at, f"bid accepted at {now} >= ends_at {before.ends_at}"
    assert amount >= before.minimum_next_bid, (
        f"bid {amount} accepted below minimum {before.minimum_next_bid}"
    )
    assert after.high_bid == amount and after.high_bidder_id == bidder_id, (
        "accepted bid is not the new high bid"
    )
    assert after.ends_at >= before.ends_at, "deadline moved earlier"
    assert result.new_ends_at == after.ends_at, "result ends_at disagrees with auction"
    assert after.extensions_used <= after.config.max_extensions, "extension cap exceeded"
    assert result.extended == (after.ends_at > before.ends_at), (
        "extended flag disagrees with deadline movement"
    )


def check_auction(auction: Auction) -> None:
    amounts = [bid.amount for bid in auction.bids]
    assert all(a < b for a, b in zip(amounts, amounts[1:])), (
        f"bid amounts not strictly increasing: {amounts}"
    )
    if auction.status is Status.CLOSED and auction.bids:
        winner = auction.winning_bid()
        assert winner is not None and winner.amount == max(amounts)
        assert amounts.count(winner.amount) == 1, "winner is not unique"
