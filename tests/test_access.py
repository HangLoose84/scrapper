"""The owner-only filter. python tests/test_access.py

No Telegram mocking: the router-level filters are plain predicates, so we feed
them a stub event and check who gets through.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # importar el proyecto

import asyncio
import os
from types import SimpleNamespace

OWNER = 1111
os.environ["TELEGRAM_OWNER_ID"] = str(OWNER)
os.environ["DB_URL"] = "sqlite+aiosqlite:///test_access.db"

import bot_ui  # noqa: E402


def event(user_id: int) -> SimpleNamespace:
    return SimpleNamespace(from_user=SimpleNamespace(id=user_id), data="list", text="/menu")


async def allowed(observer, user_id: int) -> bool:
    ok, _ = await observer.check_root_filters(event(user_id))
    return bool(ok)


async def main():
    for observer, label in [(bot_ui.router.message, "message"),
                            (bot_ui.router.callback_query, "callback")]:
        assert observer._handler.filters, f"{label}: sin filtro de acceso!"
        assert await allowed(observer, OWNER) is True, label
        assert await allowed(observer, OWNER + 1) is False, label  # otro usuario
        assert await allowed(observer, 0) is False, label
        assert await allowed(observer, -OWNER) is False, label
    print("ok")


if __name__ == "__main__":
    asyncio.run(main())
