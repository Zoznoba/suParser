from collections.abc import AsyncIterator
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    type_annotation_map = {datetime: DateTime(timezone=True)}


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def str_enum(enum: type[StrEnum]) -> Enum:
    """Enum хранится строкой-значением (varchar), без нативного типа Postgres — проще миграции."""
    return Enum(enum, native_enum=False, length=32, values_callable=lambda e: [m.value for m in e])
