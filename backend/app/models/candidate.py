from datetime import date, datetime
from typing import Any

from sqlalchemy import Column, ForeignKey, Index, String, Table, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, str_enum
from app.models.enums import CandidateStatus, Source
from app.models.user import User

candidate_profiles = Table(
    "candidate_profiles",
    Base.metadata,
    Column("candidate_id", ForeignKey("candidates.id", ondelete="CASCADE"), primary_key=True),
    Column("profile_id", ForeignKey("search_profiles.id", ondelete="CASCADE"), primary_key=True),
)


class Candidate(Base):
    """Одна карточка в ленте. Может собираться из нескольких источников (CandidateSource)."""

    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(128))
    age: Mapped[int | None]
    birth_date: Mapped[date | None] = mapped_column(index=True)
    salary: Mapped[int | None]
    currency: Mapped[str | None] = mapped_column(String(8))
    photo_url: Mapped[str | None] = mapped_column(Text)
    # нормализованное резюме: опыт, образование, навыки — см. parsers.base.ResumeData
    resume: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    status: Mapped[CandidateStatus] = mapped_column(str_enum(CandidateStatus), default=CandidateStatus.NEW, index=True)
    status_changed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status_changed_at: Mapped[datetime | None]
    # с какого момента анкета неактуальна: все её резюме сняты с площадок или давно не попадаются в поиске
    # (см. services.stale); None — актуальна
    stale_since: Mapped[datetime | None] = mapped_column(index=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    sources: Mapped[list["CandidateSource"]] = relationship(back_populates="candidate", lazy="selectin")
    status_changed_by: Mapped[User | None] = relationship(lazy="selectin")


class CandidateSource(Base):
    """Резюме кандидата на конкретной площадке."""

    __tablename__ = "candidate_sources"
    __table_args__ = (
        UniqueConstraint("source", "external_id"),
        Index("ix_candidate_sources_source_owner_id", "source", "owner_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    source: Mapped[Source] = mapped_column(str_enum(Source))
    external_id: Mapped[str] = mapped_column(String(128))
    owner_id: Mapped[str | None] = mapped_column(String(128))  # см. ParsedResume.owner_id
    url: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    published_at: Mapped[datetime | None]
    fetched_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())  # последний раз попалось в поиске
    gone_at: Mapped[datetime | None]  # площадка ответила 404 — резюме удалено или скрыто
    # добавлено вручную по ссылке: на такое резюме правило «давно не попадалось в поиске» не действует
    imported_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    candidate: Mapped[Candidate] = relationship(back_populates="sources")
    imported_by: Mapped[User | None] = relationship(lazy="selectin")


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    edited_at: Mapped[datetime | None]

    author: Mapped[User | None] = relationship(lazy="selectin")
