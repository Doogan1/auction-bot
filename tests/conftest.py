from dataclasses import replace

from auctionbot.core.models import Auction, AuctionConfig, Status


def make_auction(**overrides) -> Auction:
    base = Auction(
        id=1,
        seller_id=1,
        title="Test item",
        starting_bid=10,
        config=AuctionConfig(min_increment=5),
        ends_at=1000.0,
        status=Status.OPEN,
    )
    return replace(base, **overrides)
