from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_SessionLocal: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str) -> AsyncEngine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_async_engine(database_url, future=True, echo=False)
        _SessionLocal = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _SessionLocal is None:
        raise RuntimeError("Database engine not initialized")
    return _SessionLocal


async def init_db() -> None:
    if _engine is None:
        raise RuntimeError("Database engine not initialized")
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def create_db() -> None:
    await init_db()
