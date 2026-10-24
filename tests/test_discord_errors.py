import discord
import pytest

from auctionbot.bot.errors import is_permanent


class StubResponse:
    def __init__(self, status):
        self.status = status
        self.reason = "stub"


def http_error(status):
    return discord.HTTPException(StubResponse(status), "boom")


@pytest.mark.parametrize("status", [400, 401, 403, 404, 405])
def test_client_errors_are_permanent(status):
    assert is_permanent(http_error(status)) is True


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503])
def test_rate_limits_timeouts_and_server_errors_are_transient(status):
    assert is_permanent(http_error(status)) is False
