import logging
from typing import Protocol

from auctionbot.core.models import Auction
from auctionbot.service import AuctionService
from auctionbot.storage.repository import AuctionRef

log = logging.getLogger(__name__)


class Unannounceable(Exception):
    """Announcing can never succeed (message/channel deleted, no permission): do not retry."""


class Announcer(Protocol):
    async def announce(self, auction: Auction, ref: AuctionRef) -> None: ...


async def announce_pending(service: AuctionService, announcer: Announcer) -> int:
    """Announce every closed/cancelled auction not yet announced; return how many succeeded.

    Announcements are at-least-once: an auction is marked announced only after the post
    succeeds, so a crash in between can duplicate a post but never lose a result.
    """
    announced = 0
    for auction in await service.list_unannounced():
        try:
            await announcer.announce(auction, await service.get_ref(auction.id))
        except Unannounceable as err:
            log.warning("Giving up announcing auction %d: %s", auction.id, err)
            await service.mark_announced(auction.id)
            continue
        except Exception:
            log.exception("Failed to announce auction %d; will retry", auction.id)
            continue
        await service.mark_announced(auction.id)
        announced += 1
    return announced


async def tick(service: AuctionService, announcer: Announcer) -> None:
    """One scheduler pass. The first pass after startup doubles as restart recovery."""
    await service.close_due()
    await announce_pending(service, announcer)
