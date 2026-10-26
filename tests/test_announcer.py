import discord
import pytest

from auctionbot.bot.client import DiscordAnnouncer
from auctionbot.bot.scheduler import Unannounceable
from auctionbot.core.models import Status
from auctionbot.storage.repository import AuctionRef
from conftest import make_auction
from test_discord_errors import http_error

REF = AuctionRef(guild_id=1, channel_id=10, message_id=99)


class FakeMessage:
    def __init__(self, edit_error=None):
        self.edit_error = edit_error
        self.edits = 0

    async def edit(self, **kwargs):
        self.edits += 1
        if self.edit_error:
            raise self.edit_error

    def to_reference(self, **kwargs):
        return "reference"


class FakeChannel:
    def __init__(self, message, send_error=None):
        self.message = message
        self.send_error = send_error
        self.sent = []

    def get_partial_message(self, message_id):
        return self.message

    async def send(self, text, **kwargs):
        if self.send_error:
            raise self.send_error
        self.sent.append(text)


class FakeBot:
    def __init__(self, channel):
        self.channel = channel

    def get_partial_messageable(self, channel_id):
        return self.channel


def announcer_for(message, send_error=None):
    channel = FakeChannel(message, send_error)
    return DiscordAnnouncer(FakeBot(channel)), channel


CLOSED = make_auction(status=Status.CLOSED)


async def test_happy_path_edits_then_posts():
    message = FakeMessage()
    announcer, channel = announcer_for(message)
    await announcer.announce(CLOSED, REF)
    assert message.edits == 1 and len(channel.sent) == 1


async def test_forbidden_edit_does_not_stop_the_channel_post():
    announcer, channel = announcer_for(FakeMessage(edit_error=http_error(403)))
    await announcer.announce(CLOSED, REF)
    assert len(channel.sent) == 1


async def test_transient_edit_error_propagates_for_retry():
    announcer, channel = announcer_for(FakeMessage(edit_error=http_error(503)))
    with pytest.raises(discord.HTTPException):
        await announcer.announce(CLOSED, REF)
    assert channel.sent == []


@pytest.mark.parametrize("status", [400, 403, 404])
async def test_permanent_send_errors_become_unannounceable(status):
    announcer, _ = announcer_for(FakeMessage(), send_error=http_error(status))
    with pytest.raises(Unannounceable):
        await announcer.announce(CLOSED, REF)


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_transient_send_errors_propagate_for_retry(status):
    announcer, _ = announcer_for(FakeMessage(), send_error=http_error(status))
    with pytest.raises(discord.HTTPException):
        await announcer.announce(CLOSED, REF)
