from datetime import datetime

from pydantic import Field

from app.models.enums import Source, SourceHealth
from app.schemas.common import Schema


class SourceStateOut(Schema):
    source: Source
    enabled: bool
    ui_login: bool  # можно войти в аккаунт площадки из интерфейса
    health: SourceHealth
    message: str | None
    last_success_at: datetime | None


class LoginInput(Schema):
    """Ответ человека на шаге входа: login (+ password) на первом шаге, value — код или символы капчи."""

    login: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=255)
    value: str | None = Field(default=None, max_length=64)
