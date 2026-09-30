"""Вход на браузерную площадку из интерфейса — задача browser-воркера (см. parsers.browser.login)."""

import logging

from redis.exceptions import LockError

from app.core.db import SessionLocal
from app.core.redis import redis
from app.models import Source, SourceHealth
from app.parsers.base import SourceBlockedError
from app.parsers.browser.base import BrowserParser
from app.parsers.browser.login import LoginCancelled, LoginChannel, LoginFailed, LoginStatus, LoginTimeout
from app.parsers.registry import create_parser
from app.services.sources import set_health
from app.tasks.broker import browser_broker
from app.tasks.collect import LOCK_TIMEOUT

log = logging.getLogger(__name__)


async def run_login(source: Source) -> LoginStatus:
    channel = LoginChannel(source)
    state = await channel.get()
    if state is None or state.status != LoginStatus.QUEUED:  # отменили, пока ждали воркер
        return state.status if state else LoginStatus.CANCELLED
    await redis.delete(channel.input_key)

    # тот же lock, что у сбора: одна сессия браузера на источник
    lock = redis.lock(f"lock:collect:{source}", timeout=LOCK_TIMEOUT, blocking_timeout=LOCK_TIMEOUT)
    if not await lock.acquire():
        await channel.update(LoginStatus.FAILED, error="источник занят сбором, попробуйте позже")
        return LoginStatus.FAILED
    parser = create_parser(source)
    assert isinstance(parser, BrowserParser)
    try:
        await channel.update(LoginStatus.RUNNING, prompt="Открываем страницу входа…")
        try:
            await parser.ui_login(channel)
        except LoginCancelled:
            return (await channel.update(LoginStatus.CANCELLED)).status
        except LoginTimeout:
            return (await channel.update(LoginStatus.FAILED, error="не дождались ответа — начните вход заново")).status
        except (LoginFailed, SourceBlockedError) as e:
            error = str(e)
        except Exception as e:
            log.exception("login %s failed", source)
            error = f"ошибка входа: {e}"
        else:
            async with SessionLocal() as session:
                await set_health(session, source, SourceHealth.OK)
            log.info("login %s: done", source)
            return (await channel.update(LoginStatus.DONE, prompt="Вход выполнен, сессия сохранена")).status
        return (await channel.update(LoginStatus.FAILED, error=error, screenshot=await parser.snapshot())).status
    finally:
        await parser.close()
        try:
            await lock.release()
        except LockError:
            pass


@browser_broker.task(task_name="login_browser")
async def login_browser(source: Source) -> str:
    return await run_login(Source(source))
