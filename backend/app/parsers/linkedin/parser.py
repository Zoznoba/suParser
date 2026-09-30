import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from sqlalchemy import any_, literal, select

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.redis import redis
from app.models import SearchProfile
from app.models.enums import Source
from app.parsers.base import ParsedResume, SearchQuery, SourceBlockedError, SourceParser
from app.parsers.linkedin.client import ACCOUNT_ERRORS, ApifyClient, ApifyError
from app.parsers.linkedin.mapper import map_profile, profile_id

log = logging.getLogger(__name__)

# profile_id → unix-время последнего поиска, на который ушли страницы (для очереди по кругу)
LAST_RUN_KEY = "linkedin:last_run"


class LinkedInParser(SourceParser):
    """LinkedIn через Apify: поиск людей по ключевым словам без своего аккаунта LinkedIn.

    Каждая страница поиска стоит денег, поэтому у источника жёсткий дневной бюджет страниц на все профили
    (LINKEDIN_DAILY_PAGE_LIMIT): исчерпан — сбор тихо пропускается до завтра, как у браузерных парсеров.
    Бюджет делится по кругу: тратить его может только профиль, который дольше всех не искал в LinkedIn,
    иначе каждый день всё забирал бы профиль, до которого планировщик доходит первым.
    """

    source = Source.LINKEDIN

    def __init__(self) -> None:
        self._client = ApifyClient()

    async def search(self, query: SearchQuery) -> AsyncIterator[ParsedResume]:
        if not await self.is_turn_of(query.profile_id):
            self.complete = False
            return
        pages = await self.take_budget(settings.linkedin_max_pages)
        self.complete = pages == settings.linkedin_max_pages
        if not pages:
            return
        try:
            items = await self._client.search_profiles(query.keywords or query.title, pages)
        except ApifyError as e:
            await self.return_budget(pages)  # запуск не состоялся — страницы не списаны
            if e.status in ACCOUNT_ERRORS:
                raise SourceBlockedError(f"linkedin: {e} — проверьте APIFY_TOKEN и баланс на console.apify.com") from e
            raise
        await redis.hset(LAST_RUN_KEY, str(query.profile_id), time.time())
        for item in items:
            try:
                yield map_profile(item)
            except Exception:
                log.exception("linkedin: cannot map profile %s", profile_id(item))

    async def is_turn_of(self, profile_id: int) -> bool:
        """Очередь среди активных профилей с LinkedIn: первым идёт тот, кто дольше всех не искал (новый — сразу)."""
        async with SessionLocal() as session:
            ids = list(
                await session.scalars(
                    select(SearchProfile.id).where(
                        SearchProfile.is_active, literal(Source.LINKEDIN.value) == any_(SearchProfile.sources)
                    )
                )
            )
        if profile_id not in ids:  # профиль вне очереди (например, выключили, пока задача ждала) — не мешаем
            return True
        last = dict(zip(ids, await redis.hmget(LAST_RUN_KEY, [str(i) for i in ids]), strict=True))
        turn = min(ids, key=lambda i: (float(last[i] or 0), i))
        if turn != profile_id:
            log.info("linkedin: profile %s waits, it is profile %s's turn", profile_id, turn)
        return turn == profile_id

    @staticmethod
    def _budget_key() -> str:
        return f"linkedin:budget:{datetime.now(UTC).date()}"

    async def take_budget(self, wanted: int) -> int:
        """Списывает до wanted страниц из дневного бюджета. Возвращает, сколько удалось."""
        key = self._budget_key()
        used = await redis.incrby(key, wanted)
        await redis.expire(key, 60 * 60 * 48)
        granted = max(0, min(wanted, settings.linkedin_daily_page_limit - (used - wanted)))
        if granted < wanted:
            await redis.decrby(key, wanted - granted)
            log.warning("linkedin: daily page budget (%d) exhausted", settings.linkedin_daily_page_limit)
        return granted

    async def return_budget(self, pages: int) -> None:
        await redis.decrby(self._budget_key(), pages)

    async def close(self) -> None:
        await self._client.close()
