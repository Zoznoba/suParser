import json

import httpx
import pytest
import respx
from sqlalchemy import select

from app.core.redis import redis
from app.models import CandidateSource, SearchProfile, Source, SourceHealth, SourceState
from app.parsers import registry
from app.parsers.base import SearchQuery, SourceBlockedError
from app.parsers.linkedin import parser as li_parser
from app.parsers.linkedin.client import API_URL, ApifyClient, ApifyError
from app.parsers.linkedin.mapper import map_profile
from app.parsers.linkedin.parser import LinkedInParser

QUERY = SearchQuery(profile_id=1, title="Python-разработчик", keywords="python fastapi")
RUN_PATH = "/acts/harvestapi~linkedin-profile-search/run-sync-get-dataset-items"

LI_ID = "ACwAAAbCdEfGhIjKlMnOpQrStUvWxYz0123456"

# Short — структура снята с живого запуска актора (данные синтетические)
SHORT = {
    "id": LI_ID,
    "profileIdInSearch": LI_ID,
    "linkedinUrl": f"https://www.linkedin.com/in/{LI_ID}",
    "firstName": "Иван",
    "lastName": "Петров",
    "summary": "Python-разработчик, 5 лет в бэкенде",
    "openProfile": False,
    "premium": False,
    "currentPositions": [
        {
            "title": "Python Developer",
            "companyName": "Яндекс",
            "description": "API на FastAPI",
            "current": True,
            "startedOn": {"month": 3, "year": 2021},
            "tenureAtPosition": {"numYears": 3, "numMonths": 6},
        }
    ],
    "pictureUrl": "https://media.licdn.com/dms/image/v2/p.jpg",
    "location": {"linkedinText": "Pyatigorsk, Stavropol, Russia"},
    "_meta": {"pagination": {"totalElements": 5543, "pageNumber": 1}},
}

# Full — по документации актора: slug, headline, photo, experience/education/skills
FULL = {
    "id": LI_ID,
    "publicIdentifier": "Ivan-Petrov-%D0%B8",
    "linkedinUrl": "https://www.linkedin.com/in/ivan-petrov-и",
    "firstName": "Иван",
    "lastName": "Петров",
    "headline": "Python Developer | FastAPI",
    "about": "Пишу бэкенды",
    "photo": "https://media.licdn.com/dms/image/v2/full.jpg",
    "location": {"linkedinText": "Moscow, Russia", "countryCode": "RU", "parsed": {"city": "Moscow"}},
    "experience": [
        {
            "position": "Backend Developer",
            "companyName": "Яндекс",
            "startDate": {"month": 3, "year": 2021},
            "endDate": None,
            "duration": "3 yrs",
            "description": "API на FastAPI",
        },
        {
            "position": "Стажёр",
            "companyName": "Сбер",
            "startDate": {"month": "Aug", "year": 2019},
            "endDate": {"month": "Dec", "year": 2020},
        },
        {"position": "Фриланс", "duration": "1 yr"},
    ],
    "education": [
        {
            "schoolName": "МФТИ",
            "degree": "Бакалавр",
            "fieldOfStudy": "ПМИ",
            "startDate": {"year": 2015},
            "endDate": {"year": 2019},
        },
    ],
    "skills": ["Python", {"name": "PostgreSQL"}, None],
}


class TestMapper:
    def test_short_profile(self):
        r = map_profile(SHORT)

        assert (r.source, r.external_id, r.url) == (Source.LINKEDIN, LI_ID, f"https://www.linkedin.com/in/{LI_ID}")
        d = r.data
        # headline в Short нет — должность из текущей позиции; «О себе» — summary
        assert (d.full_name, d.title, d.city) == ("Иван Петров", "Python Developer", "Pyatigorsk")
        assert d.about == "Python-разработчик, 5 лет в бэкенде"
        assert d.photo_url == "https://media.licdn.com/dms/image/v2/p.jpg"
        [job] = d.experience
        assert (job.company, job.position, job.period, job.description) == (
            "Яндекс",
            "Python Developer",
            "03.2021 — н.в.",
            "API на FastAPI",
        )
        assert d.education == d.skills == []
        assert r.raw["via"] == "apify" and "_meta" not in r.raw  # служебная пагинация актора не нужна

    def test_full_profile(self):
        r = map_profile(FULL)

        assert r.external_id == LI_ID  # тот же id, что и в Short: смена режима не плодит дублей
        d = r.data
        assert (d.title, d.city, d.about) == ("Python Developer | FastAPI", "Moscow", "Пишу бэкенды")
        assert d.photo_url == "https://media.licdn.com/dms/image/v2/full.jpg"
        now, past, free = d.experience
        assert (now.company, now.position, now.period) == ("Яндекс", "Backend Developer", "03.2021 — н.в.")
        assert past.period == "08.2019 — 12.2020"  # месяц словом
        assert (free.company, free.period) == (None, "1 yr")
        assert d.education == ["МФТИ, Бакалавр, ПМИ, 2015 — 2019"]
        assert d.skills == ["Python", "PostgreSQL"]

    def test_country_only_location_and_no_positions(self):
        d = map_profile({"id": "ACwA1", "location": {"linkedinText": "Russia"}, "currentPositions": []}).data
        assert (d.city, d.title, d.experience) == ("Russia", None, [])

    def test_falls_back_to_slug_without_id(self):
        r = map_profile({"publicIdentifier": "Ivan-Petrov-%D0%B8", "headline": "QA"})

        assert (r.external_id, r.url) == ("ivan-petrov-и", "https://www.linkedin.com/in/ivan-petrov-и")
        assert r.data.full_name is None and r.data.city is None

    def test_profile_without_ids_is_rejected(self):
        with pytest.raises(ValueError):
            map_profile({"firstName": "Никто"})


