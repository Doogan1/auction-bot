from dataclasses import dataclass
from enum import Enum


class RejectReason(Enum):
    AUCTION_CLOSED = "auction_closed"
    INVALID_AMOUNT = "invalid_amount"
    SELLER_CANNOT_BID = "seller_cannot_bid"
    ALREADY_HIGH_BIDDER = "already_high_bidder"
    BELOW_MINIMUM = "below_minimum"


@dataclass(frozen=True)
class BidAccepted:
    extended: bool
    new_ends_at: float


@dataclass(frozen=True)
class BidRejected:
    reason: RejectReason


BidResult = BidAccepted | BidRejected


class CancelRejectReason(Enum):
    NOT_OPEN = "not_open"
    NOT_ALLOWED = "not_allowed"


@dataclass(frozen=True)
class Cancelled:
    pass


@dataclass(frozen=True)
class CancelRejected:
    reason: CancelRejectReason


CancelResult = Cancelled | CancelRejected
