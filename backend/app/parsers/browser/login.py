"""Вход на площадку из интерфейса: браузер живёт в browser-воркере, человек отвечает в UI.

Воркер ведёт настоящий (headless) браузер и на каждом шаге, где нужен человек — логин, код из SMS/почты,
капча, — публикует состояние со скриншотом страницы и ждёт ответа. API только читает состояние и кладёт ответы.
Всё общение идёт через Redis: состояние — ключ (+ WS-событие source.login), ответы — список.
Ответы (в т.ч. пароль) лежат в Redis, только пока воркер их не забрал, и никуда не логируются.
"""

import asyncio
import json
import time
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel

from app.core.config import settings
from app.core.redis import redis
from app.models.enums import Source
from app.realtime.events import EventType, publish

STATE_TTL = 60 * 30
POLL_INTERVAL = 1.0


class LoginStatus(StrEnum):
    QUEUED = "queued"  # ждёт браузерный воркер (он может быть занят сбором)
    RUNNING = "running"  # браузер работает, человек пока не нужен
    NEED_INPUT = "need_input"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE = {LoginStatus.QUEUED, LoginStatus.RUNNING, LoginStatus.NEED_INPUT}


class LoginStep(StrEnum):
    LOGIN = "login"  # почта/телефон и (необязательно) пароль
    CODE = "code"  # код из SMS/почты
    CAPTCHA = "captcha"  # символы с картинки


class LoginState(BaseModel):
    source: Source
    status: LoginStatus
    step: LoginStep | None = None
    prompt: str | None = None
    error: str | None = None  # ошибка площадки на текущем шаге («неверный код») или причина неудачи
    screenshot: str | None = None  # data:image/jpeg;base64,...
    started_by: str | None = None
    updated_at: datetime


class LoginCancelled(Exception):
    pass


class LoginFailed(Exception):
    """Площадка повела себя неожиданно — вход из интерфейса невозможен, нужен ручной."""


class LoginTimeout(Exception):
    pass


class LoginChannel:
    def __init__(self, source: Source) -> None:
        self.source = source
        self.state_key = f"login:{source}:state"
        self.input_key = f"login:{source}:input"

    async def get(self) -> LoginState | None:
        raw = await redis.get(self.state_key)
        return LoginState.model_validate_json(raw) if raw else None

    async def update(self, status: LoginStatus, **fields) -> LoginState:
        """Новое состояние. started_by переносится из предыдущего, остальные поля — только переданные."""
        prev = await self.get()
        fields.setdefault("started_by", prev.started_by if prev else None)
        state = LoginState(source=self.source, status=status, updated_at=datetime.now(UTC), **fields)
        await redis.set(self.state_key, state.model_dump_json(), ex=STATE_TTL)
        await publish(EventType.SOURCE_LOGIN, state)
        return state

    # --- сторона воркера ---

    async def ask(
        self, step: LoginStep, prompt: str, screenshot: str | None = None, error: str | None = None
    ) -> dict[str, str]:
        await self.update(LoginStatus.NEED_INPUT, step=step, prompt=prompt, screenshot=screenshot, error=error)
        deadline = time.monotonic() + settings.browser_login_input_timeout
        while time.monotonic() < deadline:
            if raw := await redis.lpop(self.input_key):
                answer = json.loads(raw)
                if answer.get("cancel"):
                    raise LoginCancelled
                await self.update(LoginStatus.RUNNING, prompt="Проверяем…")
                return answer
            await asyncio.sleep(POLL_INTERVAL)
        raise LoginTimeout

    # --- сторона API ---

    async def answer(self, values: dict[str, str]) -> None:
        await redis.rpush(self.input_key, json.dumps(values))
        await redis.expire(self.input_key, settings.browser_login_input_timeout)

    async def cancel(self) -> LoginState | None:
        state = await self.get()
        if state is None or state.status not in ACTIVE:
            return state
        if state.status == LoginStatus.QUEUED:  # воркер ещё не взял — задача увидит отмену и выйдет
            return await self.update(LoginStatus.CANCELLED)
        await self.answer({"cancel": "1"})  # воркер заберёт на ближайшем вопросе
        return state
