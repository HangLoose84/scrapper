from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, String, UniqueConstraint, delete, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from config import Target, settings


class Base(DeclarativeBase):
    pass


class Price(Base):
    __tablename__ = "prices"
    # Dedup: one observation per target per second, so a re-run or an overlapping
    # tick is a no-op instead of a duplicate row.
    __table_args__ = (UniqueConstraint("target", "seen_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    target: Mapped[str] = mapped_column(String(100), index=True)
    price: Mapped[float] = mapped_column(Float)
    seen_at: Mapped[datetime] = mapped_column(DateTime)


class Alert(Base):
    """The price we last alerted on, one row per target while the drop holds.

    The row IS the edge: present means "already alerted at this price", and the
    engine deletes it once the price recovers, so a later drop alerts again.
    """

    __tablename__ = "alerts"

    target: Mapped[str] = mapped_column(String(100), primary_key=True)
    price: Mapped[float] = mapped_column(Float)
    at: Mapped[datetime] = mapped_column(DateTime)


class TargetRow(Base):
    """A watched target, editable from /menu. Mirrors the Target model 1:1."""

    __tablename__ = "targets"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    url: Mapped[str] = mapped_column(String(500))
    json_path: Mapped[str | None] = mapped_column(String(200))
    css_selector: Mapped[str | None] = mapped_column(String(200))
    css_attribute: Mapped[str | None] = mapped_column(String(100))


engine = create_async_engine(settings.db_url)
Session = async_sessionmaker(engine, expire_on_commit=False)


async def init() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def record(target: str, price: float) -> bool:
    """Store one observation. Returns False if this second was already recorded."""
    seen_at = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
    async with Session() as s:
        r = await s.execute(
            insert(Price)
            .values(target=target, price=price, seen_at=seen_at)
            .on_conflict_do_nothing()
        )
        await s.commit()
        return bool(r.rowcount)


async def history(target: str, limit: int) -> list[float]:
    """The `limit` most recent prices for `target`, oldest first."""
    async with Session() as s:
        rows = await s.execute(
            select(Price.price)
            .where(Price.target == target)
            .order_by(Price.seen_at.desc(), Price.id.desc())
            .limit(limit)
        )
        return list(rows.scalars())[::-1]


async def get_alert(target: str) -> float | None:
    """The price we alerted on, or None if this target is not in a drop."""
    async with Session() as s:
        return await s.scalar(select(Alert.price).where(Alert.target == target))


async def set_alert(target: str, price: float | None) -> None:
    """Record the alerted price, or clear it (price=None) once recovered."""
    async with Session() as s:
        if price is None:
            await s.execute(delete(Alert).where(Alert.target == target))
        else:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            stmt = insert(Alert).values(target=target, price=price, at=now)
            await s.execute(
                stmt.on_conflict_do_update(
                    index_elements=["target"], set_={"price": price, "at": now}
                )
            )
        await s.commit()


async def add_target(target: Target) -> None:
    """Insert or replace a target, keyed by name."""
    values = target.model_dump()
    async with Session() as s:
        stmt = insert(TargetRow).values(**values)
        await s.execute(
            stmt.on_conflict_do_update(
                index_elements=["name"],
                set_={k: v for k, v in values.items() if k != "name"},
            )
        )
        await s.commit()


async def delete_target(name: str) -> bool:
    """Returns False if there was nothing to delete."""
    async with Session() as s:
        r = await s.execute(delete(TargetRow).where(TargetRow.name == name))
        await s.commit()
        return bool(r.rowcount)


async def get_all_targets() -> list[Target]:
    async with Session() as s:
        rows = await s.scalars(select(TargetRow).order_by(TargetRow.name))
        return [Target.model_validate(row, from_attributes=True) for row in rows]
