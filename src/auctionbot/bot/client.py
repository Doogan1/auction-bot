import logging

import discord
from discord import app_commands

from auctionbot.bot import commands
from auctionbot.bot.refresher import MessageRefresher
from auctionbot.bot.render import auction_embed
from auctionbot.clock import SystemClock
from auctionbot.config import Settings
from auctionbot.service import AuctionService

log = logging.getLogger(__name__)


def build_intents() -> discord.Intents:
    """Slash commands need no privileged intents (no message content, members or presences)."""
    return discord.Intents.default()


class AuctionBot(discord.Client):
    def __init__(self, settings: Settings, service: AuctionService) -> None:
        super().__init__(intents=build_intents())
        self.settings = settings
        self.service = service
        self.tree = app_commands.CommandTree(self)
        self.tree.error(self._on_tree_error)
        self.refresher = MessageRefresher(self.refresh_message, SystemClock())

    async def setup_hook(self) -> None:
        commands.register(self)
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
            embed=auction_embed(auction), allowed_mentions=discord.AllowedMentions.none()
        )

    async def close(self) -> None:
        await self.refresher.aclose()
        await super().close()

    async def on_ready(self) -> None:
        log.info("Logged in as %s", self.user)

    @staticmethod
    async def _on_tree_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        log.error("Unhandled error in command", exc_info=error)
        message = "Something went wrong. Please try again."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
