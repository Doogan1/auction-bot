import os
import subprocess
import sys

from auctionbot.bot.client import AuctionBot, build_intents
from auctionbot.bot.commands import register
from auctionbot.config import Settings


def test_intents_have_no_privileged_flags():
    intents = build_intents()
    assert not intents.message_content
    assert not intents.members
    assert not intents.presences


def test_ping_command_registered_after_register():
    bot = AuctionBot(Settings("token", None, ":memory:"), service=None)
    register(bot)
    assert bot.tree.get_command("ping") is not None


def test_package_main_fails_fast_without_token(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "DISCORD_TOKEN"}
    result = subprocess.run(
        [sys.executable, "-m", "auctionbot"],
        cwd=tmp_path,  # no .env here
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1
    assert "DISCORD_TOKEN" in result.stdout + result.stderr
