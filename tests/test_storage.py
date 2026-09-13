"""Target CRUD against a throwaway SQLite file. python tests/test_storage.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # importar el proyecto

import asyncio
import os
import pathlib

DB = str(Path(__file__).parent / "test_storage.db")
os.environ["DB_URL"] = f"sqlite+aiosqlite:///{DB}"
pathlib.Path(DB).unlink(missing_ok=True)

import storage  # noqa: E402
from config import Target  # noqa: E402

JSON_T = Target(name="api", url="https://x.cl/p.json", json_path="data.price")
HTML_T = Target(name="web", url="https://x.cl/p", css_selector="span.price", css_attribute="data-value")


async def test_crud():
    assert await storage.get_all_targets() == []

    await storage.add_target(JSON_T)
    await storage.add_target(HTML_T)
    names = [t.name for t in await storage.get_all_targets()]
    assert names == ["api", "web"], names  # ordered by name

    stored = {t.name: t for t in await storage.get_all_targets()}
    assert stored["api"] == JSON_T  # round-trips through SQLite unchanged
    assert stored["web"] == HTML_T
    assert stored["api"].css_selector is None
    assert stored["web"].css_attribute == "data-value"


async def test_add_is_upsert():
    moved = Target(name="web", url="https://x.cl/OTRA", css_selector="div.p")
    await storage.add_target(moved)
    stored = {t.name: t for t in await storage.get_all_targets()}
    assert len(stored) == 2, stored  # replaced, not duplicated
    assert stored["web"].url.endswith("/OTRA")
    assert stored["web"].css_attribute is None  # old attribute cleared, not left behind


async def test_delete():
    assert await storage.delete_target("web") is True
    assert [t.name for t in await storage.get_all_targets()] == ["api"]
    assert await storage.delete_target("web") is False  # already gone
    assert await storage.delete_target("nunca-existio") is False


async def test_validator_still_guards():
    """The model refuses a broken target before storage ever sees it."""
    for bad in [{}, {"json_path": "a", "css_selector": ".p"}]:
        try:
            Target(name="bad", url="u", **bad)
            raise AssertionError(f"should have rejected {bad}")
        except ValueError as e:
            assert "exactly one" in str(e), e


async def main():
    await storage.init()
    await test_crud()
    await test_add_is_upsert()
    await test_delete()
    await test_validator_still_guards()
    await storage.engine.dispose()
    pathlib.Path(DB).unlink(missing_ok=True)
    print("ok")


if __name__ == "__main__":
    asyncio.run(main())
