import json
import time
from typing import Any

import httpx

from app.core.config import settings
from app.core.redis import redis

API_URL = "https://api.superjob.ru/2.0"
TOKEN_KEY = "superjob:token"


class SuperJobError(Exception):
    pass


class SuperJobClient:
    """Клиент SuperJob API v2.0. Поиск резюме требует OAuth-токена аккаунта работодателя."""

    def __init__(self) -> None:
        if not (settings.superjob_app_id and settings.superjob_secret):
            raise SuperJobError("SUPERJOB_APP_ID / SUPERJOB_SECRET не заданы")
        self._http = httpx.AsyncClient(
            base_url=API_URL,
            headers={"X-Api-App-Id": settings.superjob_secret},
            timeout=30,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def search_resumes(self, keyword: str, page: int, count: int = 100) -> dict[str, Any]:
        token = await self._access_token()
        resp = await self._http.get(
            "/resumes/",
            params={"keyword": keyword, "page": page, "count": count},
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 401:
            await redis.delete(TOKEN_KEY)
        if resp.is_error:
            raise SuperJobError(f"/resumes/ {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    async def _access_token(self) -> str:
        cached = await redis.get(TOKEN_KEY)
        if cached:
            token = json.loads(cached)
            if token["expires_at"] > time.time() + 60:
                return token["access_token"]
            try:
                return await self._store(
                    await self._oauth("/oauth2/refresh_token/", refresh_token=token["refresh_token"])
                )
            except SuperJobError:
                pass
        if not (settings.superjob_login and settings.superjob_password):
            raise SuperJobError("SUPERJOB_LOGIN / SUPERJOB_PASSWORD не заданы")
        return await self._store(
            await self._oauth(
                "/oauth2/password/",
                login=settings.superjob_login,
                password=settings.superjob_password,
                hr=1,
            )
        )

    async def _oauth(self, path: str, **params: Any) -> dict[str, Any]:
        params |= {"client_id": settings.superjob_app_id, "client_secret": settings.superjob_secret}
        resp = await self._http.post(path, data=params)
        if resp.is_error:
            raise SuperJobError(f"{path} {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    async def _store(self, data: dict[str, Any]) -> str:
        token = {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "expires_at": time.time() + int(data.get("expires_in", 3600)),
        }
        await redis.set(TOKEN_KEY, json.dumps(token), ex=60 * 60 * 24 * 30)
        return token["access_token"]
