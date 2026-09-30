"""Актуальность анкет (ТЗ: «анкета остаётся в базе сайта, пока актуальна»).

Резюме на площадке неактуально, если:
- площадка ответила на него 404 — удалено или скрыто (CandidateSource.gone_at);
- или оно не попадалось в поиске settings.stale_after_days дней, считая от последнего полного обхода площадки.
  Отсчёт от обхода, а не от «сейчас»: пока площадка на паузе (капча, разлогин) или обход обрывается
  дневным лимитом страниц, резюме не «стареют» — мы их просто не искали.
Резюме, добавленные вручную по ссылке, в поиске могут и не встречаться — для них действует только 404.

Анкета неактуальна, когда неактуальны все её резюме. Из базы она не удаляется: скрыта из ленты по умолчанию,
статус и комментарии сохраняются. Резюме снова попалось в поиске — анкета снова актуальна.
"""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import Exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Candidate, CandidateSource, Source, SourceState
from app.realtime.events import EventType, publish


def fresh_source_exists() -> Exists:
    """У анкеты есть хотя бы одно актуальное резюме (коррелированный подзапрос к Candidate)."""
    max_gap = timedelta(days=settings.stale_after_days)
    return (
        select(CandidateSource.id)
        .outerjoin(SourceState, SourceState.source == CandidateSource.source)
        .where(
            CandidateSource.candidate_id == Candidate.id,
            CandidateSource.gone_at.is_(None),
            or_(
                CandidateSource.imported_by_id.is_not(None),
                SourceState.last_complete_at.is_(None),
                SourceState.last_complete_at - CandidateSource.last_seen_at <= max_gap,
            ),
        )
        .exists()
    )


async def mark_gone(session: AsyncSession, source: Source, external_ids: Iterable[str]) -> None:
    ids = list(external_ids)
    if ids:
        await session.execute(
            update(CandidateSource)
            .where(CandidateSource.source == source, CandidateSource.external_id.in_(ids))
            .where(CandidateSource.gone_at.is_(None))
            .values(gone_at=datetime.now(UTC))
        )


async def refresh_stale(session: AsyncSession) -> tuple[list[int], list[int]]:
    """Пересчитывает Candidate.stale_since и рассылает изменения.

    Возвращает (ставшие неактуальными, снова актуальные)."""
    fresh = fresh_source_exists()

    async def mark(where, value: datetime | None) -> list[int]:
        stmt = (
            update(Candidate)
            .where(where)
            # updated_at не трогаем: «обновлена» в карточке — про данные резюме, а не про пересчёт актуальности
            .values(stale_since=value, updated_at=Candidate.updated_at)
            .returning(Candidate.id)
            .execution_options(synchronize_session=False)
        )
        return sorted(await session.scalars(stmt))

    stale = await mark(Candidate.stale_since.is_(None) & ~fresh, datetime.now(UTC))
    revived = await mark(Candidate.stale_since.is_not(None) & fresh, None)
    await session.commit()
    if stale or revived:
        await publish(EventType.CANDIDATES_STALE, {"stale": stale, "fresh": revived})
    return stale, revived
