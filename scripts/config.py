"""Shared configuration loaded from .env / environment variables."""

import os
from pathlib import Path


def load_env_file(path: Path = Path(".env")) -> None:
    """Load simple KEY=VALUE pairs from .env without extra dependencies."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


load_env_file()

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

# Optional link buttons on the status view; hidden when blank.
INVITE_URL = os.getenv("INVITE_URL", "").strip()
PATREON_URL = os.getenv("PATREON_URL", "").strip()
HELP_URL = os.getenv("HELP_URL", "https://github.com/Bittu5134/Awakener").strip()

# Optional: set for instant guild-scoped slash-command sync during development.
_sync_guild = os.getenv("GUILD_ID", "").strip()
GUILD_ID = int(_sync_guild) if _sync_guild.isdigit() else None

DB_PATH = Path(os.getenv("DB_PATH", "awakener.db"))

# Cooldown limits: admins configure minutes, we store seconds internally.
MIN_COOLDOWN_MINS = 5
MAX_COOLDOWN_MINS = 360  # 6 hours
MIN_COOLDOWN_SECS = MIN_COOLDOWN_MINS * 60
MAX_COOLDOWN_SECS = MAX_COOLDOWN_MINS * 60
DEFAULT_COOLDOWN_SECS = 10  # short default while the bot is being tested

DEFAULT_PERKS_MESSAGE = "No perks have been configured by the admins yet."
PERKS_MAX_LENGTH = 1800


def secs_to_mins(seconds: int) -> int:
    return seconds // 60


def format_cooldown(seconds: int) -> str:
    """Human-readable cooldown, minute-granular when possible."""
    if seconds % 60 == 0:
        minutes = secs_to_mins(seconds)
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"{seconds} second{'s' if seconds != 1 else ''}"
