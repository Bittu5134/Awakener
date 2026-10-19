"""Awakener — multi-server Discord bot backed by SQLite."""

import logging

from scripts.bot import AwakenerBot
from scripts.config import TOKEN


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set. Add it to .env or the environment.")

    AwakenerBot().run(TOKEN)


if __name__ == "__main__":
    main()
