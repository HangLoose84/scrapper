"""Entrypoint: python main.py"""
import asyncio
import logging
import sys

import bot_ui
import notifier
import storage
from config import settings
from core.engine import run

log = logging.getLogger(__name__)


async def main() -> None:
    await storage.init()
    n = len(await storage.get_all_targets())
    hello = f"🚀 Deal Hunter Bot iniciado. Monitoreando {n} targets..."
    log.info("%s cada %ds, alertando bajo -%.0f%%",
             hello, settings.poll_seconds, settings.drop_threshold * 100)
    await notifier.send(hello)

    if notifier.bot is None:
        log.warning("sin TELEGRAM_TOKEN: corre el monitor, sin /menu")
        await run()
        return
    if not settings.telegram_owner_id:
        log.warning("sin TELEGRAM_OWNER_ID: /menu va a ignorar a todo el mundo")

    try:
        # Polling and the price loop are independent; either crashing stops both,
        # which is what we want -- a half-running bot is worse than a dead one.
        await asyncio.gather(bot_ui.dp.start_polling(notifier.bot), run())
    finally:
        await notifier.bot.session.close()


if __name__ == "__main__":
    # Windows console defaults to cp1252; logging writes to stderr, so do both.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(
        stream=sys.stdout,  # stderr is for crashes; the supervisor logs both
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
