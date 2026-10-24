import discord


def is_permanent(err: discord.HTTPException) -> bool:
    """True if retrying the same request can never succeed (a 4xx other than timeout/rate limit)."""
    return 400 <= err.status < 500 and err.status not in (408, 429)
