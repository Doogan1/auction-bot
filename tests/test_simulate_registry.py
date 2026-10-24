import asyncio

from auctionbot.bot.simulate import SimulationRegistry


def test_second_claim_for_the_same_guild_is_refused():
    registry = SimulationRegistry()
    assert registry.try_claim(1) is True
    assert registry.try_claim(1) is False
    assert registry.try_claim(2) is True


def test_release_without_a_task_frees_the_slot():
    registry = SimulationRegistry()
    registry.try_claim(1)
    registry.release(1)
    assert registry.try_claim(1) is True


async def test_release_by_a_different_task_keeps_the_current_one():
    registry = SimulationRegistry()
    current = asyncio.ensure_future(asyncio.sleep(10))
    other = asyncio.ensure_future(asyncio.sleep(10))
    registry.try_claim(1)
    registry.attach(1, current)
    registry.release(1, other)
    assert registry.try_claim(1) is False
    registry.release(1, current)
    assert registry.try_claim(1) is True
    current.cancel()
    other.cancel()


async def test_cancel_all_cancels_attached_tasks_and_ignores_bare_claims():
    registry = SimulationRegistry()
    task = asyncio.ensure_future(asyncio.sleep(10))
    registry.try_claim(1)
    registry.attach(1, task)
    registry.try_claim(2)  # claimed but no task yet
    await registry.cancel_all()
    assert task.cancelled()
