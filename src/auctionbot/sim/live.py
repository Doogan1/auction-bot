import asyncio
import random
from collections.abc import Awaitable, Callable, Sequence

from auctionbot.clock import Clock
from auctionbot.core.models import Auction, Status
from auctionbot.core.results import BidAccepted
from auctionbot.service import AuctionService
from auctionbot.sim.strategies import Strategy

OnAccepted = Callable[[Auction, int, int, BidAccepted], Awaitable[None]]


async def run_live(
    service: AuctionService,
    auction_id: int,
    strategies: Sequence[Strategy],
    rng: random.Random,
    clock: Clock,
    on_accepted: OnAccepted,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    max_steps: int = 1000,
) -> None:
    """Drive a real auction with strategies in (possibly real) time.

    Like sim.runner, but bids go through the service and the process sleeps until each
    intent is due. It never closes the auction: it stops at the deadline and leaves
    closing and announcing to the scheduler. Stops early if the auction is no longer open.
    """
    steps = 0
    while True:
        auction = await service.get(auction_id)
        if auction.status is not Status.OPEN:
            return
        now = clock.now()
        intents = []
        for strategy in strategies:
            intent = strategy.plan(auction, now, rng)
            if intent is not None:
                intents.append((max(intent.at, now), strategy.bidder_id, intent.amount))
        if not intents:
            return
        at = min(intent[0] for intent in intents)
        if auction.ends_at <= at:
            return
        await sleep(max(0.0, at - now))
        for _, bidder_id, amount in sorted((i for i in intents if i[0] == at), key=lambda i: i[1]):
            steps += 1
            if steps > max_steps:
                raise RuntimeError(f"live simulation exceeded {max_steps} steps")
            result = await service.place_bid(auction_id, bidder_id, amount)
            if isinstance(result, BidAccepted):
                await on_accepted(await service.get(auction_id), bidder_id, amount, result)
