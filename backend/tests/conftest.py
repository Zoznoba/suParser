"""Тесты гоняются на настоящих Postgres и Redis (docker compose up -d postgres redis).

Отдельная база hr_test пересоздаётся миграциями в начале сессии, Redis — db 15.
Окружение выставляется до импорта app: настройки, engine и брокеры создаются при импорте.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

os.environ.update(
    ENVIRONMENT="test",
    DATABASE_URL=os.getenv("TEST_DATABASE_URL", "postgresql+asyncpg://hr:hr@localhost:5432/hr_test"),
    REDIS_URL=os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15"),
    SUPERJOB_MODE="mock",
    SUPERJOB_APP_ID="42",
    SUPERJOB_SECRET="v3.test-secret",
    SUPERJOB_LOGIN="employer@example.com",
    SUPERJOB_PASSWORD="employer-pass",
)

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx_ws.transport import ASGIWebSocketTransport  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.core.redis import redis  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import SearchProfile, User  # noqa: E402
from app.tasks.broker import api_broker, browser_broker  # noqa: E402

PASSWORD = "password123"
BASE_URL = "http://testserver.local"


async def _recreate_database() -> None:
    dsn = settings.database_url.replace("+asyncpg", "")
    db_name = dsn.rsplit("/", 1)[1]
    conn = await asyncpg.connect(dsn.rsplit("/", 1)[0] + "/postgres")
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    asyncio.run(_recreate_database())
    command.upgrade(Config(Path(__file__).parents[1] / "alembic.ini"), "head")


@pytest.fixture(scope="session", autouse=True)
async def brokers(database: None) -> AsyncIterator[None]:
    await api_broker.startup()
    await browser_broker.startup()
    yield
    await api_broker.shutdown()
    await browser_broker.shutdown()
    await redis.aclose()
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean_state(database: None) -> None:
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await redis.flushdb()


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as s:
        yield s


UserFactory = Callable[..., Awaitable[User]]


@pytest.fixture
def make_user(session: AsyncSession) -> UserFactory:
    async def factory(login: str = "hr", name: str = "Анна HR", is_active: bool = True) -> User:
        user = User(login=login, name=name, password_hash=hash_password(PASSWORD), is_active=is_active)
        session.add(user)
        await session.commit()
        return user

    return factory


@pytest.fixture
async def profile(session: AsyncSession) -> SearchProfile:
    profile = SearchProfile(title="Python-разработчик", keywords="python, fastapi", sources=["superjob"])
    session.add(profile)
    await session.commit()
    return profile


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=BASE_URL) as c:
        yield c


@asynccontextmanager
async def ws_client(cookies: httpx.Cookies | None = None) -> AsyncIterator[httpx.AsyncClient]:
    """Клиент для WebSocket. Открывать только внутри теста: task group транспорта
    должна войти и выйти в одной и той же asyncio-задаче (фикстуры так не умеют)."""
    async with httpx.AsyncClient(transport=ASGIWebSocketTransport(app), base_url=BASE_URL, cookies=cookies) as c:
        yield c


async def login(client: httpx.AsyncClient, login: str = "hr") -> None:
    resp = await client.post("/api/auth/login", json={"login": login, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


@pytest.fixture
async def auth_client(client: httpx.AsyncClient, make_user: UserFactory) -> httpx.AsyncClient:
    await make_user()
    await login(client)
    return client
