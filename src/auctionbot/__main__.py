import asyncio
import logging
import os
import sys

from dotenv import find_dotenv, load_dotenv

from auctionbot.bot.client import AuctionBot
from auctionbot.clock import SystemClock
from auctionbot.config import ConfigError, Settings, load_settings
from auctionbot.service import AuctionService
from auctionbot.storage.repository import Repository


async def run(settings: Settings) -> None:
    repo = await Repository.open(settings.db_path)
    try:
        service = AuctionService(repo, SystemClock())
        async with AuctionBot(settings, service) as bot:
            await bot.start(settings.token)
    finally:
        await repo.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv(find_dotenv(usecwd=True))  # search from the working directory, not this file
    try:
        settings = load_settings(os.environ)
    except ConfigError as err:
        print(err, file=sys.stderr)
        return 1
    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
