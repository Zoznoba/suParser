import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from redis.exceptions import LockError
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.redis import redis
from app.models import CandidateSource, SearchProfile, Source, SourceHealth, User
from app.parsers.base import PageGoneError, SearchQuery, SourceBlockedError
from app.parsers.registry import ENABLED_SOURCES, Queue, create_parser, queue_for
from app.realtime.events import EventType, publish
from app.schemas.candidate import ImportResult
from app.services import candidates as candidates_service
from app.services.candidates import upsert_resume
from app.services.sources import get_state, set_health
from app.services.stale import mark_gone, refresh_stale
from app.tasks.broker import api_broker, browser_broker

if TYPE_CHECKING:
    from app.parsers.hh.parser import HHParser

log = logging.getLogger(__name__)

LOCK_TIMEOUT = 60 * 60


async def run_collect(profile_id: int, source: Source) -> int:
    """Собирает резюме по профилю из одного источника. Возвращает число новых карточек."""
    # один источник = один активный сбор (один аккаунт — одна сессия, без гонок при upsert)
    lock = redis.lock(f"lock:collect:{source}", timeout=LOCK_TIMEOUT, blocking_timeout=LOCK_TIMEOUT)
    if not await lock.acquire():
        log.warning("collect %s/%s: lock timeout, skipped", source, profile_id)
        return 0
    try:
        async with SessionLocal() as session:
            profile = await session.get(SearchProfile, profile_id)
            if profile is None or not profile.is_active:
                return 0
            state = await get_state(session, source)
            if state.health == SourceHealth.DISABLED or (
                state.health == SourceHealth.NEEDS_ATTENTION and queue_for(source) == Queue.BROWSER
            ):
                log.info("collect %s/%s: source is %s, skipped", source, profile_id, state.health)
                return 0

            query = SearchQuery(profile_id=profile.id, title=profile.title, keywords=profile.keywords)
            parser = create_parser(source)
            new_ids: list[int] = []
            try:
                async for resume in parser.search(query):
                    candidate, created = await upsert_resume(session, resume, profile.id)
                    if created:
                        new_ids.append(candidate.id)
                await session.commit()
            except SourceBlockedError as e:
                await session.rollback()
                await set_health(session, source, SourceHealth.NEEDS_ATTENTION, str(e))
                return 0
            except Exception as e:
                await session.rollback()
                await set_health(session, source, SourceHealth.NEEDS_ATTENTION, f"Ошибка сбора: {e}")
                raise
            finally:
                await parser.close()

            await mark_gone(session, source, parser.gone)
            if parser.complete:
                state.last_complete_at = datetime.now(UTC)
            await set_health(session, source, SourceHealth.OK, success=True)
            await refresh_stale(session)
            if new_ids:
                await publish(EventType.CANDIDATES_CREATED, {"ids": new_ids, "profile_id": profile.id})
            log.info("collect %s/%s: %d new", source, profile_id, len(new_ids))
            return len(new_ids)
    finally:
        try:
            await lock.release()
        except LockError:
            pass


@api_broker.task(task_name="collect_api")
async def collect_api(profile_id: int, source: Source) -> int:
    return await run_collect(profile_id, Source(source))


@browser_broker.task(task_name="collect_browser")
async def collect_browser(profile_id: int, source: Source) -> int:
    return await run_collect(profile_id, Source(source))


async def enqueue_collect(profile: SearchProfile) -> list[Source]:
    queued = []
    for source in map(Source, profile.sources):
        if source not in ENABLED_SOURCES:
            continue
        task = collect_api if queue_for(source) == Queue.API else collect_browser
        await task.kiq(profile.id, source)
        queued.append(source)
    return queued


@api_broker.task(task_name="dispatch", schedule=[{"cron": settings.dispatch_cron}])
async def dispatch() -> None:
    """Раз в минуту: ставит в очередь сбор для профилей, у которых подошёл интервал."""
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        profiles = await session.scalars(select(SearchProfile).where(SearchProfile.is_active))
        for profile in profiles:
            if profile.last_run_at and profile.last_run_at + timedelta(minutes=profile.interval_minutes) > now:
                continue
            await enqueue_collect(profile)
            profile.last_run_at = now
        await session.commit()


@api_broker.task(task_name="refresh_stale", schedule=[{"cron": settings.stale_cron}])
async def refresh_stale_task() -> None:
    """Анкеты «стареют» и без сбора: время идёт, а резюме всё не попадается в выдаче."""
    async with SessionLocal() as session:
        await refresh_stale(session)


# --- ручной импорт резюме hh по ссылке (ТЗ: резервный вариант, если аккаунт работодателя заблокируют) ---


def create_import_parser() -> "HHParser":
    from app.parsers.hh.parser import HHParser

    # без сессии аккаунта: он может быть заблокирован; hh отдаст резюме без ФИО, опыта и контактов
    return HHParser(anonymous=True)


@browser_broker.task(task_name="import_resume")
async def import_resume(request_id: str, resume_hash: str, url: str, user_id: int) -> ImportResult:
    """Открывает одно резюме hh без входа и кладёт в ленту. Итог — событие import.finished (его ждёт фронт)."""
    result = ImportResult(request_id=request_id, user_id=user_id, url=url)
    async with SessionLocal() as session:
        existing = await session.scalar(
            select(CandidateSource.candidate_id).where(
                CandidateSource.source == Source.HH, CandidateSource.external_id == resume_hash
            )
        )
        if existing:  # пока задача ждала очереди, резюме нашёл сбор — анонимная копия его только испортит
            result.candidate_id = existing
        else:
            await _import(session, result, resume_hash, await session.get(User, user_id))
    await publish(EventType.IMPORT_FINISHED, result)
    return result


async def _import(session, result: ImportResult, resume_hash: str, user: User | None) -> None:
    parser = create_import_parser()
    try:
        resume = await parser.fetch_resume(resume_hash, None)
    except PageGoneError:
        result.error = "hh ответил «не найдено»: резюме удалено или скрыто соискателем"
        return
    except SourceBlockedError as e:
        result.error = f"hh не отдал резюме: {e}"
        return
    except Exception:
        log.exception("import %s failed", result.url)
        result.error = "не удалось открыть резюме, попробуйте позже"
        return
    finally:
        await parser.close()

    if resume is None:
        result.error = "дневной лимит страниц hh исчерпан — попробуйте завтра"
        return
    candidate, created = await upsert_resume(session, resume, None, imported_by=user)
    await session.commit()
    result.candidate_id = candidate.id
    await refresh_stale(session)
    if created:
        await publish(EventType.CANDIDATES_CREATED, {"ids": [candidate.id], "profile_id": None})
    else:  # склеилось с карточкой с другой площадки
        await publish(EventType.CANDIDATE_UPDATED, await candidates_service.get_candidate(session, candidate.id, False))
