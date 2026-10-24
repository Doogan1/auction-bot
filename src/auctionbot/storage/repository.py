import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib import resources

import aiosqlite

from auctionbot.core.models import Auction, AuctionConfig, Bid, Status


@dataclass(frozen=True)
class AuctionRef:
    """Where an auction lives in Discord. Kept out of the core model."""

    guild_id: int
    channel_id: int
    message_id: int | None


class RepoTx:
    """Repository operations inside an open transaction. Obtained from Repository.transaction()."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def create(
        self,
        *,
        guild_id: int,
        channel_id: int,
        seller_id: int,
        title: str,
        description: str,
        starting_bid: int,
        config: AuctionConfig,
        ends_at: float,
    ) -> Auction:
        cursor = await self._conn.execute(
            "INSERT INTO auctions (guild_id, channel_id, seller_id, title, description,"
            " starting_bid, min_increment, anti_snipe_window_s, extension_s, max_extensions,"
            " ends_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                guild_id,
                channel_id,
                seller_id,
                title,
                description,
                starting_bid,
                config.min_increment,
                config.anti_snipe_window_s,
                config.extension_s,
                config.max_extensions,
                ends_at,
                Status.OPEN.value,
            ),
        )
        auction = await self.get(cursor.lastrowid)
        assert auction is not None
        return auction

    async def get(self, auction_id: int) -> Auction | None:
        async with self._conn.execute("SELECT * FROM auctions WHERE id = ?", (auction_id,)) as cur:
            row = await cur.fetchone()
        return None if row is None else await self._hydrate(row)

    async def get_ref(self, auction_id: int) -> AuctionRef | None:
        async with self._conn.execute(
            "SELECT guild_id, channel_id, message_id FROM auctions WHERE id = ?", (auction_id,)
        ) as cur:
            row = await cur.fetchone()
        return None if row is None else AuctionRef(row["guild_id"], row["channel_id"], row["message_id"])

    async def save(self, auction: Auction) -> None:
        """Write the mutable auction fields and insert any bids not yet stored."""
        await self._conn.execute(
            "UPDATE auctions SET ends_at = ?, status = ?, extensions_used = ? WHERE id = ?",
            (auction.ends_at, auction.status.value, auction.extensions_used, auction.id),
        )
        async with self._conn.execute(
            "SELECT COUNT(*) FROM bids WHERE auction_id = ?", (auction.id,)
        ) as cur:
            (stored,) = await cur.fetchone()
        for bid in auction.bids[stored:]:
            await self._conn.execute(
                "INSERT INTO bids (auction_id, bidder_id, amount, placed_at) VALUES (?, ?, ?, ?)",
                (auction.id, bid.bidder_id, bid.amount, bid.placed_at),
            )

    async def list_open(self, guild_id: int) -> list[Auction]:
        return await self._list(
            "SELECT * FROM auctions WHERE guild_id = ? AND status = 'open' ORDER BY ends_at, id",
            (guild_id,),
        )

    async def list_due(self, now: float) -> list[Auction]:
        return await self._list(
            "SELECT * FROM auctions WHERE status = 'open' AND ends_at <= ? ORDER BY ends_at, id",
            (now,),
        )

    async def list_unannounced(self) -> list[Auction]:
        return await self._list(
            "SELECT * FROM auctions WHERE status != 'open' AND closed_announced = 0 ORDER BY id"
        )

    async def set_message_id(self, auction_id: int, message_id: int) -> None:
        await self._conn.execute(
            "UPDATE auctions SET message_id = ? WHERE id = ?", (message_id, auction_id)
        )

    async def mark_announced(self, auction_id: int) -> None:
        await self._conn.execute(
            "UPDATE auctions SET closed_announced = 1 WHERE id = ?", (auction_id,)
        )

    async def _list(self, sql: str, params: tuple = ()) -> list[Auction]:
        async with self._conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [await self._hydrate(row) for row in rows]

    async def _hydrate(self, row: aiosqlite.Row) -> Auction:
        async with self._conn.execute(
            "SELECT bidder_id, amount, placed_at FROM bids WHERE auction_id = ? ORDER BY id",
            (row["id"],),
        ) as cur:
            bids = tuple(Bid(b["bidder_id"], b["amount"], b["placed_at"]) for b in await cur.fetchall())
        return Auction(
            id=row["id"],
            seller_id=row["seller_id"],
            title=row["title"],
            description=row["description"],
            starting_bid=row["starting_bid"],
            config=AuctionConfig(
                min_increment=row["min_increment"],
                anti_snipe_window_s=row["anti_snipe_window_s"],
                extension_s=row["extension_s"],
                max_extensions=row["max_extensions"],
            ),
            ends_at=row["ends_at"],
            status=Status(row["status"]),
            bids=bids,
            extensions_used=row["extensions_used"],
        )


class Repository:
    """SQLite persistence over one connection.

    A single connection cannot interleave transactions, so every access goes
    through `transaction()`, which holds one asyncio.Lock for its whole body.
    The convenience methods below each open their own transaction; do not call
    them from inside `transaction()` (the lock is not reentrant) -- use the
    yielded RepoTx instead.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()

    @classmethod
    async def open(cls, path: str) -> "Repository":
        conn = await aiosqlite.connect(path, isolation_level=None)  # we issue BEGIN/COMMIT ourselves
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.executescript(resources.files("auctionbot.storage").joinpath("schema.sql").read_text())
        return cls(conn)

    async def close(self) -> None:
        await self._conn.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[RepoTx]:
        async with self._lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield RepoTx(self._conn)
            except BaseException:
                await self._conn.rollback()
                raise
            else:
                await self._conn.commit()

    async def create(self, **kwargs) -> Auction:
        async with self.transaction() as tx:
            return await tx.create(**kwargs)

    async def get(self, auction_id: int) -> Auction | None:
        async with self.transaction() as tx:
            return await tx.get(auction_id)

    async def get_ref(self, auction_id: int) -> AuctionRef | None:
        async with self.transaction() as tx:
            return await tx.get_ref(auction_id)

    async def save(self, auction: Auction) -> None:
        async with self.transaction() as tx:
            await tx.save(auction)

    async def list_open(self, guild_id: int) -> list[Auction]:
        async with self.transaction() as tx:
            return await tx.list_open(guild_id)

    async def list_due(self, now: float) -> list[Auction]:
        async with self.transaction() as tx:
            return await tx.list_due(now)

    async def list_unannounced(self) -> list[Auction]:
        async with self.transaction() as tx:
            return await tx.list_unannounced()

    async def set_message_id(self, auction_id: int, message_id: int) -> None:
        async with self.transaction() as tx:
            await tx.set_message_id(auction_id, message_id)

    async def mark_announced(self, auction_id: int) -> None:
        async with self.transaction() as tx:
            await tx.mark_announced(auction_id)
