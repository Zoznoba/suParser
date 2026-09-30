import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.db import engine
from app.core.redis import redis
from app.realtime.manager import manager
from app.tasks.broker import api_broker, browser_broker


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await api_broker.startup()
    await browser_broker.startup()
    listener = asyncio.create_task(manager.listen())
    yield
    listener.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await listener
    await api_broker.shutdown()
    await browser_broker.shutdown()
    await redis.aclose()
    await engine.dispose()


app = FastAPI(title="HR Parser", lifespan=lifespan)
app.include_router(api_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
