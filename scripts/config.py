import os
from pathlib import Path


def _load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "")

INVITE_URL = "https://discord.com/oauth2/authorize?client_id=1561603393192067153&permissions=268504064&integration_type=0&scope=bot+applications.commands"
PATREON_URL = "https://www.patreon.com/c/LazyBittu"
HELP_URL = "https://github.com/Bittu5134/Awakener"
WEBSITE_URL = "https://github.com/Bittu5134/Awakener"

# For Developement only, it will only register commands for this server if set.
GUILD_ID = os.getenv("GUILD_ID")
GUILD_ID = int(GUILD_ID) if GUILD_ID else None

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = BASE_DIR / "awakener.db"
LEADERBOARD_DB_PATH = BASE_DIR / "leaderboard.db"

# Optional: Discord webhook that receives guild join/leave logs.
LOG_WEBHOOK_URL = os.getenv("LOG_WEBHOOK_URL", "")

MIN_COOLDOWN_MINS = 1
MAX_COOLDOWN_MINS = 360
DEFAULT_COOLDOWN_SECS = 5 * 60

DEFAULT_PERKS_MESSAGE = "Use `/config` to add more perks here!"
PERKS_MAX_LENGTH = 1800


def format_cooldown(seconds: int) -> str:
    """Human-readable cooldown, minute-granular when possible."""
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"{seconds} second{'s' if seconds != 1 else ''}"
