import json
import time

import httpx
import pytest
import respx

from app.core.redis import redis
from app.models import Source
from app.parsers.base import SearchQuery
from app.parsers.superjob import parser as sj_parser
from app.parsers.superjob.client import API_URL, TOKEN_KEY, SuperJobClient, SuperJobError
from app.parsers.superjob.mapper import map_resume

FULL = {
    "id": 123,
    "lastname": "Иванова",
    "firstname": "Мария",
    "middlename": "Петровна",
    "profession": "Python-разработчик",
    "town": {"id": 4, "title": "Москва"},
    "age": 29,
    "payment": 250000,
    "currency": "rub",
    "photo": "https://img.superjob.ru/1.jpg",
    "link": "https://www.superjob.ru/resume/123.html",
    "date_published": 1_700_000_000,
    "achievements": "Люблю тесты",
    "work_history": [
        {"name": "Яндекс", "profession": "Backend", "monthbeg": 3, "yearbeg": 2020, "work": "API"},
        {"name": "Сбер", "profession": "Стажёр", "yearbeg": 2018, "yearend": 2019, "monthend": 12},
    ],
    "base_education_history": [{"institute": {"title": "МФТИ"}, "speciality": "ПМИ", "yearend": 2018}],
    "catalogues": [{"title": "IT"}, {"title": None}],
}


class TestMapper:
    def test_full_resume(self):
        r = map_resume(FULL)

        assert (r.source, r.external_id, r.url) == (Source.SUPERJOB, "123", FULL["link"])
        assert r.published_at.timestamp() == 1_700_000_000
        assert r.raw == FULL
        d = r.data
        assert d.full_name == "Иванова Мария Петровна"
        assert (d.title, d.city, d.age, d.salary, d.currency) == ("Python-разработчик", "Москва", 29, 250000, "rub")
        assert d.photo_url == "https://img.superjob.ru/1.jpg"
        assert d.about == "Люблю тесты"
        assert [(w.company, w.position, w.period) for w in d.experience] == [
            ("Яндекс", "Backend", "3.2020 — н.в."),
            ("Сбер", "Стажёр", "2018 — 12.2019"),
        ]
        assert d.education == ["МФТИ, ПМИ, 2018"]
        assert d.skills == ["IT"]

    def test_minimal_resume(self):
        """У SuperJob многие поля бывают null, 0 или вообще отсутствуют — маппер не должен падать."""
        r = map_resume({"id": 1, "payment": 0, "age": 0, "town": None, "photo": None, "work_history": None})

        d = r.data
        assert r.external_id == "1"
        assert r.published_at is None
        assert (d.full_name, d.city, d.salary, d.age, d.photo_url) == (None, None, None, None, None)
        assert d.experience == d.education == d.skills == []


def token(access: str = "access-1", refresh: str = "refresh-1") -> dict:
    return {"access_token": access, "refresh_token": refresh, "expires_in": 3600}


@pytest.fixture
async def client():
    c = SuperJobClient()
    yield c
    await c.close()


@pytest.fixture
def api():
    with respx.mock(base_url=API_URL, assert_all_called=False) as mock:
        yield mock


