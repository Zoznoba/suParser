import json
import secrets

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.api.deps import CurrentUser, user_from_cookie
from app.core.config import settings
from app.core.db import SessionLocal
from app.realtime import presence
from app.realtime.manager import manager
from app.schemas.candidate import Viewers

router = APIRouter()


@router.websocket("/ws")
async def websocket(ws: WebSocket) -> None:
    async with SessionLocal() as session:
        user = await user_from_cookie(session, ws.cookies.get(settings.session_cookie_name))
    if user is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    conn_id = secrets.token_hex(8)
    await manager.connect(ws)
    try:
        while True:
            # клиент шлёт ping (сервер отвечает pong — держим соединение живым за прокси)
            # и {"type": "view", "candidate_ids": [...]} — какие анкеты у него сейчас открыты
            message = await ws.receive_text()
            if message == "ping":
                await presence.touch(conn_id)
                await ws.send_text("pong")
                continue
            try:
                data = json.loads(message)
                if data.get("type") == "view":
                    ids = [int(i) for i in data.get("candidate_ids") or []]
                    await presence.set_viewing(conn_id, user, ids)
            except (ValueError, TypeError, AttributeError):
                continue  # мусор от клиента соединение не рвёт
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)
        await presence.leave(conn_id)


@router.get("/presence", response_model=list[Viewers], tags=["candidates"])
async def get_presence(_: CurrentUser) -> list[Viewers]:
    """Кто какие анкеты смотрит сейчас — начальное состояние, дальше приходят события presence.updated."""
    return [Viewers(candidate_id=cid, viewers=users) for cid, users in sorted((await presence.viewers()).items())]
