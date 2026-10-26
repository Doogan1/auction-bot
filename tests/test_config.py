import pytest

from auctionbot.config import ConfigError, Settings, load_settings


def test_loads_all_values():
    env = {"DISCORD_TOKEN": "t", "DEV_GUILD_ID": "123", "DB_PATH": "x.db"}
    assert load_settings(env) == Settings("t", 123, "x.db")


def test_db_path_defaults_to_auctions_db():
    assert load_settings({"DISCORD_TOKEN": "t"}).db_path == "auctions.db"


def test_blank_dev_guild_is_none():
    assert load_settings({"DISCORD_TOKEN": "t", "DEV_GUILD_ID": "  "}).dev_guild_id is None


def test_missing_token_raises_with_hint():
    with pytest.raises(ConfigError) as err:
        load_settings({})
    assert "DISCORD_TOKEN" in str(err.value) and ".env" in str(err.value)


def test_blank_token_raises():
    with pytest.raises(ConfigError):
        load_settings({"DISCORD_TOKEN": "   "})


def test_non_integer_guild_raises_config_error():
    with pytest.raises(ConfigError):
        load_settings({"DISCORD_TOKEN": "t", "DEV_GUILD_ID": "abc"})


def test_error_message_never_contains_token():
    with pytest.raises(ConfigError) as err:
        load_settings({"DISCORD_TOKEN": "SECRET", "DEV_GUILD_ID": "abc"})
    assert "SECRET" not in str(err.value)
