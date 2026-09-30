import asyncio
import contextlib
import json

import pytest
from httpx_ws import WebSocketDisconnect, aconnect_ws

from app.core.redis import redis
from app.models import Source
from app.realtime.events import CHANNEL
from app.realtime.manager import manager
from app.tasks import collect
from tests.conftest import ws_client
from tests.factories import StubParser, make_candidate, make_resume


@pytest.fixture
async def listener():
    """Слушатель Redis → WebSocket (в проде запускается в lifespan приложения)."""
    task = asyncio.create_task(manager.listen())
    async with asyncio.timeout(5):
        while (await redis.pubsub_numsub(CHANNEL))[0][1] < 1:
            await asyncio.sleep(0.01)
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def next_event(ws, event_type: str) -> dict:
    async with asyncio.timeout(5):
        while True:
            msg = await ws.receive_text()
            if msg != "pong" and (event := json.loads(msg))["type"] == event_type:
                return event["data"]


async def test_ws_rejects_anonymous():
    # сервер закрывает соединение до accept (uvicorn отдаёт на это 403)
    async with ws_client() as c:
        with pytest.raises(WebSocketDisconnect) as exc:
            async with aconnect_ws("/api/ws", c):
                pass
    assert exc.value.code == 1008


async def test_ws_ping_pong(auth_client):
    async with ws_client(auth_client.cookies) as c, aconnect_ws("/api/ws", c) as ws:
        await ws.send_text("ping")
        assert await ws.receive_text() == "pong"


async def test_status_change_is_pushed_to_other_hr(auth_client, session, profile, listener):
    c = await make_candidate(session, profile.id)

    async with ws_client(auth_client.cookies) as wc, aconnect_ws("/api/ws", wc) as ws:
        await auth_client.patch(f"/api/candidates/{c.id}/status", json={"status": "in_progress"})
        data = await next_event(ws, "candidate.updated")

    assert data["id"] == c.id
    assert data["status"] == "in_progress"
    assert data["status_changed_by"]["name"] == "Анна HR"


async def test_comment_is_pushed(auth_client, session, profile, listener):
    c = await make_candidate(session, profile.id)

    async with ws_client(auth_client.cookies) as wc, aconnect_ws("/api/ws", wc) as ws:
        await auth_client.post(f"/api/candidates/{c.id}/comments", json={"text": "Беру"})
        data = await next_event(ws, "comment.created")

    assert (data["candidate_id"], data["text"], data["author"]["name"]) == (c.id, "Беру", "Анна HR")


async def test_new_candidates_from_worker_are_pushed(auth_client, profile, listener, monkeypatch):
    monkeypatch.setattr(collect, "create_parser", lambda s: StubParser(s, [make_resume("1"), make_resume("2")]))

    async with ws_client(auth_client.cookies) as wc, aconnect_ws("/api/ws", wc) as ws:
        await collect.run_collect(profile.id, Source.SUPERJOB)
        data = await next_event(ws, "candidates.created")

    assert data["profile_id"] == profile.id
    assert len(data["ids"]) == 2


async def test_source_health_change_is_pushed(auth_client, profile, listener, monkeypatch):
    from app.parsers.base import SourceBlockedError

    monkeypatch.setattr(collect, "create_parser", lambda s: StubParser(s, error=SourceBlockedError("капча")))

    async with ws_client(auth_client.cookies) as wc, aconnect_ws("/api/ws", wc) as ws:
        await collect.run_collect(profile.id, Source.HH)
        data = await next_event(ws, "source.updated")

    assert (data["source"], data["health"], data["message"]) == ("hh", "needs_attention", "капча")


async def test_broadcast_survives_dead_connection():
    class Dead:
        async def send_text(self, _):
            raise RuntimeError("socket closed")

    class Alive:
        received: list[str] = []

        async def send_text(self, msg):
            self.received.append(msg)

    dead, alive = Dead(), Alive()
    manager._connections.update({dead, alive})
    try:
        await manager.broadcast("hello")
        assert alive.received == ["hello"]
        assert dead not in manager._connections
    finally:
        manager._connections.clear()
