import asyncio
import logging

from fastapi import WebSocket

from app.core.redis import redis
from app.realtime.events import CHANNEL

log = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def broadcast(self, message: str) -> None:
        async def send(ws: WebSocket) -> None:
            try:
                await ws.send_text(message)
            except Exception:
                self.disconnect(ws)

        await asyncio.gather(*(send(ws) for ws in list(self._connections)))

    async def listen(self) -> None:
        """Слушает Redis-канал и пересылает события всем подключённым клиентам этого процесса."""
        while True:
            try:
                async with redis.pubsub() as pubsub:
                    await pubsub.subscribe(CHANNEL)
                    async for msg in pubsub.listen():
                        if msg["type"] == "message":
                            await self.broadcast(msg["data"])
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("redis pubsub listener failed, reconnecting")
                await asyncio.sleep(1)


manager = ConnectionManager()
