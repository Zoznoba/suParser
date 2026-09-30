"""Актуальность анкет: не попадалось в поиске 2 дня (после полного обхода) или 404 → неактуальна."""

from datetime import UTC, datetime, timedelta

from httpx_ws import aconnect_ws
from sqlalchemy import select, update

from app.models import Candidate, CandidateSource, CandidateStatus, Source, SourceState
from app.parsers.base import SourceBlockedError
from app.services.stale import refresh_stale
from app.tasks import collect
from tests.conftest import ws_client
from tests.factories import make_resume
from tests.test_collect import stub  # noqa: F401
from tests.test_realtime import listener, next_event  # noqa: F401

DAYS_AGO = datetime.now(UTC) - timedelta(days=3)


async def seen_days_ago(session, *external_ids: str) -> None:
    """Как будто эти резюме последний раз попадались в поиске 3 дня назад."""
    await session.execute(
        update(CandidateSource).where(CandidateSource.external_id.in_(external_ids)).values(last_seen_at=DAYS_AGO)
    )
    await session.commit()


async def card(session, external_id: str) -> Candidate:
    return await session.scalar(
        select(Candidate)
        .join(CandidateSource)
        .where(CandidateSource.external_id == external_id)
        .execution_options(populate_existing=True)
    )


async def feed(client, **params) -> list[str]:
    return sorted(c["full_name"] for c in (await client.get("/api/candidates", params=params)).json()["items"])


async def test_resume_missing_from_search_for_two_days_becomes_stale_and_comes_back(
    auth_client,
    session,
    profile,
    stub,  # noqa: F811
):
    stub(resumes=[make_resume("1"), make_resume("2")])
    await collect.run_collect(profile.id, Source.SUPERJOB)
    c2 = await card(session, "2")
    c2.status = CandidateStatus.CONTACTED
    await session.commit()
    await auth_client.post(f"/api/candidates/{c2.id}/comments", json={"text": "Уже общаемся"})
    await seen_days_ago(session, "1", "2")

    stub(resumes=[make_resume("1")])  # второе резюме пропало из выдачи
    await collect.run_collect(profile.id, Source.SUPERJOB)

    assert (await card(session, "1")).stale_since is None
    stale = await card(session, "2")
    assert stale.stale_since is not None
    assert stale.status == CandidateStatus.CONTACTED  # работа команды не теряется
    assert await feed(auth_client) == ["Кандидат 1"]  # по умолчанию лента — только актуальные
    assert await feed(auth_client, freshness="stale") == ["Кандидат 2"]
    assert await feed(auth_client, freshness="all") == ["Кандидат 1", "Кандидат 2"]
    assert (await auth_client.get(f"/api/candidates/{c2.id}")).json()["stale_since"] is not None

    stub(resumes=[make_resume("1"), make_resume("2")])  # снова в выдаче
    await collect.run_collect(profile.id, Source.SUPERJOB)

    assert (await card(session, "2")).stale_since is None
    assert (await auth_client.get(f"/api/candidates/{c2.id}/comments")).json()[0]["text"] == "Уже общаемся"


async def test_less_than_two_days_is_still_actual(session, profile, stub):  # noqa: F811
    stub(resumes=[make_resume("1"), make_resume("2")])
    await collect.run_collect(profile.id, Source.SUPERJOB)
    await session.execute(
        update(CandidateSource)
        .where(CandidateSource.external_id == "2")
        .values(last_seen_at=datetime.now(UTC) - timedelta(days=1, hours=23))
    )
    await session.commit()

    stub(resumes=[make_resume("1")])
    await collect.run_collect(profile.id, Source.SUPERJOB)

    assert (await card(session, "2")).stale_since is None


async def test_paused_source_does_not_age_resumes(session, profile, stub):  # noqa: F811
    """Площадка на паузе (капча) — резюме не искали, значит и не «пропали»."""
    stub(Source.HH, resumes=[make_resume("1", source=Source.HH)])
    await collect.run_collect(profile.id, Source.HH)
    await seen_days_ago(session, "1")
    state = await session.get(SourceState, Source.HH)
    state.last_complete_at = DAYS_AGO + timedelta(hours=1)
    await session.commit()

    stub(Source.HH, error=SourceBlockedError("капча"))
    await collect.run_collect(profile.id, Source.HH)
    await refresh_stale(session)

    assert (await card(session, "1")).stale_since is None


