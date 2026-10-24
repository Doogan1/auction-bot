import random

import pytest

from auctionbot.core.models import Status
from auctionbot.core.results import BidAccepted, BidRejected, RejectReason
from auctionbot.sim.runner import run_simulation
from auctionbot.sim.strategies import (
    BiddingWar,
    Chaos,
    Incrementer,
    Simultaneous,
    Sniper,
)
from conftest import make_auction


def test_same_seed_same_result():
    def run():
        return run_simulation(
            make_auction(), [Chaos(-1), Chaos(-2), Incrementer(-3, ceiling=200)], random.Random(42)
        )

    assert run() == run()


def test_different_seed_can_differ():
    def run(seed):
        return run_simulation(make_auction(), [Chaos(-1), Chaos(-2)], random.Random(seed))

    assert run(1).events != run(2).events


def test_incrementer_pair_ends_closed_with_higher_ceiling_winning():
    result = run_simulation(
        make_auction(),
        [Incrementer(-1, ceiling=50), Incrementer(-2, ceiling=80)],
        random.Random(7),
    )
    assert result.auction.status is Status.CLOSED
    assert result.auction.winning_bid().bidder_id == -2


def test_sniper_bids_inside_final_seconds_and_extends():
    result = run_simulation(
        make_auction(),
        [Sniper(-1, lead_s=5, ceiling=100), Incrementer(-2, ceiling=20)],
        random.Random(3),
    )
    sniper_events = [e for e in result.events if e.bidder_id == -1]
    assert sniper_events[0].at == 995.0
    assert isinstance(sniper_events[0].result, BidAccepted)
    assert sniper_events[0].result.extended is True
    assert result.auction.ends_at >= 1025.0
    assert result.auction.winning_bid().bidder_id == -1


def test_bidding_war_terminates_within_cap():
    auction = make_auction(ends_at=60.0)
    result = run_simulation(
        auction,
        [BiddingWar(-1, ceiling=10**9), BiddingWar(-2, ceiling=10**9)],
        random.Random(11),
    )
    assert result.auction.status is Status.CLOSED
    assert result.auction.extensions_used == result.auction.config.max_extensions


@pytest.mark.parametrize("seed", range(20))
def test_chaos_never_violates_invariants(seed):
    result = run_simulation(
        make_auction(),
        [Chaos(-1), Chaos(-2), Incrementer(-3, ceiling=500)],
        random.Random(seed),
    )
    assert result.auction.status is Status.CLOSED


def test_simultaneous_first_by_bidder_id_wins():
    bidders = [Simultaneous(-i, at=100.0, ceiling=1000) for i in range(1, 6)]
    result = run_simulation(make_auction(), bidders, random.Random(0))
    assert [e.at for e in result.events] == [100.0] * 5
    assert [e.bidder_id for e in result.events] == [-5, -4, -3, -2, -1]
    assert isinstance(result.events[0].result, BidAccepted)
    assert all(
        e.result == BidRejected(RejectReason.BELOW_MINIMUM) for e in result.events[1:]
    )
    assert result.auction.winning_bid().bidder_id == -5


def test_max_steps_guard_raises():
    with pytest.raises(RuntimeError):
        run_simulation(
            make_auction(),
            [BiddingWar(-1, ceiling=10**12), BiddingWar(-2, ceiling=10**12)],
            random.Random(0),
            max_steps=5,
        )
