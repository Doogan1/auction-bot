from collections.abc import Mapping
from dataclasses import dataclass


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    token: str
    dev_guild_id: int | None
    db_path: str


def load_settings(env: Mapping[str, str]) -> Settings:
    token = env.get("DISCORD_TOKEN", "").strip()
    if not token:
        raise ConfigError(
            "DISCORD_TOKEN is not set. Copy .env.example to .env and fill in your bot token."
        )
    guild_text = env.get("DEV_GUILD_ID", "").strip()
    try:
        dev_guild_id = int(guild_text) if guild_text else None
    except ValueError:
        raise ConfigError("DEV_GUILD_ID must be an integer server id.") from None
    return Settings(token, dev_guild_id, env.get("DB_PATH", "").strip() or "auctions.db")
