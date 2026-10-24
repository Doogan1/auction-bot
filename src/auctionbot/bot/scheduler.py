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


def _log_unannounced(auction: Auction, reason: str) -> None:
    """Record the result of an auction that will never be announced, so it can be recovered."""
    winning = auction.winning_bid()
    log.error(
        "Result of auction %d (%s) was not announced (%s): winner=%s amount=%s",
        auction.id,
        auction.title,
        reason,
        winning.bidder_id if winning else None,
        winning.amount if winning else None,
    )


async def announce_pending(
    service: AuctionService,
    announcer: Announcer,
    failures: dict[int, int] | None = None,
    max_attempts: int = 30,
) -> int:
    """Announce every closed/cancelled auction not yet announced; return how many succeeded.

    Announcements are at-least-once: an auction is marked announced only after the post
    succeeds, so a crash in between can duplicate a post but never lose a result. Permanent
    failures, and transient ones that persist for `max_attempts` passes (tracked in
    `failures`, which the caller keeps between passes), are logged and given up on.
    """
    failures = failures if failures is not None else {}
    announced = 0
    for auction in await service.list_unannounced():
        try:
            await announcer.announce(auction, await service.get_ref(auction.id))
        except Unannounceable as err:
            _log_unannounced(auction, str(err))
            failures.pop(auction.id, None)
            await service.mark_announced(auction.id)
            continue
        except Exception:
            failures[auction.id] = failures.get(auction.id, 0) + 1
            if failures[auction.id] >= max_attempts:
                log.exception("Failed to announce auction %d; giving up", auction.id)
                _log_unannounced(auction, f"gave up after {max_attempts} attempts")
                failures.pop(auction.id)
                await service.mark_announced(auction.id)
            else:
                log.exception("Failed to announce auction %d; will retry", auction.id)
            continue
        failures.pop(auction.id, None)
        await service.mark_announced(auction.id)
        announced += 1
    return announced


async def tick(
    service: AuctionService,
    announcer: Announcer,
    failures: dict[int, int] | None = None,
    max_attempts: int = 30,
) -> None:
    """One scheduler pass. The first pass after startup doubles as restart recovery."""
    await service.close_due()
    await announce_pending(service, announcer, failures, max_attempts)
