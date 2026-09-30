from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models import Candidate, CandidateSource, CandidateStatus, SearchProfile, Source, SourceHealth, SourceState
from app.parsers.base import SourceBlockedError
from app.tasks import collect
from tests.factories import StubParser, make_resume


@pytest.fixture
def stub(monkeypatch):
    """Подменяет парсер источника. Возвращает функцию-настройщик."""
    parsers: dict[Source, StubParser] = {}

    def install(source: Source = Source.SUPERJOB, **kwargs) -> StubParser:
        parsers[source] = StubParser(source, **kwargs)
        return parsers[source]

    monkeypatch.setattr(collect, "create_parser", lambda source: parsers[source])
    return install


async def count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


async def health(session, source: Source) -> SourceState:
    return await session.get(SourceState, source, populate_existing=True)


async def test_collect_creates_candidates_and_marks_source_ok(session, profile, stub):
    parser = stub(resumes=[make_resume("1", city="Москва"), make_resume("2")])

    assert await collect.run_collect(profile.id, Source.SUPERJOB) == 2

    assert await count(session, Candidate) == 2
    assert parser.queries[0].keywords == "python, fastapi"
    assert parser.closed
    state = await health(session, Source.SUPERJOB)
    assert state.health == SourceHealth.OK
    assert state.last_success_at is not None


async def test_repeated_collect_does_not_duplicate_and_keeps_team_work(session, profile, stub):
    stub(resumes=[make_resume("1", salary=100_000)])
    await collect.run_collect(profile.id, Source.SUPERJOB)
    candidate = await session.scalar(select(Candidate))
    candidate.status = CandidateStatus.CONTACTED
    await session.commit()

    # резюме на площадке обновилось
    stub(resumes=[make_resume("1", salary=150_000), make_resume("2")])
    assert await collect.run_collect(profile.id, Source.SUPERJOB) == 1

    assert await count(session, Candidate) == 2
    assert await count(session, CandidateSource) == 2
    updated = await session.get(Candidate, candidate.id, populate_existing=True)
    assert updated.salary == 150_000  # данные резюме обновились
    assert updated.status == CandidateStatus.CONTACTED  # а статус команды — нет


async def test_same_resume_in_two_profiles_is_one_card(session, profile, stub):
    other = SearchProfile(title="Backend", keywords="backend", sources=["superjob"])
    session.add(other)
    await session.commit()
    stub(resumes=[make_resume("1")])

    await collect.run_collect(profile.id, Source.SUPERJOB)
    await collect.run_collect(other.id, Source.SUPERJOB)

    assert await count(session, Candidate) == 1


async def test_captcha_marks_source_needs_attention_and_keeps_nothing_partial(session, profile, stub):
    stub(Source.HH, resumes=[make_resume("1", source=Source.HH)], error=SourceBlockedError("hh: капча"))
    profile.sources = ["hh"]
    await session.commit()

    assert await collect.run_collect(profile.id, Source.HH) == 0

    state = await health(session, Source.HH)
    assert state.health == SourceHealth.NEEDS_ATTENTION
    assert state.message == "hh: капча"
    assert await count(session, Candidate) == 0  # транзакция откатилась


async def test_blocked_browser_source_is_skipped_until_resumed(auth_client, session, profile, stub):
    stub(Source.HH, error=SourceBlockedError("капча"))
    await collect.run_collect(profile.id, Source.HH)

    parser = stub(Source.HH, resumes=[make_resume("1", source=Source.HH)])
    assert await collect.run_collect(profile.id, Source.HH) == 0
    assert parser.queries == []  # в браузер даже не ходили

    # человек прошёл капчу и нажал «продолжить»
    assert (await auth_client.post("/api/sources/hh/resume")).json()["health"] == "ok"
    assert await collect.run_collect(profile.id, Source.HH) == 1


async def test_api_source_error_is_reported_but_retried(session, profile, stub):
    stub(error=RuntimeError("502 Bad Gateway"))
    with pytest.raises(RuntimeError):
        await collect.run_collect(profile.id, Source.SUPERJOB)
    state = await health(session, Source.SUPERJOB)
    assert state.health == SourceHealth.NEEDS_ATTENTION
    assert "502" in state.message

    # у API-источника ошибки обычно временные — следующий запуск идёт и чинит статус
    stub(resumes=[make_resume("1")])
    assert await collect.run_collect(profile.id, Source.SUPERJOB) == 1
    assert (await health(session, Source.SUPERJOB)).health == SourceHealth.OK


async def test_inactive_or_deleted_profile_is_not_collected(session, profile, stub):
    parser = stub(resumes=[make_resume("1")])
    profile.is_active = False
    await session.commit()

    assert await collect.run_collect(profile.id, Source.SUPERJOB) == 0
    assert await collect.run_collect(999, Source.SUPERJOB) == 0
    assert parser.queries == []


async def test_collect_releases_lock(profile, stub):
    from app.core.redis import redis

    stub(resumes=[make_resume("1")])
    await collect.run_collect(profile.id, Source.SUPERJOB)
    assert await redis.get("lock:collect:superjob") is None


class TestDispatch:
    @pytest.fixture
    def enqueued(self, monkeypatch) -> list[int]:
        calls: list[int] = []

        async def fake_enqueue(profile):
            calls.append(profile.id)
            return []

        monkeypatch.setattr(collect, "enqueue_collect", fake_enqueue)
        return calls

    async def add(self, session, last_run_minutes_ago: int | None, interval: int = 60, active: bool = True) -> int:
        last_run = (
            datetime.now(UTC) - timedelta(minutes=last_run_minutes_ago) if last_run_minutes_ago is not None else None
        )
        p = SearchProfile(
            title="p",
            keywords="k",
            sources=["superjob"],
            interval_minutes=interval,
            is_active=active,
            last_run_at=last_run,
        )
        session.add(p)
        await session.commit()
        return p.id

    async def test_runs_only_due_active_profiles(self, session, enqueued):
        never_run = await self.add(session, None)
        due = await self.add(session, 61)
        await self.add(session, 30)  # ещё рано
        await self.add(session, None, active=False)

        await collect.dispatch()

        assert sorted(enqueued) == sorted([never_run, due])

    async def test_updates_last_run_so_next_tick_skips(self, session, enqueued):
        await self.add(session, None)
        await collect.dispatch()
        await collect.dispatch()
        assert len(enqueued) == 1


async def test_enqueue_routes_only_enabled_sources(session, monkeypatch):
    calls = []

    async def fake_kiq(profile_id, source):
        calls.append(source)

    monkeypatch.setattr(collect.collect_api, "kiq", fake_kiq)
    monkeypatch.setattr(collect.collect_browser, "kiq", fake_kiq)
    profile = SearchProfile(id=1, title="p", keywords="k", sources=["superjob", "hh", "linkedin"])

    assert await collect.enqueue_collect(profile) == [Source.SUPERJOB, Source.HH]
    assert calls == [Source.SUPERJOB, Source.HH]
