import asyncio
import logging
from collections.abc import Awaitable, Callable

from auctionbot.clock import Clock

log = logging.getLogger(__name__)


class MessageRefresher:
    """Debounces edits of auction messages to at most one per `min_interval` seconds each.

    `request()` is synchronous so handlers can call it freely. The first request after a
    quiet period edits right away; requests that arrive sooner coalesce into one trailing
    edit at `last_edit + min_interval`. `edit` reads the latest state when it runs, so one
    edit always covers every request made before it.
    """

    def __init__(
        self,
        edit: Callable[[int], Awaitable[None]],
        clock: Clock,
        min_interval: float = 2.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._edit = edit
        self._clock = clock
        self._min_interval = min_interval
        self._sleep = sleep
        self._last_edit: dict[int, float] = {}
        self._pending: dict[int, asyncio.Task] = {}

    def request(self, auction_id: int) -> None:
        if auction_id in self._pending:
            return
        last = self._last_edit.get(auction_id)
        delay = 0.0 if last is None else max(0.0, last + self._min_interval - self._clock.now())
        self._pending[auction_id] = asyncio.ensure_future(self._run(auction_id, delay))

    async def _run(self, auction_id: int, delay: float) -> None:
        if delay > 0:
            await self._sleep(delay)
        self._last_edit[auction_id] = self._clock.now()
        del self._pending[auction_id]  # later requests schedule a fresh edit
        try:
            await self._edit(auction_id)
        except Exception:
            log.exception("Failed to refresh message for auction %d", auction_id)

    async def aclose(self) -> None:
        tasks = list(self._pending.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._pending.clear()