@pytest.fixture
def settings(monkeypatch):
    s = li_parser.settings
    monkeypatch.setattr(s, "apify_token", "apify_api_test")
    monkeypatch.setattr(s, "linkedin_profile_mode", "Short")
    monkeypatch.setattr(s, "linkedin_location", None)
    monkeypatch.setattr(s, "linkedin_max_pages", 1)
    monkeypatch.setattr(s, "linkedin_daily_page_limit", 3)
    return s


@pytest.fixture
def apify(settings):
    with respx.mock(base_url=API_URL, assert_all_called=False) as mock:
        yield mock


async def collect(query: SearchQuery = QUERY) -> tuple[list, LinkedInParser]:
    parser = LinkedInParser()
    try:
        return [r async for r in parser.search(query)], parser
    finally:
        await parser.close()


class TestParser:
    async def test_runs_actor_and_maps_profiles(self, apify):
        route = apify.post(RUN_PATH).respond(201, json=[SHORT, {"id": "ACwA2", "headline": "QA"}, {}])

        resumes, parser = await collect()

        assert [r.external_id for r in resumes] == [LI_ID, "ACwA2"]  # битый профиль пропущен
        assert parser.complete
        req = route.calls.last.request
        assert req.headers["Authorization"] == "Bearer apify_api_test"
        assert (
            req.url.params["maxTotalChargeUsd"] == "0.22"
        )  # страница + ещё одна (иначе актор не отдаёт профили) + старт
        assert json.loads(req.content) == {
            "searchQuery": "python fastapi",
            "profileScraperMode": "Short",
            "startPage": 1,
            "takePages": 1,
            "maxItems": 25,
        }

    async def test_full_mode_location_and_title_fallback(self, apify, settings, monkeypatch):
        monkeypatch.setattr(settings, "linkedin_profile_mode", "Full")
        monkeypatch.setattr(settings, "linkedin_location", "Russia")
        monkeypatch.setattr(settings, "linkedin_max_pages", 2)
        route = apify.post(RUN_PATH).respond(201, json=[FULL])

        resumes, _ = await collect(SearchQuery(profile_id=1, title="Python-разработчик", keywords=""))

        assert resumes[0].data.skills == ["Python", "PostgreSQL"]
        req = route.calls.last.request
        body = json.loads(req.content)
        assert (body["searchQuery"], body["locations"], body["takePages"], body["maxItems"]) == (
            "Python-разработчик",
            ["Russia"],
            2,
            50,
        )
        assert req.url.params["maxTotalChargeUsd"] == "0.62"  # (2 + 1) × ($0.10 + 25 × $0.004) + старт

    async def test_daily_budget_is_shared_between_runs(self, apify, settings, monkeypatch):
        monkeypatch.setattr(settings, "linkedin_max_pages", 2)
        route = apify.post(RUN_PATH).respond(201, json=[SHORT])

        _, first = await collect()  # 2 из 3
        _, second = await collect()  # остаток — 1 страница
        third, last = await collect()  # бюджет кончился: Apify не зовём

        assert [json.loads(c.request.content)["takePages"] for c in route.calls] == [2, 1]
        assert (first.complete, second.complete, last.complete) == (True, False, False)
        assert third == []
        [key] = await redis.keys("linkedin:budget:*")
        assert await redis.get(key) == "3" and await redis.ttl(key) > 0

    @pytest.mark.parametrize("status", [401, 402, 403])
    async def test_account_errors_block_source_and_return_budget(self, apify, status):
        apify.post(RUN_PATH).respond(status, json={"error": {"type": "x", "message": "Not enough usage"}})

        with pytest.raises(SourceBlockedError, match="Not enough usage.*APIFY_TOKEN"):
            await collect()

        [key] = await redis.keys("linkedin:budget:*")
        assert await redis.get(key) == "0"  # запуск не состоялся — деньги не потрачены

    async def test_other_errors_are_raised(self, apify):
        apify.post(RUN_PATH).respond(500, text="boom")
        with pytest.raises(ApifyError, match="Apify 500: boom"):
            await collect()

    async def test_timeout_is_raised(self, apify):
        apify.post(RUN_PATH).mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(httpx.ReadTimeout):
            await collect()

    def test_requires_token(self, settings, monkeypatch):
        monkeypatch.setattr(settings, "apify_token", None)
        with pytest.raises(ApifyError, match="APIFY_TOKEN"):
            ApifyClient()


