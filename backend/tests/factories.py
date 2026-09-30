from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Candidate, CandidateStatus, Source
from app.parsers.base import ParsedResume, ResumeData, SearchQuery, SourceParser
from app.services.candidates import upsert_resume


def make_resume(external_id: str = "1", source: Source = Source.SUPERJOB, **data: Any) -> ParsedResume:
    data.setdefault("full_name", f"Кандидат {external_id}")
    data.setdefault("title", "Python-разработчик")
    return ParsedResume(
        source=source,
        external_id=external_id,
        url=f"https://example.com/resume/{external_id}",
        data=ResumeData(**data),
        raw={"id": external_id},
    )


async def make_candidate(
    session: AsyncSession,
    profile_id: int,
    external_id: str = "1",
    status: CandidateStatus = CandidateStatus.NEW,
    **data: Any,
) -> Candidate:
    candidate, _ = await upsert_resume(session, make_resume(external_id, **data), profile_id)
    candidate.status = status
    await session.commit()
    return candidate


class StubParser(SourceParser):
    """Парсер-заглушка: отдаёт заранее заданные резюме, опционально падает в конце."""

    def __init__(self, source: Source, resumes: list[ParsedResume] = (), error: Exception | None = None) -> None:
        self.source = source
        self.resumes = list(resumes)
        self.error = error
        self.closed = False
        self.queries: list[SearchQuery] = []

    async def search(self, query: SearchQuery) -> AsyncIterator[ParsedResume]:
        self.queries.append(query)
        for resume in self.resumes:
            yield resume
        if self.error:
            raise self.error

    async def close(self) -> None:
        self.closed = True
