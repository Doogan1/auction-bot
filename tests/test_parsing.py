import pytest

from auctionbot.bot.parsing import parse_amount, parse_duration


@pytest.mark.parametrize(
    "text, seconds",
    [("90s", 90), ("10m", 600), ("1h30m", 5400), ("2d", 172800), (" 5m ", 300), ("10S", 10)],
)
def test_parse_duration_accepts(text, seconds):
    assert parse_duration(text) == seconds


@pytest.mark.parametrize(
    "text",
    ["", "0", "5", "-5m", "abc", "9s", "8d", "99999d", "1.5h", "5m5", "9" * 400 + "s"],
)
def test_parse_duration_rejects_with_a_message(text):
    with pytest.raises(ValueError) as err:
        parse_duration(text)
    assert str(err.value)


@pytest.mark.parametrize("text, amount", [("15", 15), (" 15 ", 15)])
def test_parse_amount_accepts(text, amount):
    assert parse_amount(text) == amount


@pytest.mark.parametrize("text", ["", "abc", "1e5", "10.5", "-3", "0", "1" * 14, "1,000"])
def test_parse_amount_rejects_with_a_message(text):
    with pytest.raises(ValueError) as err:
        parse_amount(text)
    assert str(err.value)
