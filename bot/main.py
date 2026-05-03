"""
Main bot application
"""
import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Dispatcher, Bot, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import BotCommand

from bot.config.settings import load_env, get_settings
from bot.handlers import start_router, phone_router
from bot.middlewares import LoggingMiddleware


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def build_session(settings) -> AiohttpSession:
    """Build aiohttp session with optional proxy and longer timeout.

    Russia-hosted servers often have flaky access to api.telegram.org.
    A proxy outside RU plus a generous request timeout keeps polling alive.
    """
    timeout = max(int(settings.BOT_REQUEST_TIMEOUT), settings.BOT_POLLING_TIMEOUT + 10)
    proxy = settings.BOT_PROXY_URL.strip() if settings.BOT_PROXY_URL else None

    if proxy:
        logger.info(f"Using proxy for Telegram API (timeout={timeout}s)")
        return AiohttpSession(proxy=proxy, timeout=timeout)
    logger.info(f"Direct connection to Telegram API (timeout={timeout}s)")
    return AiohttpSession(timeout=timeout)


async def set_bot_commands(bot: Bot):
    """Set bot commands"""
    commands = [
        BotCommand(command="start", description="Botni boshlash"),
        BotCommand(command="help", description="Yordam"),
    ]
    await bot.set_my_commands(commands)
    logger.info("Bot commands set successfully")


def build_dispatcher() -> Dispatcher:
    """Build the dispatcher once. Routers can only be attached to a single
    parent, so reuse this dispatcher across reconnect attempts."""
    dp = Dispatcher()
    dp.message.middleware(LoggingMiddleware())
    dp.include_router(start_router)
    dp.include_router(phone_router)
    return dp


async def run_polling(settings, dp: Dispatcher) -> None:
    bot = Bot(token=settings.BOT_TOKEN, session=build_session(settings))

    try:
        await set_bot_commands(bot)
    except Exception as e:
        # Don't crash on slow first network round-trip; commands can be set later
        logger.warning(f"set_my_commands failed (will continue): {e}")

    logger.info("Bot is running... (polling mode)")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            polling_timeout=settings.BOT_POLLING_TIMEOUT,
        )
    finally:
        await bot.session.close()


async def main():
    """Main function with reconnect loop for unstable networks."""
    try:
        load_env()
        settings = get_settings()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        logger.error("Please set up .env file first:")
        logger.error("  1. cp .env.example .env")
        logger.error("  2. Edit .env and add BOT_TOKEN")
        logger.error("  3. Get token from @BotFather on Telegram")
        sys.exit(1)

    logger.info("Starting Savdo Bot...")

    dp = build_dispatcher()

    backoff = 5
    while True:
        try:
            await run_polling(settings, dp)
            return  # graceful stop
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            logger.error(f"Polling crashed: {e}. Reconnecting in {backoff}s...", exc_info=True)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
