"""Общий контракт парсеров.

Каждый источник (API или браузерный) отдаёт резюме в одном формате — ParsedResume.
Дальше ими занимается services.candidates, которому неважно, откуда пришли данные.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import Source


class SearchQuery(BaseModel):
    profile_id: int
    title: str
    keywords: str


class WorkItem(BaseModel):
    company: str | None = None
    position: str | None = None
    period: str | None = None
    description: str | None = None


class ResumeData(BaseModel):
    full_name: str | None = None
    title: str | None = None
    city: str | None = None
    age: int | None = None
    birth_date: date | None = None
    salary: int | None = None
    currency: str | None = None
    photo_url: str | None = None
    about: str | None = None
    experience: list[WorkItem] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class ParsedResume(BaseModel):
    source: Source
    external_id: str
    url: str | None = None
    # id владельца резюме на площадке (аккаунт соискателя): у одного человека может быть несколько резюме
    owner_id: str | None = None
    published_at: datetime | None = None
    data: ResumeData
    raw: dict[str, Any] = Field(default_factory=dict)


class SourceBlockedError(Exception):
    """Источник требует вмешательства человека: капча, разлогин, блокировка аккаунта."""


class PageGoneError(Exception):
    """Площадка ответила 404/410: резюме удалено или скрыто соискателем."""


class SourceParser(ABC):
    source: Source
    # обход дошёл до конца (выдачи или лимита страниц профиля), а не оборван дневным лимитом —
    # только после такого обхода резюме, которых не было в выдаче, начинают «стареть» (services.stale)
    complete: bool = True
    # external_id резюме, на которые площадка ответила 404 за этот обход
    gone: tuple[str, ...] = ()

    @abstractmethod
    def search(self, query: SearchQuery) -> AsyncIterator[ParsedResume]: ...

    async def close(self) -> None:  # noqa: B027
        pass
