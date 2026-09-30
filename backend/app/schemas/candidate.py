from datetime import date, datetime
from typing import Any

from pydantic import Field

from app.models.enums import CandidateStatus, Source
from app.schemas.common import Schema, UserOut


class SourceOut(Schema):
    source: Source
    external_id: str
    url: str | None
    published_at: datetime | None
    fetched_at: datetime
    last_seen_at: datetime
    gone_at: datetime | None
    imported_by: UserOut | None


class CandidateOut(Schema):
    id: int
    full_name: str | None
    title: str | None
    city: str | None
    age: int | None
    birth_date: date | None
    salary: int | None
    currency: str | None
    photo_url: str | None
    status: CandidateStatus
    status_changed_by: UserOut | None
    status_changed_at: datetime | None
    stale_since: datetime | None
    created_at: datetime
    updated_at: datetime
    sources: list[SourceOut]
    comments_count: int = 0


class CandidateDetail(CandidateOut):
    resume: dict[str, Any]


class CandidatePage(Schema):
    items: list[CandidateOut]
    total: int


class DuplicateOut(Schema):
    candidate: CandidateOut
    reasons: list[str]  # что совпало: «ФИО», «дата рождения», …
    sure: bool  # совпадение достаточное для автосклейки (обычно такие уже склеены при сборе)


class MergeIn(Schema):
    other_id: int


class StatusIn(Schema):
    status: CandidateStatus
    # статус, который человек видел, когда нажимал: если его уже сменил коллега — 409, а не молча перезаписать
    expected: CandidateStatus | None = None


class CommentIn(Schema):
    text: str = Field(min_length=1, max_length=5000)


class CommentOut(Schema):
    id: int
    candidate_id: int
    author: UserOut | None
    text: str
    created_at: datetime
    edited_at: datetime | None


class ImportIn(Schema):
    url: str = Field(min_length=1, max_length=2000)


class ImportOut(Schema):
    request_id: str  # по нему фронт узнаёт своё событие import.finished
    candidate_id: int | None = None  # резюме уже есть в базе — карточка сразу


class ImportResult(Schema):
    request_id: str
    user_id: int
    url: str
    candidate_id: int | None = None
    error: str | None = None


class Viewers(Schema):
    candidate_id: int
    viewers: list[UserOut]
