import asyncio
from collections.abc import AsyncIterator

from app.core.config import settings
from app.models.enums import Source
from app.parsers.base import ParsedResume, SearchQuery, SourceParser
from app.parsers.superjob.client import SuperJobClient
from app.parsers.superjob.fake import fake_search
from app.parsers.superjob.mapper import map_resume

PAGE_SIZE = 100


class SuperJobParser(SourceParser):
    source = Source.SUPERJOB

    def __init__(self) -> None:
        self._client = SuperJobClient() if settings.superjob_mode == "api" else None

    async def search(self, query: SearchQuery) -> AsyncIterator[ParsedResume]:
        keyword = query.keywords or query.title
        for page in range(settings.superjob_max_pages):
            if self._client:
                data = await self._client.search_resumes(keyword, page=page, count=PAGE_SIZE)
            else:
                data = fake_search(keyword, page, PAGE_SIZE)
            for obj in data.get("objects", []):
                yield map_resume(obj)
            if not data.get("more"):
                break
            await asyncio.sleep(1)  # лимит API ~120 запросов/мин

    async def close(self) -> None:
        if self._client:
            await self._client.close()
