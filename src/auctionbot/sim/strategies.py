import random
from dataclasses import dataclass
from typing import Protocol

from auctionbot.core.models import Auction


@dataclass(frozen=True)
class BidIntent:
    at: float
    amount: int


class Strategy(Protocol):
    bidder_id: int

    def plan(self, auction: Auction, now: float, rng: random.Random) -> BidIntent | None:
        """The next bid this bidder wants to place, or None if it has nothing more to do."""
        ...


def _raise_to_minimum(
    bidder_id: int, ceiling: int, auction: Auction, at: float
) -> BidIntent | None:
    if auction.high_bidder_id == bidder_id or auction.minimum_next_bid > ceiling:
        return None
    return BidIntent(at, auction.minimum_next_bid)


class Incrementer:
    """Always bids the minimum next bid, a few seconds after the last change, up to a ceiling."""

    def __init__(self, bidder_id: int, ceiling: int) -> None:
        self.bidder_id = bidder_id
        self.ceiling = ceiling

    def plan(self, auction: Auction, now: float, rng: random.Random) -> BidIntent | None:
        return _raise_to_minimum(self.bidder_id, self.ceiling, auction, now + rng.uniform(0.5, 5.0))


class Sniper:
    """Waits until `lead_s` seconds before the deadline, then bids the minimum."""

    def __init__(self, bidder_id: int, lead_s: float, ceiling: int) -> None:
        self.bidder_id = bidder_id
        self.lead_s = lead_s
        self.ceiling = ceiling

    def plan(self, auction: Auction, now: float, rng: random.Random) -> BidIntent | None:
        return _raise_to_minimum(
            self.bidder_id, self.ceiling, auction, max(now, auction.ends_at - self.lead_s)
        )


class BiddingWar:
    """Answers every outbid almost immediately. Use two instances against each other."""

    def __init__(self, bidder_id: int, ceiling: int) -> None:
        self.bidder_id = bidder_id
        self.ceiling = ceiling

    def plan(self, auction: Auction, now: float, rng: random.Random) -> BidIntent | None:
        return _raise_to_minimum(self.bidder_id, self.ceiling, auction, now + rng.uniform(0.1, 1.0))


class Chaos:
    """Random times and amounts, including non-positive and below-minimum ones."""

    def __init__(self, bidder_id: int) -> None:
        self.bidder_id = bidder_id

    def plan(self, auction: Auction, now: float, rng: random.Random) -> BidIntent | None:
        minimum = auction.minimum_next_bid
        amount = rng.choice(
            [
                rng.randint(-5, 0),
                rng.randint(0, minimum),
                rng.randint(minimum, minimum + 50),
            ]
        )
        return BidIntent(now + rng.uniform(0, 20), amount)


class Simultaneous:
    """Bids the minimum at one fixed instant; plans before anyone else's bid at that instant lands."""

    def __init__(self, bidder_id: int, at: float, ceiling: int) -> None:
        self.bidder_id = bidder_id
        self.at = at
        self.ceiling = ceiling

    def plan(self, auction: Auction, now: float, rng: random.Random) -> BidIntent | None:
        if now >= self.at:
            return None
        return _raise_to_minimum(self.bidder_id, self.ceiling, auction, self.at)