class TestRoundRobin:
    """Общий бюджет не достаётся каждый день одному и тому же профилю."""

    @pytest.fixture
    async def profiles(self, session):
        items = [
            SearchProfile(title=f"Профиль {i}", keywords=f"q{i}", sources=[Source.HH, Source.LINKEDIN])
            for i in range(3)
        ]
        items.append(SearchProfile(title="Без LinkedIn", keywords="x", sources=[Source.HH]))
        items.append(SearchProfile(title="Выключен", keywords="y", sources=[Source.LINKEDIN], is_active=False))
        session.add_all(items)
        await session.commit()
        return items

    @staticmethod
    def query(p: SearchProfile) -> SearchQuery:
        return SearchQuery(profile_id=p.id, title=p.title, keywords=p.keywords)

    async def test_profiles_take_turns(self, apify, settings, monkeypatch, profiles):
        monkeypatch.setattr(settings, "linkedin_daily_page_limit", 100)
        route = apify.post(RUN_PATH).respond(201, json=[SHORT])
        a, b, c = profiles[:3]

        ran = []
        for p in [a, a, b, c, a, c, b, a]:  # планировщик дёргает профили в своём порядке
            resumes, parser = await collect(self.query(p))
            if resumes:
                ran.append(p.title)
            else:
                assert not parser.complete  # пропуск «не твоя очередь» не считается полным обходом

        # a (очередь пуста — первый по id), затем b и c, потом снова a, b…
        assert ran == ["Профиль 0", "Профиль 1", "Профиль 2", "Профиль 0", "Профиль 1"]
        assert len(route.calls) == 5

    async def test_skipped_turn_does_not_spend_budget(self, apify, settings, profiles):
        apify.post(RUN_PATH).respond(201, json=[SHORT])
        a, b = profiles[:2]

        assert (await collect(self.query(b)))[0] == []  # очередь a — b ждёт, страницу не тратит
        assert len((await collect(self.query(a)))[0]) == 1
        [key] = await redis.keys("linkedin:budget:*")
        assert await redis.get(key) == "1"

    async def test_failed_run_keeps_the_turn(self, apify, profiles):
        apify.post(RUN_PATH).respond(500, text="boom")
        a, b = profiles[:2]

        with pytest.raises(ApifyError):
            await collect(self.query(a))

        assert (await collect(self.query(b)))[0] == []  # a так и не поискал — очередь всё ещё его

    async def test_profile_outside_queue_is_not_blocked(self, apify, profiles):
        apify.post(RUN_PATH).respond(201, json=[SHORT])
        off = profiles[4]  # выключили, пока задача ждала в очереди
        assert len((await collect(self.query(off)))[0]) == 1


async def test_collect_puts_profiles_into_feed(session, profile, apify, monkeypatch):
    """Путь «очередь api → Apify → лента» целиком; LinkedIn включается токеном."""
    from app.tasks import collect as collect_task

    monkeypatch.setattr(collect_task, "ENABLED_SOURCES", registry.ENABLED_SOURCES | {Source.LINKEDIN})
    apify.post(RUN_PATH).respond(201, json=[SHORT])
    profile.sources = [Source.LINKEDIN]
    await session.commit()

    assert await collect_task.enqueue_collect(profile) == [Source.LINKEDIN]

    src = (await session.scalars(select(CandidateSource))).all()
    assert [(s.source, s.external_id) for s in src] == [(Source.LINKEDIN, LI_ID)]
    state = await session.get(SourceState, Source.LINKEDIN, populate_existing=True)
    assert state.health == SourceHealth.OK


async def test_bad_token_puts_source_on_pause(session, profile, apify):
    from app.tasks import collect as collect_task

    apify.post(RUN_PATH).respond(401, json={"error": {"message": "Token is not valid"}})

    assert await collect_task.run_collect(profile.id, Source.LINKEDIN) == 0

    state = await session.get(SourceState, Source.LINKEDIN, populate_existing=True)
    assert state.health == SourceHealth.NEEDS_ATTENTION
    assert "APIFY_TOKEN" in state.message