class TestClient:
    async def test_password_grant_then_token_is_cached(self, client, api):
        password = api.post("/oauth2/password/").respond(json=token())
        resumes = api.get("/resumes/").respond(json={"objects": [], "total": 0, "more": False})

        await client.search_resumes("python", page=0)
        await client.search_resumes("python", page=1)

        assert password.call_count == 1  # токен взят из Redis во второй раз
        form = dict(httpx.QueryParams(password.calls[0].request.content.decode()))
        assert form == {
            "login": "employer@example.com",
            "password": "employer-pass",
            "hr": "1",
            "client_id": "42",
            "client_secret": "v3.test-secret",
        }
        req = resumes.calls[1].request
        assert req.headers["Authorization"] == "Bearer access-1"
        assert req.headers["X-Api-App-Id"] == "v3.test-secret"
        assert req.url.params["keyword"] == "python"
        assert req.url.params["page"] == "1"

    async def test_expired_token_is_refreshed(self, client, api):
        await redis.set(
            TOKEN_KEY, json.dumps({"access_token": "old", "refresh_token": "r-old", "expires_at": time.time() - 1})
        )
        refresh = api.post("/oauth2/refresh_token/").respond(json=token("access-2", "r-new"))
        resumes = api.get("/resumes/").respond(json={"objects": []})

        await client.search_resumes("python", page=0)

        assert dict(httpx.QueryParams(refresh.calls[0].request.content.decode()))["refresh_token"] == "r-old"
        assert resumes.calls[0].request.headers["Authorization"] == "Bearer access-2"
        assert json.loads(await redis.get(TOKEN_KEY))["refresh_token"] == "r-new"

    async def test_failed_refresh_falls_back_to_password(self, client, api):
        await redis.set(TOKEN_KEY, json.dumps({"access_token": "a", "refresh_token": "r", "expires_at": 0}))
        api.post("/oauth2/refresh_token/").respond(400, json={"error": "invalid_grant"})
        password = api.post("/oauth2/password/").respond(json=token("access-3"))
        api.get("/resumes/").respond(json={"objects": []})

        await client.search_resumes("python", page=0)

        assert password.called

    async def test_401_drops_cached_token(self, client, api):
        api.post("/oauth2/password/").respond(json=token())
        api.get("/resumes/").respond(401, json={"error": {"message": "invalid token"}})

        with pytest.raises(SuperJobError, match="401"):
            await client.search_resumes("python", page=0)
        assert await redis.get(TOKEN_KEY) is None

    async def test_bad_employer_credentials(self, client, api):
        api.post("/oauth2/password/").respond(400, json={"error": {"message": "Неверный логин"}})
        with pytest.raises(SuperJobError, match="oauth2/password"):
            await client.search_resumes("python", page=0)

    def test_requires_app_credentials(self, monkeypatch):
        monkeypatch.setattr("app.parsers.superjob.client.settings.superjob_secret", None)
        with pytest.raises(SuperJobError, match="SUPERJOB_SECRET"):
            SuperJobClient()


class TestParser:
    QUERY = SearchQuery(profile_id=1, title="Python-разработчик", keywords="python django")

    @pytest.fixture(autouse=True)
    def real_api(self, monkeypatch):
        monkeypatch.setattr(sj_parser.settings, "superjob_mode", "api")
        monkeypatch.setattr(sj_parser.asyncio, "sleep", _no_sleep)

    async def collect(self, query=QUERY):
        parser = sj_parser.SuperJobParser()
        try:
            return [r async for r in parser.search(query)]
        finally:
            await parser.close()

    async def test_walks_pages_until_no_more(self, api):
        api.post("/oauth2/password/").respond(json=token())
        pages = api.get("/resumes/").mock(
            side_effect=[
                httpx.Response(200, json={"objects": [{"id": 1}, {"id": 2}], "more": True}),
                httpx.Response(200, json={"objects": [{"id": 3}], "more": False}),
            ]
        )

        resumes = await self.collect()

        assert [r.external_id for r in resumes] == ["1", "2", "3"]
        assert [c.request.url.params["page"] for c in pages.calls] == ["0", "1"]
        assert pages.calls[0].request.url.params["keyword"] == "python django"

    async def test_stops_at_max_pages(self, api, monkeypatch):
        monkeypatch.setattr(sj_parser.settings, "superjob_max_pages", 2)
        api.post("/oauth2/password/").respond(json=token())
        pages = api.get("/resumes/").respond(json={"objects": [{"id": 1}], "more": True})

        await self.collect()

        assert pages.call_count == 2

    async def test_falls_back_to_title_without_keywords(self, api):
        api.post("/oauth2/password/").respond(json=token())
        pages = api.get("/resumes/").respond(json={"objects": [], "more": False})

        await self.collect(SearchQuery(profile_id=1, title="Тестировщик", keywords=""))

        assert pages.calls[0].request.url.params["keyword"] == "Тестировщик"


async def _no_sleep(_: float) -> None:
    pass
