import discord

from auctionbot.bot.render import bid_announcement, reject_message
from auctionbot.core.models import Auction
from auctionbot.core.results import BidRejected
from auctionbot.service import AuctionNotFound, AuctionService

NO_MENTIONS = discord.AllowedMentions.none()
NOT_FOUND_MESSAGE = "That auction doesn't exist (or it belongs to another server)."


async def get_in_guild(service: AuctionService, auction_id: int, guild_id: int) -> Auction:
    """Load an auction, treating ones from other servers as nonexistent (ids are global)."""
    ref = await service.get_ref(auction_id)
    if ref.guild_id != guild_id:
        raise AuctionNotFound(auction_id)
    return await service.get(auction_id)


async def perform_bid(interaction: discord.Interaction, auction_id: int, amount: int) -> None:
    """Place a bid for the interacting user: ephemeral on rejection, public on success."""
    bot = interaction.client  # an AuctionBot; typed loosely to avoid an import cycle
    try:
        await get_in_guild(bot.service, auction_id, interaction.guild_id)
        result = await bot.service.place_bid(auction_id, interaction.user.id, amount)
        auction = await bot.service.get(auction_id)
    except AuctionNotFound:
        await interaction.response.send_message(NOT_FOUND_MESSAGE, ephemeral=True)
        return
    if isinstance(result, BidRejected):
        await interaction.response.send_message(
            reject_message(result.reason, auction), ephemeral=True
        )
        return
    await interaction.response.send_message(
        bid_announcement(
            auction, interaction.user.id, amount, result.extended, auction.config.anti_snipe_window_s
        ),
        allowed_mentions=NO_MENTIONS,
    )
    bot.refresher.request(auction_id)
