from typing import Any

import httpx

from app.core.config import settings

API_URL = "https://api.apify.com/v2"
PAGE_SIZE = 25  # профилей на странице поиска LinkedIn
# цены актора harvestapi/linkedin-profile-search (бесплатный план Apify); нужны для потолка расхода на запуск
PAGE_PRICE_USD = 0.10
FULL_PROFILE_PRICE_USD = 0.004
# актор списывает страницу и только потом проверяет, хватит ли потолка ещё на одну; не хватает —
# «max charge reached», и профили уже оплаченной страницы не отдаются. Поэтому потолок — на страницу выше
# нужного (+ копейки на старт актора); лишнюю страницу он всё равно не возьмёт: takePages/maxItems
CHARGE_MARGIN_USD = 0.02
# ошибки аккаунта Apify: неверный токен, кончились кредиты, нет доступа к актору — сам сбор это не починит
ACCOUNT_ERRORS = {401, 402, 403}


class ApifyError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ApifyClient:
    """Синхронный запуск актора Apify: запуск → ожидание → элементы датасета одним запросом."""

    def __init__(self) -> None:
        if not settings.apify_token:
            raise ApifyError("APIFY_TOKEN не задан")
        self._http = httpx.AsyncClient(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {settings.apify_token}"},
            timeout=settings.linkedin_run_timeout + 30,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def search_profiles(self, query: str, pages: int) -> list[dict[str, Any]]:
        full = settings.linkedin_profile_mode == "Full"
        run_input: dict[str, Any] = {
            "searchQuery": query,
            "profileScraperMode": settings.linkedin_profile_mode,
            "startPage": 1,
            "takePages": pages,
            "maxItems": pages * PAGE_SIZE,
        }
        if settings.linkedin_location:
            run_input["locations"] = [settings.linkedin_location]
        # потолок расхода: даже если актор поменяет логику, запуск не спишет больше чем на страницу сверх бюджета
        page_price = PAGE_PRICE_USD + (PAGE_SIZE * FULL_PROFILE_PRICE_USD if full else 0)
        max_charge = (pages + 1) * page_price + CHARGE_MARGIN_USD
        resp = await self._http.post(
            f"/acts/{settings.linkedin_actor}/run-sync-get-dataset-items",
            params={
                "format": "json",
                "clean": "true",
                "timeout": settings.linkedin_run_timeout,
                "maxTotalChargeUsd": f"{max_charge:.2f}",
            },
            json=run_input,
        )
        if resp.is_error:
            raise ApifyError(f"Apify {resp.status_code}: {self._error_message(resp)}", resp.status_code)
        items = resp.json()
        if not isinstance(items, list):
            raise ApifyError(f"Apify: неожиданный ответ {str(items)[:300]}")
        return items

    @staticmethod
    def _error_message(resp: httpx.Response) -> str:
        try:
            return resp.json()["error"]["message"]
        except Exception:
            return resp.text[:300]
