import asyncio

from auctionbot.clock import Clock
from auctionbot.core import rules
from auctionbot.core.models import Auction, AuctionConfig
from auctionbot.core.results import BidAccepted, BidResult, CancelResult, Cancelled
from auctionbot.storage.repository import AuctionRef, Repository

MAX_TITLE_LENGTH = 256  # Discord embed title limit
MAX_DESCRIPTION_LENGTH = 1000


class AuctionNotFound(Exception):
    pass


class AuctionService:
    """The only thing the bot layer talks to. No discord imports."""

    def __init__(self, repo: Repository, clock: Clock) -> None:
        self._repo = repo
        self._clock = clock
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock_for(self, auction_id: int) -> asyncio.Lock:
        return self._locks.setdefault(auction_id, asyncio.Lock())

    async def create_auction(
        self,
        guild_id: int,
        channel_id: int,
        seller_id: int,
        title: str,
        starting_bid: int,
        duration_s: int,
        config: AuctionConfig = AuctionConfig(),
        description: str = "",
    ) -> Auction:
        title = title.strip()
        if not title:
            raise ValueError("title must not be blank")
        if len(title) > MAX_TITLE_LENGTH:
            raise ValueError(f"title must be at most {MAX_TITLE_LENGTH} characters")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            raise ValueError(f"description must be at most {MAX_DESCRIPTION_LENGTH} characters")
        if not 1 <= starting_bid <= rules.MAX_AMOUNT:
            raise ValueError(f"starting_bid must be between 1 and {rules.MAX_AMOUNT}")
        if duration_s <= 0:
            raise ValueError("duration_s must be positive")
        if config.min_increment < 1:
            raise ValueError("min_increment must be at least 1")
        return await self._repo.create(
            guild_id=guild_id,
            channel_id=channel_id,
            seller_id=seller_id,
            title=title,
            description=description,
            starting_bid=starting_bid,
            config=config,
            ends_at=self._clock.now() + duration_s,
        )

    async def place_bid(self, auction_id: int, bidder_id: int, amount: int) -> BidResult:
        async with self._lock_for(auction_id), self._repo.transaction() as tx:
            auction = await tx.get(auction_id)
            if auction is None:
                raise AuctionNotFound(auction_id)
            new_auction, result = rules.place_bid(auction, bidder_id, amount, self._clock.now())
            if isinstance(result, BidAccepted):
                await tx.save(new_auction)
            return result

    async def close_due(self) -> list[Auction]:
        """Close every open auction past its deadline; return those that just closed."""
        now = self._clock.now()
        closed = []
        async with self._repo.transaction() as tx:
            for auction in await tx.list_due(now):
                new_auction, did_close = rules.close_if_due(auction, now)
                if did_close:
                    await tx.save(new_auction)
                    closed.append(new_auction)
        return closed

    async def cancel(self, auction_id: int, actor_id: int, is_admin: bool) -> CancelResult:
        async with self._lock_for(auction_id), self._repo.transaction() as tx:
            auction = await tx.get(auction_id)
            if auction is None:
                raise AuctionNotFound(auction_id)
            new_auction, result = rules.cancel(auction, actor_id, is_admin, self._clock.now())
            if isinstance(result, Cancelled):
                await tx.save(new_auction)
            return result

    async def get(self, auction_id: int) -> Auction:
        auction = await self._repo.get(auction_id)
        if auction is None:
            raise AuctionNotFound(auction_id)
        return auction

    async def list_open(self, guild_id: int) -> list[Auction]:
        return await self._repo.list_open(guild_id)

    async def get_ref(self, auction_id: int) -> AuctionRef:
        ref = await self._repo.get_ref(auction_id)
        if ref is None:
            raise AuctionNotFound(auction_id)
        return ref

    async def set_message_id(self, auction_id: int, message_id: int) -> None:
        await self._repo.set_message_id(auction_id, message_id)

    async def list_unannounced(self) -> list[Auction]:
        """Closed or cancelled auctions whose result has not been announced yet."""
        return await self._repo.list_unannounced()

    async def mark_announced(self, auction_id: int) -> None:
        await self._repo.mark_announced(auction_id)
