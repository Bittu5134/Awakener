"""Shared configuration file"""

import os
from pathlib import Path

TOKEN = os.getenv("DISCORD_TOKEN", "")

INVITE_URL = "https://discord.com/oauth2/authorize?client_id=1561603393192067153"
PATREON_URL = "https://www.patreon.com/c/LazyBittu"
HELP_URL = "https://github.com/Bittu5134/Awakener"
WEBSITE_URL = "https://github.com/Bittu5134/Awakener"
# For Developement only, it will only register commands for this server if set.
GUILD_ID = os.getenv("GUILD_ID")
GUILD_ID = int(GUILD_ID) if GUILD_ID else None

DB_PATH = Path(os.getenv("DB_PATH", "awakener.db"))

# Cooldown limits:
MIN_COOLDOWN_MINS = 5
MAX_COOLDOWN_MINS = 360
MIN_COOLDOWN_SECS = MIN_COOLDOWN_MINS * 60
MAX_COOLDOWN_SECS = MAX_COOLDOWN_MINS * 60
# DEFAULT_COOLDOWN_SECS = 5
DEFAULT_COOLDOWN_SECS = 10

DEFAULT_PERKS_MESSAGE = "No perks have been configured by the admins yet."
PERKS_MAX_LENGTH = 1800


def format_cooldown(seconds: int) -> str:
    """Human-readable cooldown, minute-granular when possible."""
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"{seconds} second{'s' if seconds != 1 else ''}"
