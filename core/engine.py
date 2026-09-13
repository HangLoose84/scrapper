import asyncio
import logging

import aiohttp

import notifier
import scraper
import storage
from config import Target, settings
from core.anomaly import drop_ratio

log = logging.getLogger(__name__)


async def check(session: aiohttp.ClientSession, target: Target) -> None:
    try:
        price = await scraper.fetch_price(session, target)
    except Exception as e:  # one bad target must not kill the loop
        log.warning("%s: fetch failed: %s", target.name, e)
        return

    past = await storage.history(target.name, settings.history_size)
    await storage.record(target.name, price)
    drop = drop_ratio(price, past)
    log.info("%s: %.2f (%.1f%% below baseline)", target.name, price, drop * 100)

    # Edge-triggered, and the edge lives in SQLite so a restart does not re-alert.
    alerted_at = await storage.get_alert(target.name)
    if drop >= settings.drop_threshold:
        if alerted_at != price:  # first drop, or it fell further
            await storage.set_alert(target.name, price)
            await notifier.send(
                f"⚠️ {target.name}: {price:.2f} - {drop * 100:.1f}% below usual\n{target.url}",
            )
    elif alerted_at is not None:
        log.info("%s: recovered, alert state cleared", target.name)
        await storage.set_alert(target.name, None)


async def run(once: bool = False) -> None:
    async with aiohttp.ClientSession() as session:
        while True:
            # Re-read every cycle so targets added from /menu are picked up live.
            targets = await storage.get_all_targets()
            await asyncio.gather(*(check(session, t) for t in targets))
            if once:
                return
            await asyncio.sleep(settings.poll_seconds)

