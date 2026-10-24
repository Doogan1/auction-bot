import math
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from auctionbot.bot.client import AuctionBot


def register(bot: "AuctionBot") -> None:
    @bot.tree.command(name="ping", description="Check that the bot is alive")
    async def ping(interaction: discord.Interaction) -> None:
        latency = bot.latency  # nan before the first heartbeat
        suffix = f" {round(latency * 1000)}ms" if math.isfinite(latency) else ""
        await interaction.response.send_message(f"Pong!{suffix}", ephemeral=True)
