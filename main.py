import logging

from scripts.bot import bot
from scripts.config import TOKEN

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)

bot.run(TOKEN)
