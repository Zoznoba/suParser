from datetime import datetime

from sqlalchemy import ARRAY, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import Source


class SearchProfile(Base):
    """Кого ищем: позиция + ключевые слова. Сборщик обходит источники по каждому активному профилю."""

    __tablename__ = "search_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    keywords: Mapped[str] = mapped_column(Text)
    sources: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=lambda: [Source.SUPERJOB])
    interval_minutes: Mapped[int] = mapped_column(default=60)
    is_active: Mapped[bool] = mapped_column(default=True)
    last_run_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
