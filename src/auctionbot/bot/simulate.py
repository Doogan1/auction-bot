import asyncio
import logging
import random

import discord

from auctionbot.bot.actions import NO_MENTIONS, discard_auction, reply_ephemeral
from auctionbot.bot.render import auction_embed, bid_announcement
from auctionbot.bot.views import auction_view
from auctionbot.clock import SystemClock
from auctionbot.core.models import Auction, AuctionConfig
from auctionbot.core.results import BidAccepted
from auctionbot.sim.live import run_live
from auctionbot.sim.strategies import Chaos, Incrementer, Sniper, Strategy

log = logging.getLogger(__name__)

SIM_DURATION_S = 30
SIM_STARTING_BID = 10
SIM_CONFIG = AuctionConfig(min_increment=5, anti_snipe_window_s=5, extension_s=5, max_extensions=3)


def sim_bidders() -> list[Strategy]:
    """Fake bidders. Negative ids never collide with real Discord ids."""
    return [
        Incrementer(-1, ceiling=200),
        Incrementer(-2, ceiling=300),
        Sniper(-3, lead_s=3, ceiling=400),
        Chaos(-4),
    ]


class SimulationRegistry:
    """Tracks the one running simulation per guild. A slot is claimed before any await,
    so two concurrent /simulate calls cannot both start."""

    def __init__(self) -> None:
        self._slots: dict[int, asyncio.Task | None] = {}

    def try_claim(self, guild_id: int) -> bool:
        if guild_id in self._slots:
            return False
        self._slots[guild_id] = None
        return True

    def attach(self, guild_id: int, task: asyncio.Task) -> None:
        self._slots[guild_id] = task

    def release(self, guild_id: int, task: asyncio.Task | None = None) -> None:
        """Free the slot; if `task` is given, only when it is the task holding the slot."""
        if task is None or self._slots.get(guild_id) is task:
            self._slots.pop(guild_id, None)

    async def cancel_all(self) -> None:
        tasks = [t for t in self._slots.values() if t is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def start_simulation(interaction: discord.Interaction) -> None:
    """Admin demo: a 30-second auction bid on by clearly labeled simulated bidders."""
    bot = interaction.client
    guild_id = interaction.guild_id
    if not interaction.user.guild_permissions.administrator:
        await reply_ephemeral(interaction, "Only server admins can run a simulation.")
        return
    if not bot.simulations.try_claim(guild_id):
        await reply_ephemeral(interaction, "A simulation is already running in this server.")
        return
    try:
        auction = await bot.service.create_auction(
            guild_id=guild_id,
            channel_id=interaction.channel_id,
            seller_id=interaction.user.id,
            title="Simulated auction",
            starting_bid=SIM_STARTING_BID,
            duration_s=SIM_DURATION_S,
            config=SIM_CONFIG,
            description="Demo: the bidders here are simulated (SimBidder-N), not real people.",
        )
        try:
            await interaction.response.send_message(
                embed=auction_embed(auction), view=auction_view(auction), allowed_mentions=NO_MENTIONS
            )
            message = await interaction.original_response()
            await bot.service.set_message_id(auction.id, message.id)
        except Exception:
            await discard_auction(bot.service, auction)
            raise

        channel = bot.get_partial_messageable(interaction.channel_id)

        async def on_accepted(
            after: Auction, bidder_id: int, amount: int, result: BidAccepted
        ) -> None:
            text = bid_announcement(
                after, bidder_id, amount, result.extended, after.config.anti_snipe_window_s
            )
            try:
                await channel.send(text, allowed_mentions=NO_MENTIONS)
            except discord.HTTPException:
                log.exception("Could not announce simulated bid")
            bot.refresher.request(after.id)

        task = asyncio.create_task(
            run_live(
                bot.service, auction.id, sim_bidders(), random.Random(), SystemClock(), on_accepted
            )
        )
        bot.simulations.attach(guild_id, task)
    except BaseException:
        bot.simulations.release(guild_id)
        raise

    def finished(done: asyncio.Task) -> None:
        bot.simulations.release(guild_id, done)
        if not done.cancelled() and done.exception() is not None:
            log.error("Simulation failed", exc_info=done.exception())

    task.add_done_callback(finished)
