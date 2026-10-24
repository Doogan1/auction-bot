import logging
import re

import discord

from auctionbot.bot.actions import NOT_FOUND_MESSAGE, get_in_guild, perform_bid, reply_ephemeral
from auctionbot.bot.parsing import parse_amount
from auctionbot.core.models import Auction, Status
from auctionbot.service import AuctionNotFound

log = logging.getLogger(__name__)

ENDED_MESSAGE = "This auction has ended."


async def _report_error(interaction: discord.Interaction, error: Exception) -> None:
    log.error("Unhandled error in bid control", exc_info=error)
    await reply_ephemeral(interaction, "Something went wrong. Please try again.")


async def _open_auction(interaction: discord.Interaction, auction_id: int) -> Auction | None:
    """The auction if it exists in this server and is open; otherwise answer ephemerally."""
    try:
        auction = await get_in_guild(interaction.client.service, auction_id, interaction.guild_id)
    except AuctionNotFound:
        await interaction.response.send_message(NOT_FOUND_MESSAGE, ephemeral=True)
        return None
    if auction.status is not Status.OPEN:
        await interaction.response.send_message(ENDED_MESSAGE, ephemeral=True)
        return None
    return auction


class BidModal(discord.ui.Modal):
    amount = discord.ui.TextInput(
        label="Amount", placeholder="Whole number, e.g. 150", min_length=1, max_length=13
    )

    def __init__(self, auction_id: int) -> None:
        super().__init__(title="Place a bid")
        self.auction_id = auction_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            value = parse_amount(self.amount.value)
        except ValueError as err:
            await interaction.response.send_message(str(err), ephemeral=True)
            return
        await perform_bid(interaction, self.auction_id, value)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await _report_error(interaction, error)


class BidButton(discord.ui.DynamicItem[discord.ui.Button], template=r"auction:bid:(?P<id>[0-9]+)"):
    """Bids the minimum next bid. Works on any old message: the auction id lives in custom_id."""

    def __init__(self, auction_id: int, min_increment: int = 1, disabled: bool = False) -> None:
        super().__init__(
            discord.ui.Button(
                label=f"Bid +{min_increment}",
                style=discord.ButtonStyle.success,
                custom_id=f"auction:bid:{auction_id}",
                disabled=disabled,
            )
        )
        self.auction_id = auction_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> "BidButton":
        return cls(int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        auction = await _open_auction(interaction, self.auction_id)
        if auction is not None:
            await perform_bid(interaction, self.auction_id, auction.minimum_next_bid)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await _report_error(interaction, error)


class CustomBidButton(
    discord.ui.DynamicItem[discord.ui.Button], template=r"auction:custom:(?P<id>[0-9]+)"
):
    """Opens a modal to type a bid amount."""

    def __init__(self, auction_id: int, disabled: bool = False) -> None:
        super().__init__(
            discord.ui.Button(
                label="Custom bid",
                style=discord.ButtonStyle.primary,
                custom_id=f"auction:custom:{auction_id}",
                disabled=disabled,
            )
        )
        self.auction_id = auction_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> "CustomBidButton":
        return cls(int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if await _open_auction(interaction, self.auction_id) is not None:
            await interaction.response.send_modal(BidModal(self.auction_id))

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await _report_error(interaction, error)


def auction_view(auction: Auction, *, disabled: bool = False) -> discord.ui.View:
    """The bid buttons for an auction message; disabled once it is no longer open."""
    off = disabled or auction.status is not Status.OPEN
    view = discord.ui.View(timeout=None)
    view.add_item(BidButton(auction.id, auction.config.min_increment, disabled=off))
    view.add_item(CustomBidButton(auction.id, disabled=off))
    return view
