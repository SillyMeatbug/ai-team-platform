"""Async SQLAlchemy setup и доступ к сессии.

Используется SQLite по умолчанию (aiosqlite). DATABASE_URL — из Settings.
# TODO: PostgreSQL для прода (общая БД между инстансами).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from app.config.loader import Settings


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str) -> AsyncEngine:
    """Создать движок один раз; повторные вызовы возвращают существующий."""
    global _engine, _session_factory
    if _engine is None:
        connect_args: dict[str, object] = {}
        if database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_async_engine(
            database_url,
            future=True,
            echo=False,
            connect_args=connect_args,
        )
        _session_factory = async_sessionmaker(
            bind=_engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("DB engine not initialized; call init_engine first")
    return _session_factory


async def init_db() -> None:
    """Создать таблицы при первом запуске (идемпотентно)."""
    from app.models.database import Base

    if _engine is None:
        raise RuntimeError("DB engine not initialized; call init_engine first")
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_schema_patches)


def _apply_schema_patches(sync_conn) -> None:
    """Лёгкие идемпотентные патчи схемы для SQLite без Alembic."""
    insp = inspect(sync_conn)
    tables = set(insp.get_table_names())
    if "chat_messages" not in tables:
        return
    cols = {c["name"] for c in insp.get_columns("chat_messages")}
    if "attachment_file_ids" not in cols:
        sync_conn.execute(
            text("ALTER TABLE chat_messages ADD COLUMN attachment_file_ids JSON")
        )
    if "projects" in tables:
        pcols = {c["name"] for c in insp.get_columns("projects")}
        if "is_crypto_enabled" not in pcols:
            sync_conn.execute(
                text("ALTER TABLE projects ADD COLUMN is_crypto_enabled BOOLEAN DEFAULT 0")
            )
    if "paper_trades" in tables:
        pt_cols = {c["name"] for c in insp.get_columns("paper_trades")}
        if "message_id" not in pt_cols:
            sync_conn.execute(
                text("ALTER TABLE paper_trades ADD COLUMN message_id VARCHAR(36)")
            )


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: одна сессия на запрос."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


def configure_from_settings(settings: "Settings") -> AsyncEngine:
    # Railway deploy note: use managed PostgreSQL via DATABASE_URL.
    # Local development can keep SQLite default from Settings.
    return init_engine(settings.database_url)
