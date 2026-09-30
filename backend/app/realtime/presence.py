"""Кто сейчас смотрит анкету — ТЗ: «чтобы двое не писали одному кандидату параллельно».

Каждое WebSocket-соединение сообщает, какие анкеты у него открыты (карточка или тред в ленте):
{"type": "view", "candidate_ids": [...]}. Состояние общее для всех процессов API — хэш в Redis
«соединение → пользователь, анкеты, до какого времени». Запись продлевается пингом клиента (раз в 25 с),
а через TTL без пинга считается устаревшей — так вычищаются соединения упавшего процесса.
Изменения рассылаются событием presence.updated по каждой затронутой анкете.
"""

import json
import time
from collections.abc import Iterable

from app.core.redis import redis
from app.models import User
from app.realtime.events import EventType, publish
from app.schemas.candidate import Viewers
from app.schemas.common import UserOut

KEY = "presence"
TTL = 60
MAX_VIEWING = 20  # анкет на одно соединение: больше тредов разом никто не раскрывает


async def _entries() -> dict[str, dict]:
    now = time.time()
    alive, dead = {}, []
    for conn_id, raw in (await redis.hgetall(KEY)).items():
        entry = json.loads(raw)
        if entry["expires"] > now:
            alive[conn_id] = entry
        else:
            dead.append(conn_id)
    if dead:
        await redis.hdel(KEY, *dead)
    return alive


async def viewers() -> dict[int, list[UserOut]]:
    """Анкета → кто её сейчас смотрит (каждый человек один раз, даже если открыл в двух вкладках)."""
    result: dict[int, dict[int, UserOut]] = {}
    for entry in (await _entries()).values():
        user = UserOut.model_validate(entry["user"])
        for candidate_id in entry["candidate_ids"]:
            result.setdefault(candidate_id, {})[user.id] = user
    return {cid: sorted(users.values(), key=lambda u: u.name) for cid, users in result.items()}


async def _publish(candidate_ids: Iterable[int]) -> None:
    ids = sorted(set(candidate_ids))
    if not ids:
        return
    current = await viewers()
    for cid in ids:
        await publish(EventType.PRESENCE_UPDATED, Viewers(candidate_id=cid, viewers=current.get(cid, [])))


async def _get(conn_id: str) -> dict | None:
    raw = await redis.hget(KEY, conn_id)
    return json.loads(raw) if raw else None


async def set_viewing(conn_id: str, user: User | None, candidate_ids: Iterable[int]) -> None:
    old = await _get(conn_id)
    old_ids = set(old["candidate_ids"]) if old else set()
    new_ids = set(list(dict.fromkeys(candidate_ids))[:MAX_VIEWING])
    if new_ids and user is not None:
        entry = {
            "user": UserOut.model_validate(user).model_dump(),
            "candidate_ids": sorted(new_ids),
            "expires": time.time() + TTL,
        }
        await redis.hset(KEY, conn_id, json.dumps(entry))
    else:
        await redis.hdel(KEY, conn_id)
    await _publish(old_ids ^ new_ids)


async def touch(conn_id: str) -> None:
    if entry := await _get(conn_id):
        entry["expires"] = time.time() + TTL
        await redis.hset(KEY, conn_id, json.dumps(entry))


async def leave(conn_id: str) -> None:
    await set_viewing(conn_id, None, [])
