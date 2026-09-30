"""Шина событий для реалтайма.

Публиковать может кто угодно (API, воркеры TaskIQ): событие уходит в Redis-канал,
каждый процесс API подписан на канал и рассылает его своим WebSocket-клиентам.
"""

import json
from enum import StrEnum
from typing import Any

from fastapi.encoders import jsonable_encoder

from app.core.redis import redis

CHANNEL = "events"


class EventType(StrEnum):
    CANDIDATE_UPDATED = "candidate.updated"  # data: CandidateOut
    CANDIDATES_CREATED = "candidates.created"  # data: {ids, profile_id}
    CANDIDATE_MERGED = "candidate.merged"  # data: {id, into} — карточка id удалена, всё перенесено в into
    COMMENT_CREATED = "comment.created"  # data: CommentOut
    COMMENT_UPDATED = "comment.updated"  # data: CommentOut
    COMMENT_DELETED = "comment.deleted"  # data: {id, candidate_id}
    CANDIDATES_STALE = "candidates.stale"  # data: {stale: [ids], fresh: [ids]} — анкеты стали (не)актуальны
    PRESENCE_UPDATED = "presence.updated"  # data: {candidate_id, viewers: [UserOut]} — кто сейчас смотрит анкету
    IMPORT_FINISHED = "import.finished"  # data: ImportResult — ручной импорт резюме по ссылке
    SOURCE_UPDATED = "source.updated"  # data: SourceStateOut
    SOURCE_LOGIN = "source.login"  # data: LoginState — вход на площадку из интерфейса


async def publish(event: EventType, data: Any) -> None:
    await redis.publish(CHANNEL, json.dumps({"type": event, "data": jsonable_encoder(data)}))
