import asyncio
import logging
import sys

from pydantic import ValidationError

from src.bot.app import App
from src.config.settings import Settings

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO)  # until the settings are read
    try:
        settings = Settings()  # pyright: ignore[reportCallIssue]
    except ValidationError as error:
        # Report env var names (BOT__TOKEN), which is what the user has to set.
        missing = ", ".join("__".join(map(str, e["loc"])).upper() for e in error.errors())
        logger.error("Invalid configuration, check these settings: %s", missing)
        return 1
    logging.getLogger().setLevel(settings.log_level)
    if not settings.bot.token.get_secret_value():
        logger.error("BOT__TOKEN is empty: set it in the environment or .env")
        return 1
    try:
        asyncio.run(App(settings).run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
