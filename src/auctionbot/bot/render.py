import discord

from auctionbot.core.models import Auction, Status
from auctionbot.core.results import CancelRejectReason, RejectReason

_REJECT_MESSAGES = {
    RejectReason.AUCTION_CLOSED: "This auction has ended.",
    RejectReason.INVALID_AMOUNT: "That isn't a valid bid amount.",
    RejectReason.SELLER_CANNOT_BID: "You can't bid on your own auction.",
    RejectReason.ALREADY_HIGH_BIDDER: "You're already the high bidder.",
}
_CANCEL_REJECT_MESSAGES = {
    CancelRejectReason.NOT_OPEN: "That auction is no longer open.",
    CancelRejectReason.NOT_ALLOWED: "Only the seller or an admin can cancel this auction.",
}
CHOICE_LABEL_MAX = 100


def bidder_label(bidder_id: int) -> str:
    if bidder_id < 0:
        return f"SimBidder-{-bidder_id} (simulated)"
    return f"<@{bidder_id}>"


def format_amount(amount: int) -> str:
    return f"{amount:,}"


def _safe(title: str) -> str:
    """Titles are user input: neutralise @everyone/@here/<@id> in plain message text."""
    return discord.utils.escape_mentions(title)


def auction_embed(auction: Auction) -> discord.Embed:
    embed = discord.Embed(title=auction.title, description=auction.description or None)
    embed.set_footer(text=f"Auction #{auction.id}")
    ends = f"<t:{int(auction.ends_at)}:R>"
    winning = auction.winning_bid()
    if auction.status is Status.OPEN:
        embed.colour = discord.Colour.green()
        if auction.high_bid is None:
            embed.add_field(name="Current bid", value="No bids yet")
        else:
            embed.add_field(
                name="Current bid",
                value=f"{format_amount(auction.high_bid)} by {bidder_label(auction.high_bidder_id)}",
            )
        embed.add_field(name="Minimum next bid", value=format_amount(auction.minimum_next_bid))
        embed.add_field(name="Ends", value=ends)
    elif auction.status is Status.CLOSED:
        embed.colour = discord.Colour.dark_grey()
        if winning is None:
            embed.add_field(name="Result", value="No bids")
        else:
            embed.add_field(
                name="Winner",
                value=f"{bidder_label(winning.bidder_id)} with {format_amount(winning.amount)}",
            )
        embed.add_field(name="Ended", value=ends)
    else:
        embed.colour = discord.Colour.dark_red()
        embed.add_field(name="Result", value="Cancelled")
    return embed


def reject_message(reason: RejectReason, auction: Auction) -> str:
    if reason is RejectReason.BELOW_MINIMUM:
        return f"Your bid is too low. The minimum is {format_amount(auction.minimum_next_bid)}."
    return _REJECT_MESSAGES[reason]


def cancel_reject_message(reason: CancelRejectReason) -> str:
    return _CANCEL_REJECT_MESSAGES[reason]


def bid_announcement(
    auction: Auction, bidder_id: int, amount: int, extended: bool, window_s: int
) -> str:
    text = (
        f"{bidder_label(bidder_id)} bid **{format_amount(amount)}** "
        f"on **{_safe(auction.title)}** (#{auction.id})."
    )
    if extended:
        text += f"\nBid landed in the final {window_s} seconds. Deadline extended."
    return text


def closed_announcement(auction: Auction) -> str:
    winning = auction.winning_bid()
    title = f"🔨 **{_safe(auction.title)}** (#{auction.id})"
    if winning is None:
        return f"{title} has ended with no bids."
    return (
        f"{title} has ended! {bidder_label(winning.bidder_id)} won "
        f"with a bid of **{format_amount(winning.amount)}**."
    )


def cancelled_announcement(auction: Auction) -> str:
    return f"**{_safe(auction.title)}** (#{auction.id}) was cancelled."


def auction_choice_label(auction: Auction) -> str:
    amount = auction.high_bid if auction.high_bid is not None else auction.starting_bid
    label = f"#{auction.id} {auction.title} - {format_amount(amount)}"
    if len(label) > CHOICE_LABEL_MAX:
        label = label[: CHOICE_LABEL_MAX - 1] + "…"
    return label
