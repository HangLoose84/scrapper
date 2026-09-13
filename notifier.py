import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from config import settings

log = logging.getLogger(__name__)

# One Bot for both the alerts and the /menu UI. None when no token is configured.
bot = Bot(token=settings.telegram_token) if settings.telegram_token else None


async def send(text: str) -> None:
    """Best effort: Telegram being down must never take the monitor down with it."""
    if bot is None:
        log.warning("telegram not configured; alert was: %s", text)
        return
    try:
        await bot.send_message(settings.telegram_chat_id, text)
    except TelegramAPIError as e:  # network errors included
        log.error("telegram: %s", e)
