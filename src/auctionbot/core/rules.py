from dataclasses import replace

from auctionbot.core.models import Auction, Bid, Status
from auctionbot.core.results import BidAccepted, BidRejected, BidResult, RejectReason

# Bids above this are rejected so an amount can never overflow SQLite's 64-bit integers.
MAX_AMOUNT = 10**12


def place_bid(
    auction: Auction, bidder_id: int, amount: int, now: float
) -> tuple[Auction, BidResult]:
    """Apply a bid. A rejected bid returns the unchanged auction.

    Evaluation order, first failure wins:
      1. auction not OPEN, or now >= ends_at      -> AUCTION_CLOSED
      2. amount <= 0 or amount > MAX_AMOUNT       -> INVALID_AMOUNT
      3. bidder is the seller                     -> SELLER_CANNOT_BID
      4. bidder is the current high bidder        -> ALREADY_HIGH_BIDDER
      5. amount < minimum_next_bid                -> BELOW_MINIMUM
      6. otherwise accept; if inside the anti-snipe window and the extension
         cap is not reached, push ends_at out to now + extension_s (never earlier).
    """
    if auction.status is not Status.OPEN or now >= auction.ends_at:
        return auction, BidRejected(RejectReason.AUCTION_CLOSED)
    if amount <= 0 or amount > MAX_AMOUNT:
        return auction, BidRejected(RejectReason.INVALID_AMOUNT)
    if bidder_id == auction.seller_id:
        return auction, BidRejected(RejectReason.SELLER_CANNOT_BID)
    if bidder_id == auction.high_bidder_id:
        return auction, BidRejected(RejectReason.ALREADY_HIGH_BIDDER)
    if amount < auction.minimum_next_bid:
        return auction, BidRejected(RejectReason.BELOW_MINIMUM)

    config = auction.config
    ends_at = auction.ends_at
    extensions_used = auction.extensions_used
    if (
        auction.ends_at - now <= config.anti_snipe_window_s
        and extensions_used < config.max_extensions
    ):
        ends_at = max(auction.ends_at, now + config.extension_s)
    extended = ends_at > auction.ends_at
    if extended:
        extensions_used += 1

    new_auction = replace(
        auction,
        bids=auction.bids + (Bid(bidder_id, amount, now),),
        ends_at=ends_at,
        extensions_used=extensions_used,
    )
    return new_auction, BidAccepted(extended=extended, new_ends_at=ends_at)
