import math
from collections.abc import Sequence
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from auctionbot.bot.actions import NO_MENTIONS, NOT_FOUND_MESSAGE, get_in_guild, perform_bid
from auctionbot.bot.parsing import parse_amount, parse_duration
from auctionbot.bot.render import (
    auction_choice_label,
    auction_embed,
    cancel_reject_message,
)
from auctionbot.core.models import Auction, AuctionConfig
from auctionbot.core.results import CancelRejected
from auctionbot.core.rules import MAX_AMOUNT
from auctionbot.service import AuctionNotFound

if TYPE_CHECKING:
    from auctionbot.bot.client import AuctionBot

MAX_CHOICES = 25
MAX_LISTED = 20


def autocomplete_choices(auctions: Sequence[Auction], current: str) -> list[app_commands.Choice[int]]:
    needle = current.strip().lower()
    matches = [a for a in auctions if needle in f"#{a.id} {a.title}".lower()]
    return [
        app_commands.Choice(name=auction_choice_label(a), value=a.id)
        for a in matches[:MAX_CHOICES]
    ]


def register(bot: "AuctionBot") -> None:
    service = bot.service

    @bot.tree.command(name="ping", description="Check that the bot is alive")
    async def ping(interaction: discord.Interaction) -> None:
        latency = bot.latency  # nan before the first heartbeat
        suffix = f" {round(latency * 1000)}ms" if math.isfinite(latency) else ""
        await interaction.response.send_message(f"Pong!{suffix}", ephemeral=True)

    async def auction_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[int]]:
        return autocomplete_choices(await service.list_open(interaction.guild_id), current)

    group = app_commands.Group(
        name="auction", description="Run and inspect auctions", guild_only=True
    )

    @group.command(name="start", description="Start a new auction in this channel")
    @app_commands.describe(
        title="What is being auctioned",
        starting_bid="Opening bid (whole number)",
        duration="How long it runs, e.g. 90s, 10m, 1h30m, 2d",
        min_increment="Smallest allowed raise (default 1)",
        description="Optional extra details",
    )
    async def start(
        interaction: discord.Interaction,
        title: str,
        starting_bid: app_commands.Range[int, 1, MAX_AMOUNT],
        duration: str,
        min_increment: app_commands.Range[int, 1, MAX_AMOUNT] = 1,
        description: str = "",
    ) -> None:
        try:
            auction = await service.create_auction(
                guild_id=interaction.guild_id,
                channel_id=interaction.channel_id,
                seller_id=interaction.user.id,
                title=title,
                starting_bid=starting_bid,
                duration_s=parse_duration(duration),
                config=AuctionConfig(min_increment=min_increment),
                description=description,
            )
        except ValueError as err:
            await interaction.response.send_message(str(err), ephemeral=True)
            return
        await interaction.response.send_message(
            embed=auction_embed(auction), allowed_mentions=NO_MENTIONS
        )
        message = await interaction.original_response()
        await service.set_message_id(auction.id, message.id)

    @group.command(name="status", description="Show an auction (default: the newest open one)")
    @app_commands.describe(auction="Which auction")
    @app_commands.autocomplete(auction=auction_autocomplete)
    async def status(interaction: discord.Interaction, auction: int | None = None) -> None:
        try:
            if auction is None:
                open_auctions = await service.list_open(interaction.guild_id)
                if not open_auctions:
                    await interaction.response.send_message("No open auctions.", ephemeral=True)
                    return
                found = max(open_auctions, key=lambda a: a.id)
            else:
                found = await get_in_guild(service, auction, interaction.guild_id)
        except AuctionNotFound:
            await interaction.response.send_message(NOT_FOUND_MESSAGE, ephemeral=True)
            return
        await interaction.response.send_message(embed=auction_embed(found), ephemeral=True)

    @group.command(name="list", description="List open auctions in this server")
    async def list_auctions(interaction: discord.Interaction) -> None:
        open_auctions = await service.list_open(interaction.guild_id)
        if not open_auctions:
            await interaction.response.send_message("No open auctions.", ephemeral=True)
            return
        lines = [auction_choice_label(a) for a in open_auctions[:MAX_LISTED]]
        if len(open_auctions) > MAX_LISTED:
            lines.append(f"...and {len(open_auctions) - MAX_LISTED} more")
        await interaction.response.send_message(
            "\n".join(lines), ephemeral=True, allowed_mentions=NO_MENTIONS
        )

    @group.command(name="cancel", description="Cancel an auction (seller or admin)")
    @app_commands.describe(auction="Which auction")
    @app_commands.autocomplete(auction=auction_autocomplete)
    async def cancel(interaction: discord.Interaction, auction: int) -> None:
        try:
            await get_in_guild(service, auction, interaction.guild_id)
            result = await service.cancel(
                auction, interaction.user.id, interaction.user.guild_permissions.administrator
            )
        except AuctionNotFound:
            await interaction.response.send_message(NOT_FOUND_MESSAGE, ephemeral=True)
            return
        if isinstance(result, CancelRejected):
            await interaction.response.send_message(
                cancel_reject_message(result.reason), ephemeral=True
            )
            return
        await interaction.response.send_message("Auction cancelled.", ephemeral=True)

    bot.tree.add_command(group)

    @bot.tree.command(name="bid", description="Place a bid on an auction")
    @app_commands.guild_only()
    @app_commands.describe(auction="Which auction", amount="Your bid (whole number)")
    @app_commands.autocomplete(auction=auction_autocomplete)
    async def bid(interaction: discord.Interaction, auction: int, amount: str) -> None:
        try:
            value = parse_amount(amount)
        except ValueError as err:
            await interaction.response.send_message(str(err), ephemeral=True)
            return
        await perform_bid(interaction, auction, value)
