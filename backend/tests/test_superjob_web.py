import pytest

from app.core.redis import redis
from app.models import Source
from app.parsers import registry
from app.parsers.base import SearchQuery, SourceBlockedError
from app.parsers.browser.base import BrowserParser
from app.parsers.superjob import web_parser
from app.parsers.superjob.parser import SuperJobParser
from app.parsers.superjob.web_mapper import map_web_resume
from app.parsers.superjob.web_parser import SuperJobWebParser, search_url
from tests.superjob_site import FakeSuperJob, resume_entities

QUERY = SearchQuery(profile_id=1, title="Python-разработчик", keywords="python fastapi")


class TestMapper:
    def test_maps_search_state_resume(self):
        entities = resume_entities(["501", "502"])

        r = map_web_resume(entities, "501", "https://www.superjob.ru/resume/python-501.html")

        assert (r.source, r.external_id, r.url) == (
            Source.SUPERJOB,
            "501",
            "https://www.superjob.ru/resume/python-501.html",
        )
        assert r.published_at.isoformat() == "2026-09-23T12:04:49+03:00"
        d = r.data
        assert d.full_name is None  # анонимно ФИО не отдаётся
        assert (d.title, d.city, d.age) == ("Python-разработчик 501", "Москва", 25)
        assert (d.salary, d.currency) == (None, None)  # «по договорённости» = 0
        assert d.photo_url == "https://public.superjob.ru/images/r501.jpg"
        assert d.about == "Люблю асинхронщину"
        assert d.skills == ["Python", "FastAPI", "PostgreSQL"]
        [work] = d.experience
        assert (work.company, work.position, work.period) == ("Компания 0", "Backend-разработчик", "03.2021 — н.в.")
        assert work.description == "Разработка API на FastAPI\n\nУскорил сервис в 3 раза"
        assert r.raw["via"] == "web"
        assert r.owner_id == "9501"
        assert d.birth_date.isoformat() == "2001-01-17"

    def test_hidden_birthday_is_not_used(self):
        assert map_web_resume(resume_entities(["501", "502"]), "502").data.birth_date is None

    def test_finished_job_salary_and_name_for_logged_in_employer(self):
        entities = resume_entities(["501", "502"], logged_in=True)

        d = map_web_resume(entities, "502").data

        assert d.full_name == "Тестов1 Иван"
        assert (d.salary, d.currency) == (210000, "rub")
        assert d.experience[0].period == "03.2021 — 11.2024"

    def test_tolerates_missing_relations(self):
        entities = {"resume": {"7": {"id": "7", "attributes": {"position": "Тестировщик"}, "relationships": {}}}}

        r = map_web_resume(entities, "7")

        assert r.url == "https://www.superjob.ru/resume/7.html"
        assert r.data.title == "Тестировщик"
        assert (r.data.city, r.data.age, r.data.salary, r.data.photo_url) == (None, None, None, None)
        assert r.data.experience == r.data.skills == []


def test_search_url():
    assert search_url("python fastapi", 1) == (
        "https://www.superjob.ru/resume/search_resume.html?keywords%5B0%5D%5Bkeys%5D=python+fastapi"
    )
    assert search_url("go", 3).endswith("keywords%5B0%5D%5Bkeys%5D=go&page=3")


def test_resume_links_ignore_search_links():
    links = SuperJobWebParser._resume_links(
        [
            "/resume/python-razrabotchik-123.html",
            "/resume/search_resume.html?page=2",
            "https://x.ru/resume/qa-9.html",
            "/resume/",
        ]
    )
    assert links == {
        "123": "https://www.superjob.ru/resume/python-razrabotchik-123.html",
        "9": "https://x.ru/resume/qa-9.html",
    }


class TestRegistry:
    @pytest.mark.parametrize(
        ("mode", "queue", "parser_cls"),
        [("mock", "api", SuperJobParser), ("api", "api", SuperJobParser), ("browser", "browser", SuperJobWebParser)],
    )
    def test_superjob_mode_selects_parser_and_queue(self, monkeypatch, mode, queue, parser_cls):
        monkeypatch.setattr(registry.settings, "superjob_mode", mode)
        assert registry.queue_for(Source.SUPERJOB) == queue
        assert isinstance(registry.create_parser(Source.SUPERJOB), parser_cls)

    def test_hh_is_browser_and_linkedin_is_api_source(self):
        assert registry.queue_for(Source.HH) == "browser"
        assert registry.queue_for(Source.LINKEDIN) == "api"  # Apify: браузер у них, у нас HTTP


# --- настоящий Chromium против фейкового сайта ---

playwright = pytest.importorskip("playwright.async_api")


class FakeSiteParser(SuperJobWebParser):
    password_step_timeout_ms = 2_000

    def __init__(self, site: FakeSuperJob) -> None:
        super().__init__(headless=True)
        self.site = site
        self.pauses: list[tuple] = []

    async def page(self):
        first = self._page is None
        page = await super().page()
        if first:  # ни одного запроса в настоящий интернет
            await self._context.route("**/*", self.site.handle)
        return page

    async def pause(self, min_delay=None, max_delay=None) -> None:
        self.pauses.append((min_delay, max_delay))


@pytest.fixture
def site(monkeypatch, tmp_path) -> FakeSuperJob:
    monkeypatch.setattr(web_parser.settings, "browser_state_dir", tmp_path)
    monkeypatch.setattr(web_parser.settings, "superjob_web_max_pages", 5)
    monkeypatch.setattr(web_parser.settings, "superjob_login", None)
    return FakeSuperJob()


