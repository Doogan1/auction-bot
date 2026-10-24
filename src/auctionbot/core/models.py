from dataclasses import dataclass
from enum import Enum


class Status(Enum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class AuctionConfig:
    min_increment: int = 1
    anti_snipe_window_s: int = 30  # bids within this many seconds of ends_at may extend the deadline
    extension_s: int = 30  # deadline becomes now + extension_s after an extending bid
    max_extensions: int = 10  # extensions beyond this are not applied


@dataclass(frozen=True)
class Bid:
    bidder_id: int
    amount: int
    placed_at: float


@dataclass(frozen=True)
class Auction:
    id: int
    seller_id: int
    title: str
    starting_bid: int
    config: AuctionConfig
    ends_at: float
    status: Status
    bids: tuple[Bid, ...] = ()
    description: str = ""
    extensions_used: int = 0

    @property
    def high_bid(self) -> int | None:
        return self.bids[-1].amount if self.bids else None

    @property
    def high_bidder_id(self) -> int | None:
        return self.bids[-1].bidder_id if self.bids else None

    @property
    def minimum_next_bid(self) -> int:
        if not self.bids:
            return self.starting_bid
        return self.bids[-1].amount + self.config.min_increment

    def winning_bid(self) -> Bid | None:
        return max(self.bids, key=lambda b: b.amount, default=None)
