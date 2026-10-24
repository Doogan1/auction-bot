import logging

import discord
from discord import app_commands
from discord.ext import tasks

from auctionbot.bot import commands
from auctionbot.bot.actions import reply_ephemeral
from auctionbot.bot.refresher import MessageRefresher
from auctionbot.bot.render import (
    auction_embed,
    cancelled_announcement,
    closed_announcement,
)
from auctionbot.bot.scheduler import Unannounceable, tick
from auctionbot.bot.views import BidButton, CustomBidButton, auction_view
from auctionbot.clock import SystemClock
from auctionbot.config import Settings
from auctionbot.core.models import Auction, Status
from auctionbot.service import AuctionService
from auctionbot.storage.repository import AuctionRef

log = logging.getLogger(__name__)


def build_intents() -> discord.Intents:
    """Slash commands need no privileged intents (no message content, members or presences)."""
    return discord.Intents.default()


class DiscordAnnouncer:
    """Posts final results: edits the auction message, then announces in the channel."""

    def __init__(self, bot: "AuctionBot") -> None:
        self._bot = bot

    async def announce(self, auction: Auction, ref: AuctionRef) -> None:
        text = (
            cancelled_announcement(auction)
            if auction.status is Status.CANCELLED
            else closed_announcement(auction)
        )
        none = discord.AllowedMentions.none()
        channel = self._bot.get_partial_messageable(ref.channel_id)
        try:
            reference = None
            if ref.message_id is not None:
                message = channel.get_partial_message(ref.message_id)
                try:
                    await message.edit(
                        embed=auction_embed(auction), view=auction_view(auction), allowed_mentions=none
                    )
                    reference = message.to_reference(fail_if_not_exists=False)
                except discord.NotFound:
                    pass  # the auction message was deleted; still announce the result
            await channel.send(text, reference=reference, allowed_mentions=none)
        except (discord.NotFound, discord.Forbidden) as err:
            raise Unannounceable(f"{type(err).__name__}: {err}") from err


class AuctionBot(discord.Client):
    def __init__(self, settings: Settings, service: AuctionService) -> None:
        super().__init__(intents=build_intents())
        self.settings = settings
        self.service = service
        self.tree = app_commands.CommandTree(self)
        self.tree.error(self._on_tree_error)
        self.refresher = MessageRefresher(self.refresh_message, SystemClock())
        self.announcer = DiscordAnnouncer(self)

    @tasks.loop(seconds=2)
    async def scheduler(self) -> None:
        try:
            await tick(self.service, self.announcer)
        except Exception:
            log.exception("Scheduler tick failed")  # keep the loop alive

    @scheduler.before_loop
    async def _before_scheduler(self) -> None:
        await self.wait_until_ready()

    async def setup_hook(self) -> None:
        commands.register(self)
        self.add_dynamic_items(BidButton, CustomBidButton)
        self.scheduler.start()
        if self.settings.dev_guild_id is None:
            log.warning("DEV_GUILD_ID is not set; slash commands were not synced")
            return
        guild = discord.Object(id=self.settings.dev_guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        log.info("Synced %d command(s) to guild %d", len(synced), guild.id)

    async def refresh_message(self, auction_id: int) -> None:
        """Re-render an auction's live message (called through the debouncing refresher)."""
        auction = await self.service.get(auction_id)
        ref = await self.service.get_ref(auction_id)
        if ref.message_id is None:
            return
        message = self.get_partial_messageable(ref.channel_id).get_partial_message(ref.message_id)
        await message.edit(
            embed=auction_embed(auction),
            view=auction_view(auction),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def close(self) -> None:
        self.scheduler.cancel()
        await self.refresher.aclose()
        await super().close()

    async def on_ready(self) -> None:
        log.info("Logged in as %s", self.user)

    @staticmethod
    async def _on_tree_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        log.error("Unhandled error in command", exc_info=error)
        await reply_ephemeral(interaction, "Something went wrong. Please try again.")
