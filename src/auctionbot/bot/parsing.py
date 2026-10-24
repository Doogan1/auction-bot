import re

MIN_DURATION_S = 10
MAX_DURATION_S = 7 * 86400
_DURATION = re.compile(r"(?:[0-9]{1,6}[smhd])+")
_DURATION_PART = re.compile(r"([0-9]{1,6})([smhd])")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_AMOUNT = re.compile(r"[0-9]{1,13}")


def parse_duration(text: str) -> int:
    """Parse e.g. '90s', '10m', '1h30m', '2d' into seconds (10 seconds to 7 days)."""
    cleaned = text.strip().lower()
    if not _DURATION.fullmatch(cleaned):
        raise ValueError("Duration must look like 90s, 10m, 1h30m or 2d.")
    total = sum(int(n) * _UNIT_SECONDS[unit] for n, unit in _DURATION_PART.findall(cleaned))
    if not MIN_DURATION_S <= total <= MAX_DURATION_S:
        raise ValueError("Duration must be between 10 seconds and 7 days.")
    return total


def parse_amount(text: str) -> int:
    """Parse a whole-number bid amount: digits only, positive, at most 13 digits."""
    cleaned = text.strip()
    if not _AMOUNT.fullmatch(cleaned) or int(cleaned) == 0:
        raise ValueError("Enter a whole number greater than zero, using digits only.")
    return int(cleaned)
