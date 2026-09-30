from datetime import datetime

from sqlalchemy import Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, str_enum
from app.models.enums import Source, SourceHealth


class SourceState(Base):
    """Состояние источника: работает / нужна капча или перелогин / выключен."""

    __tablename__ = "source_states"

    source: Mapped[Source] = mapped_column(str_enum(Source), primary_key=True)
    health: Mapped[SourceHealth] = mapped_column(str_enum(SourceHealth), default=SourceHealth.OK)
    message: Mapped[str | None] = mapped_column(Text)
    last_success_at: Mapped[datetime | None]
    # последний обход, дошедший до конца (не оборван дневным лимитом страниц): от него считается,
    # что резюме «давно не попадалось в поиске» (services.stale)
    last_complete_at: Mapped[datetime | None]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
