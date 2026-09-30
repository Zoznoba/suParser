import secrets

from pwdlib import PasswordHash

from app.core.config import settings
from app.core.redis import redis

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def _key(token: str) -> str:
    return f"session:{token}"


async def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    await redis.set(_key(token), user_id, ex=settings.session_ttl_seconds)
    return token


async def get_session_user_id(token: str) -> int | None:
    value = await redis.get(_key(token))
    return int(value) if value else None


async def delete_session(token: str) -> None:
    await redis.delete(_key(token))