async def test_run_cut_by_daily_page_limit_does_not_age_resumes(session, profile, stub):  # noqa: F811
    stub(resumes=[make_resume("1"), make_resume("2")])
    await collect.run_collect(profile.id, Source.SUPERJOB)
    await seen_days_ago(session, "1", "2")  # последний полный обход был тогда же
    state = await session.get(SourceState, Source.SUPERJOB)
    state.last_complete_at = complete_before = DAYS_AGO
    await session.commit()

    parser = stub(resumes=[make_resume("1")])
    parser.complete = False  # дневной лимит страниц кончился посреди выдачи
    await collect.run_collect(profile.id, Source.SUPERJOB)

    assert (await card(session, "2")).stale_since is None
    state = await session.get(SourceState, Source.SUPERJOB, populate_existing=True)
    assert state.last_complete_at == complete_before
    assert state.last_success_at > complete_before


async def test_gone_resume_is_stale_right_away(session, profile, stub):  # noqa: F811
    stub(resumes=[make_resume("1"), make_resume("2")])
    await collect.run_collect(profile.id, Source.SUPERJOB)

    parser = stub(resumes=[make_resume("1")])
    parser.gone = ("2",)  # площадка ответила 404
    await collect.run_collect(profile.id, Source.SUPERJOB)

    assert (await card(session, "2")).stale_since is not None
    src = await session.scalar(select(CandidateSource).where(CandidateSource.external_id == "2"))
    assert src.gone_at is not None


async def test_card_is_actual_while_any_of_its_resumes_is(session, profile, stub):  # noqa: F811
    # один человек на SuperJob и hh (склеено по ФИО + дате рождения)
    person = {"full_name": "Иван Петров", "birth_date": "1990-01-01"}
    stub(resumes=[make_resume("sj", **person)])
    stub(Source.HH, resumes=[make_resume("hh", source=Source.HH, **person)])
    await collect.run_collect(profile.id, Source.SUPERJOB)
    await collect.run_collect(profile.id, Source.HH)
    assert (await card(session, "sj")).id == (await card(session, "hh")).id
    await seen_days_ago(session, "sj")

    stub(resumes=[make_resume("other")])  # на SuperJob его больше нет, на hh ещё свежий
    await collect.run_collect(profile.id, Source.SUPERJOB)

    assert (await card(session, "sj")).stale_since is None


async def test_imported_resume_does_not_age_without_404(session, profile, make_user, stub):  # noqa: F811
    from app.services.candidates import upsert_resume

    user = await make_user()
    await upsert_resume(session, make_resume("manual", source=Source.HH), None, imported_by=user)
    await session.commit()
    await seen_days_ago(session, "manual")

    stub(Source.HH, resumes=[make_resume("other", source=Source.HH)])
    await collect.run_collect(profile.id, Source.HH)

    assert (await card(session, "manual")).stale_since is None


async def test_scheduled_refresh_ages_resumes_without_collect(session, profile, stub):  # noqa: F811
    stub(resumes=[make_resume("1")])
    await collect.run_collect(profile.id, Source.SUPERJOB)
    await seen_days_ago(session, "1")  # и с тех пор был полный обход, где его не было
    state = await session.get(SourceState, Source.SUPERJOB)
    state.last_complete_at = datetime.now(UTC)
    await session.commit()

    await collect.refresh_stale_task()

    assert (await card(session, "1")).stale_since is not None


async def test_stale_change_is_pushed(auth_client, session, profile, stub, listener):  # noqa: F811
    stub(resumes=[make_resume("1"), make_resume("2")])
    await collect.run_collect(profile.id, Source.SUPERJOB)
    await seen_days_ago(session, "2")
    stub(resumes=[make_resume("1")])

    async with ws_client(auth_client.cookies) as wc, aconnect_ws("/api/ws", wc) as ws:
        await collect.run_collect(profile.id, Source.SUPERJOB)
        data = await next_event(ws, "candidates.stale")

    assert data == {"stale": [(await card(session, "2")).id], "fresh": []}
