from datetime import datetime

from pydantic import Field

from app.models.enums import Source
from app.schemas.common import Schema


class ProfileIn(Schema):
    title: str = Field(min_length=1, max_length=255)
    keywords: str = ""
    sources: list[Source] = Field(default_factory=lambda: [Source.SUPERJOB])
    interval_minutes: int = Field(default=60, ge=15, le=60 * 24 * 7)
    is_active: bool = True


class ProfileOut(ProfileIn):
    id: int
    last_run_at: datetime | None
    created_at: datetime
