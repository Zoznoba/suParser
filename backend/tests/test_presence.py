"""Кто сейчас смотрит анкету: WS-сообщения view → общее состояние в Redis → событие presence.updated."""

import asyncio
import json
import time

import httpx
import pytest
from httpx_ws import aconnect_ws

from app.core.redis import redis
from app.realtime import presence
from tests.conftest import login, ws_client
from tests.factories import make_candidate
from tests.test_realtime import listener, next_event  # noqa: F401


async def view(ws, *candidate_ids: int) -> None:
    await ws.send_text(json.dumps({"type": "view", "candidate_ids": list(candidate_ids)}))


async def names(client, candidate_id: int) -> list[str]:
    for entry in (await client.get("/api/presence")).json():
        if entry["candidate_id"] == candidate_id:
            return [u["name"] for u in entry["viewers"]]
    return []


async def test_colleague_sees_who_opened_the_card(client, make_user, session, profile, listener):  # noqa: F811
    c = await make_candidate(session, profile.id)
    await make_user(login="anna", name="Анна")
    await make_user(login="oleg", name="Олег")
    await login(client, "anna")
    anna = httpx.Cookies(client.cookies)
    await login(client, "oleg")
    oleg = httpx.Cookies(client.cookies)

    async with (
        ws_client(oleg) as oc,
        aconnect_ws("/api/ws", oc) as oleg_ws,
        ws_client(anna) as ac,
        aconnect_ws("/api/ws", ac) as anna_ws,
    ):
        await view(anna_ws, c.id)
        data = await next_event(oleg_ws, "presence.updated")
        assert data == {"candidate_id": c.id, "viewers": [{"id": 1, "login": "anna", "name": "Анна"}]}
        assert await names(client, c.id) == ["Анна"]

        await view(anna_ws)  # закрыла карточку
        data = await next_event(oleg_ws, "presence.updated")
        assert data == {"candidate_id": c.id, "viewers": []}
        assert await names(client, c.id) == []


async def test_disconnect_clears_presence(auth_client, session, profile, listener):  # noqa: F811
    c = await make_candidate(session, profile.id)

    async with ws_client(auth_client.cookies) as wc:
        async with aconnect_ws("/api/ws", wc) as ws:
            await view(ws, c.id)
            await next_event(ws, "presence.updated")
            assert await names(auth_client, c.id) == ["Анна HR"]

        # вкладку закрыли: сервер убирает запись в finally после разрыва
        async with asyncio.timeout(5):
            while await names(auth_client, c.id):
                await asyncio.sleep(0.02)


async def test_same_person_in_two_tabs_is_listed_once(auth_client, session, profile):
    from app.models import User

    c = await make_candidate(session, profile.id)
    user = await session.get(User, 1)
    await presence.set_viewing("tab-1", user, [c.id])
    await presence.set_viewing("tab-2", user, [c.id, 999])

    assert await names(auth_client, c.id) == ["Анна HR"]
    assert await names(auth_client, 999) == ["Анна HR"]

    await presence.leave("tab-1")
    assert await names(auth_client, c.id) == ["Анна HR"]  # во второй вкладке ещё открыта


async def test_entry_of_dead_process_expires(auth_client, session, profile):
    from app.models import User

    c = await make_candidate(session, profile.id)
    await presence.set_viewing("conn", await session.get(User, 1), [c.id])
    entry = json.loads(await redis.hget(presence.KEY, "conn"))
    entry["expires"] = time.time() - 1  # процесс упал и больше не продлевает
    await redis.hset(presence.KEY, "conn", json.dumps(entry))

    assert await names(auth_client, c.id) == []
    assert not await redis.hexists(presence.KEY, "conn")


async def test_ping_extends_presence(auth_client, session, profile, monkeypatch):
    c = await make_candidate(session, profile.id)
    async with ws_client(auth_client.cookies) as wc, aconnect_ws("/api/ws", wc) as ws:
        await view(ws, c.id)
        await ws.send_text("ping")
        assert await ws.receive_text() == "pong"
        (conn_id,) = await redis.hkeys(presence.KEY)
        before = json.loads(await redis.hget(presence.KEY, conn_id))["expires"]
        time.sleep(0.01)
        await ws.send_text("ping")
        assert await ws.receive_text() == "pong"
        assert json.loads(await redis.hget(presence.KEY, conn_id))["expires"] > before


@pytest.mark.parametrize("junk", ["{not json", '{"type": "view", "candidate_ids": ["x"]}', "[1, 2]", '"view"'])
async def test_junk_messages_do_not_break_connection(auth_client, junk):
    async with ws_client(auth_client.cookies) as wc, aconnect_ws("/api/ws", wc) as ws:
        await ws.send_text(junk)
        await ws.send_text("ping")
        assert await ws.receive_text() == "pong"


async def test_presence_requires_login(client):
    assert (await client.get("/api/presence")).status_code == 401
