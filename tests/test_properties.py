from hypothesis import given
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from auctionbot.core.models import AuctionConfig, Status
from auctionbot.core.results import BidRejected
from auctionbot.core.rules import cancel, close_if_due, place_bid
from auctionbot.sim.invariants import check_auction, check_bid_step
from conftest import make_auction

SELLER = 0

configs = st.builds(
    AuctionConfig,
    min_increment=st.integers(1, 20),
    anti_snipe_window_s=st.integers(0, 60),
    extension_s=st.integers(0, 60),
    max_extensions=st.integers(0, 5),
)
actions = st.lists(
    st.tuples(
        st.floats(0, 15, allow_nan=False),  # dt
        st.integers(0, 6),  # bidder (0 is the seller)
        st.integers(-5, 300),  # amount
    ),
    max_size=60,
)


@given(config=configs, steps=actions)
def test_invariants_hold_over_random_bid_sequences(config, steps):
    auction = make_auction(seller_id=SELLER, config=config)
    now = 950.0
    for dt, bidder_id, amount in steps:
        now += dt
        before = auction
        auction, result = place_bid(before, bidder_id, amount, now)
        check_bid_step(before, auction, result, bidder_id, amount, now)
        check_auction(auction)
    auction, _ = close_if_due(auction, auction.ends_at)
    check_auction(auction)


@given(config=configs, steps=actions)
def test_high_bid_and_ends_at_never_decrease(config, steps):
    auction = make_auction(seller_id=SELLER, config=config)
    now = 950.0
    high, ends_at = 0, auction.ends_at
    for dt, bidder_id, amount in steps:
        now += dt
        auction, _ = place_bid(auction, bidder_id, amount, now)
        assert (auction.high_bid or 0) >= high
        assert auction.ends_at >= ends_at
        high, ends_at = auction.high_bid or 0, auction.ends_at


class AuctionMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        config = AuctionConfig(min_increment=3, max_extensions=3)
        self.auction = make_auction(seller_id=SELLER, config=config)
        self.now = 900.0
        self.terminal = None

    @rule(bidder=st.integers(0, 4), amount=st.integers(-2, 200))
    def bid(self, bidder, amount):
        before = self.auction
        self.auction, result = place_bid(before, bidder, amount, self.now)
        check_bid_step(before, self.auction, result, bidder, amount, self.now)
        if before.status is not Status.OPEN:
            assert isinstance(result, BidRejected)

    @rule(dt=st.floats(0, 40, allow_nan=False))
    def advance(self, dt):
        self.now += dt

    @rule()
    def close(self):
        self.auction, _ = close_if_due(self.auction, self.now)

    @rule(actor=st.integers(0, 4), is_admin=st.booleans())
    def cancel_auction(self, actor, is_admin):
        self.auction, _ = cancel(self.auction, actor, is_admin, self.now)

    @invariant()
    def auction_is_consistent_and_terminal_states_stick(self):
        check_auction(self.auction)
        if self.auction.status is not Status.OPEN:
            if self.terminal is None:
                self.terminal = self.auction.status
            assert self.auction.status is self.terminal
        else:
            assert self.terminal is None


TestAuctionMachine = AuctionMachine.TestCase