@pytest.fixture(scope="module")
def chromium_available():
    import asyncio

    async def check():
        async with playwright.async_playwright() as p:
            browser = await p.chromium.launch(channel="chromium")
            await browser.close()

    try:
        asyncio.run(check())
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Chromium для Playwright не установлен: {e}")


async def collect(parser: SuperJobWebParser, query: SearchQuery = QUERY) -> list:
    try:
        return [r async for r in parser.search(query)]
    finally:
        await parser.close()


@pytest.mark.usefixtures("chromium_available")
class TestBrowser:
    async def test_walks_all_pages_anonymously(self, site):
        parser = FakeSiteParser(site)

        resumes = await collect(parser)

        assert [r.external_id for r in resumes] == [str(1000 + i) for i in range(7)]
        assert resumes[0].url == "https://www.superjob.ru/resume/python-razrabotchik-1000.html"
        assert [v for v in site.visited if "search_resume" in v] == [
            "/resume/search_resume.html?keywords%5B0%5D%5Bkeys%5D=python+fastapi",
            "/resume/search_resume.html?keywords%5B0%5D%5Bkeys%5D=python+fastapi&page=2",
            "/resume/search_resume.html?keywords%5B0%5D%5Bkeys%5D=python+fastapi&page=3",
        ]
        assert not any(v.startswith("/auth") for v in site.visited)  # без логина не входим
        assert (None, None) in parser.pauses  # между страницами — «человеческая» пауза
        assert parser.state_path.exists()  # сессия сохранена для следующего запуска

    async def test_respects_max_pages(self, site, monkeypatch):
        monkeypatch.setattr(web_parser.settings, "superjob_web_max_pages", 2)
        assert len(await collect(FakeSiteParser(site))) == 6

    async def test_stops_when_daily_budget_is_exhausted(self, site, monkeypatch):
        monkeypatch.setattr(web_parser.settings, "browser_daily_page_limit", 1)

        resumes = await collect(FakeSiteParser(site))

        assert len(resumes) == 3  # одна страница — и тихая остановка до завтра
        assert len([v for v in site.visited if "search_resume" in v]) == 1

    async def test_budget_is_shared_between_runs(self, site, monkeypatch):
        monkeypatch.setattr(web_parser.settings, "browser_daily_page_limit", 3)
        await collect(FakeSiteParser(site))  # потратил 3 страницы

        assert await collect(FakeSiteParser(site)) == []
        keys = await redis.keys("browser:budget:superjob:*")
        assert len(keys) == 1 and await redis.ttl(keys[0]) > 0

    async def test_captcha_raises_blocked_with_screenshot(self, site, tmp_path):
        site.captcha_on_page = 2

        with pytest.raises(SourceBlockedError, match="капча") as exc:
            await collect(FakeSiteParser(site))

        assert "скриншот" in str(exc.value)
        assert list((tmp_path / "debug").glob("superjob-*-blocked.png"))

    @pytest.mark.parametrize("status", [403, 429])
    async def test_block_status_raises_blocked(self, site, status):
        site.status = status
        with pytest.raises(SourceBlockedError, match=f"HTTP {status}"):
            await collect(FakeSiteParser(site))

    async def test_page_without_state_raises_blocked(self, site):
        site.no_state_on_page = 1
        with pytest.raises(SourceBlockedError, match="нет данных"):
            await collect(FakeSiteParser(site))

    async def test_logs_in_as_employer_and_gets_names(self, site, monkeypatch):
        monkeypatch.setattr(web_parser.settings, "superjob_login", "hr@example.com")
        monkeypatch.setattr(web_parser.settings, "superjob_password", "secret-pass")

        resumes = await collect(FakeSiteParser(site))

        assert site.logins == [{"login": "hr@example.com", "password": "secret-pass", "employer": True}]
        assert resumes[0].data.full_name == "Тестов0 Иван"
        assert len(resumes) == 7

    async def test_reuses_saved_session_without_relogin(self, site, monkeypatch):
        monkeypatch.setattr(web_parser.settings, "superjob_login", "hr@example.com")
        monkeypatch.setattr(web_parser.settings, "superjob_password", "secret-pass")
        await collect(FakeSiteParser(site))

        await collect(FakeSiteParser(site))

        assert len(site.logins) == 1  # во второй раз cookies взяты из storage_state

    async def test_code_instead_of_password_asks_for_manual_login(self, site, monkeypatch):
        monkeypatch.setattr(web_parser.settings, "superjob_login", "hr@example.com")
        monkeypatch.setattr(web_parser.settings, "superjob_password", "secret-pass")
        site.code_required = True

        with pytest.raises(SourceBlockedError, match="browser-login superjob"):
            await collect(FakeSiteParser(site))
        assert site.logins == []


async def test_blocked_browser_superjob_is_paused_until_resumed(auth_client, session, profile, monkeypatch):
    """В browser-режиме SuperJob после капчи встаёт на паузу, как hh/LinkedIn."""
    from app.models import SourceHealth, SourceState
    from app.tasks import collect as collect_task
    from tests.factories import StubParser

    monkeypatch.setattr(registry.settings, "superjob_mode", "browser")
    calls = []

    def create(source):
        calls.append(source)
        return StubParser(source, error=SourceBlockedError("капча"))

    monkeypatch.setattr(collect_task, "create_parser", create)

    await collect_task.run_collect(profile.id, Source.SUPERJOB)
    await collect_task.run_collect(profile.id, Source.SUPERJOB)

    assert len(calls) == 1
    state = await session.get(SourceState, Source.SUPERJOB, populate_existing=True)
    assert state.health == SourceHealth.NEEDS_ATTENTION


def test_browser_parser_is_abstract():
    with pytest.raises(TypeError):
        BrowserParser()  # type: ignore[abstract]
