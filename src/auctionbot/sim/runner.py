import random
from collections.abc import Sequence
from dataclasses import dataclass

from auctionbot.clock import FakeClock
from auctionbot.core.models import Auction
from auctionbot.core.results import BidResult
from auctionbot.core.rules import close_if_due, place_bid
from auctionbot.sim.invariants import check_auction, check_bid_step
from auctionbot.sim.strategies import Strategy


@dataclass(frozen=True)
class SimEvent:
    at: float
    bidder_id: int
    amount: int
    result: BidResult


@dataclass(frozen=True)
class SimResult:
    auction: Auction
    events: tuple[SimEvent, ...]


def run_simulation(
    auction: Auction,
    strategies: Sequence[Strategy],
    rng: random.Random,
    max_steps: int = 10_000,
    start: float = 0.0,
) -> SimResult:
    """Drive `auction` with `strategies` on a FakeClock until it closes.

    Each round every strategy plans its next bid; all intents at the earliest
    instant are then applied in ascending bidder_id order (so simultaneous bids
    were planned against the same state). The auction closes at its deadline.
    Invariants are checked after every bid. Same seed -> identical result.
    """
    clock = FakeClock(start)
    events: list[SimEvent] = []
    steps = 0
    while True:
        intents = []
        for strategy in strategies:
            intent = strategy.plan(auction, clock.now(), rng)
            if intent is not None:
                intents.append((max(intent.at, clock.now()), strategy.bidder_id, intent.amount))
        if not intents:
            break
        at = min(intent[0] for intent in intents)
        if auction.ends_at <= at:
            break
        clock.set(at)
        for _, bidder_id, amount in sorted(
            (i for i in intents if i[0] == at), key=lambda i: i[1]
        ):
            steps += 1
            if steps > max_steps:
                raise RuntimeError(f"simulation exceeded {max_steps} steps")
            before = auction
            auction, result = place_bid(before, bidder_id, amount, at)
            check_bid_step(before, auction, result, bidder_id, amount, at)
            check_auction(auction)
            events.append(SimEvent(at, bidder_id, amount, result))

    clock.set(max(clock.now(), auction.ends_at))
    auction, _ = close_if_due(auction, clock.now())
    check_auction(auction)
    return SimResult(auction, tuple(events))
