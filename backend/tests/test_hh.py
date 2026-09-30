import asyncio
from collections.abc import Callable

import pytest

from app.core.redis import redis
from app.models import Source
from app.parsers import registry
from app.parsers.base import SearchQuery, SourceBlockedError
from app.parsers.browser.login import LoginChannel, LoginState, LoginStatus, LoginStep
from app.parsers.hh import parser as hh_parser
from app.parsers.hh.mapper import map_resume, map_search_item
from app.parsers.hh.parser import HHParser, search_url
from tests.hh_site import (
    CAPTCHA_TEXT,
    EMPLOYER_CODE,
    EMPLOYER_LOGIN,
    EMPLOYER_PASSWORD,
    FakeHH,
    resume_state,
    search_item,
)

QUERY = SearchQuery(profile_id=1, title="Python-разработчик", keywords="python fastapi")


class TestMapper:
    def test_maps_employer_resume_page(self):
        r = map_resume(resume_state("abc123", logged_in=True))

        assert (r.source, r.external_id, r.url) == (Source.HH, "abc123", "https://hh.ru/resume/abc123")
        assert r.published_at.isoformat() == "2026-09-30T10:46:00+00:00"
        d = r.data
        assert d.full_name == "Тестов0 Иван"
        assert (d.title, d.city, d.age) == ("Python-разработчик abc123", "Москва", 25)
        assert (d.salary, d.currency) == (200000, "rub")
        assert d.photo_url == "https://img.hhcdn.ru/photo/abc123.jpeg"
        assert d.about == "Люблю асинхронщину"
        assert d.skills == ["Python", "FastAPI", "PostgreSQL"]
        current, previous = d.experience
        assert (current.company, current.position) == ("Компания 0", "Backend-разработчик")
        assert current.period == "03.2021 — н.в."
        assert current.description == "Разработка API на FastAPI"
        assert previous.period == "06.2020 — 02.2021"
        assert d.education == ["2020 — МГУ, ВМК, Прикладная математика"]
        assert r.raw["via"] == "web"
        assert "humanDatesRules" not in r.raw["resume"]  # служебный шум не сохраняем
        assert r.raw["resume"]["title"] == "Python-разработчик abc123"

    def test_anonymous_resume_page_has_no_personal_data(self):
        d = map_resume(resume_state("abc123")).data

        assert (d.full_name, d.photo_url) == (None, None)
        assert d.experience == d.education == []
        assert d.city == "Москва"

    def test_tolerates_api_style_experience(self):
        state = resume_state("x")
        state["experience"]["value"] = [{"company": {"name": "Яндекс"}, "position": "SRE", "start": "2019-01"}]

        [work] = map_resume(state).data.experience

        assert (work.company, work.period) == ("Яндекс", "01.2019 — н.в.")

    def test_maps_search_item(self):
        r = map_search_item(search_item("h1", i=0))

        assert (r.external_id, r.url) == ("h1", "https://hh.ru/resume/h1")
        assert (r.data.title, r.data.age) == ("Python-разработчик h1", 25)
        assert (r.data.salary, r.data.currency) == (200000, "rub")
        assert r.data.skills == ["Python", "FastAPI"]
        assert "negotiationLinks" not in r.raw["item"]
        assert map_search_item(search_item("h2", i=1)).data.salary is None


def test_search_url(monkeypatch):
    monkeypatch.setattr(hh_parser.settings, "hh_search_period_days", 3)
    assert search_url("python fastapi", 0) == (
        "https://hh.ru/search/resume?text=python+fastapi&logic=normal&pos=full_text&exp_period=all_time"
        "&order_by=relevance&search_period=3"
    )
    assert search_url("go", 2).endswith(
        "text=go&logic=normal&pos=full_text&exp_period=all_time&order_by=relevance&search_period=3&page=2"
    )

    monkeypatch.setattr(hh_parser.settings, "hh_search_period_days", 0)
    assert "search_period" not in search_url("go", 0)


def test_hh_is_enabled_browser_source():
    assert Source.HH in registry.ENABLED_SOURCES
    assert registry.queue_for(Source.HH) == "browser"
    assert isinstance(registry.create_parser(Source.HH), HHParser)
    assert registry.UI_LOGIN_SOURCES == {Source.HH}


# --- настоящий Chromium против фейкового сайта ---

playwright = pytest.importorskip("playwright.async_api")


class FakeSiteParser(HHParser):
    login_step_polls = 2

    def __init__(self, site: FakeHH, logged_in: bool = False) -> None:
        super().__init__(headless=True)
        self.site = site
        self.logged_in = logged_in
        self.pauses: list[tuple] = []

    async def page(self):
        first = self._page is None
        page = await super().page()
        if first:  # ни одного запроса в настоящий интернет
            await self._context.route("**/*", self.site.handle)
            if self.logged_in:
                await self._context.add_cookies([{"name": "hh_auth", "value": "1", "url": "https://hh.ru"}])
        return page

    async def pause(self, min_delay=None, max_delay=None) -> None:
        self.pauses.append((min_delay, max_delay))


@pytest.fixture
def site(monkeypatch, tmp_path) -> FakeHH:
    monkeypatch.setattr(hh_parser.settings, "browser_state_dir", tmp_path)
    monkeypatch.setattr(hh_parser.settings, "hh_max_pages", 5)
    monkeypatch.setattr(hh_parser.settings, "hh_open_resumes", True)
    monkeypatch.setattr(hh_parser.settings, "hh_require_login", False)
    monkeypatch.setattr(hh_parser.settings, "hh_search_period_days", 0)
    return FakeHH()


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


async def collect(parser: HHParser, query: SearchQuery = QUERY) -> list:
    try:
        return [r async for r in parser.search(query)]
    finally:
        await parser.close()


def search_visits(site: FakeHH) -> list[str]:
    return [v for v in site.visited if v.startswith("/search/resume")]


@pytest.mark.usefixtures("chromium_available")
class TestBrowser:
    async def test_walks_search_and_opens_each_resume(self, site):
        parser = FakeSiteParser(site)

        resumes = await collect(parser)

        hashes = [f"h{1000 + i}" for i in range(7)]
        assert [r.external_id for r in resumes] == hashes  # скрытое (forbidden) резюме пропущено
        assert site.resumes_opened == hashes
        base = "/search/resume?text=python+fastapi&logic=normal&pos=full_text&exp_period=all_time"
        assert search_visits(site) == [
            f"{base}&order_by=relevance",
            f"{base}&order_by=relevance&page=1",
            f"{base}&order_by=relevance&page=2",
        ]
        assert resumes[0].data.city == "Москва"  # данные со страницы резюме, а не из карточки
        assert resumes[0].data.full_name is None  # анонимно
        assert (None, None) in parser.pauses
        assert parser.state_path.exists()

    async def test_employer_session_gets_full_resumes(self, site):
        resumes = await collect(FakeSiteParser(site, logged_in=True))

        assert resumes[0].data.full_name == "Тестов0 Иван"
        assert resumes[0].data.experience[0].company == "Компания 0"

    async def test_unchanged_resumes_are_not_opened_again(self, site):
        await collect(FakeSiteParser(site))
        site.visited.clear()
        site.updated["h1001"] = 1790765160000 + 60_000  # кандидат обновил резюме

        resumes = await collect(FakeSiteParser(site))

        assert len(resumes) == 7  # из кеша — всё равно отдаём, чтобы привязать к профилю
        assert site.resumes_opened == ["h1001"]

    async def test_search_only_mode_does_not_open_resumes(self, site, monkeypatch):
        monkeypatch.setattr(hh_parser.settings, "hh_open_resumes", False)

        resumes = await collect(FakeSiteParser(site))

        assert len(resumes) == 7
        assert site.resumes_opened == []
        assert resumes[0].data.skills == ["Python", "FastAPI"]

    async def test_respects_max_pages(self, site, monkeypatch):
        monkeypatch.setattr(hh_parser.settings, "hh_max_pages", 1)
        assert len(await collect(FakeSiteParser(site))) == 3

    async def test_resume_pages_spend_daily_budget(self, site, monkeypatch):
        monkeypatch.setattr(hh_parser.settings, "browser_daily_page_limit", 3)

        resumes = await collect(FakeSiteParser(site))

        assert len(resumes) == 2  # 1 страница поиска + 2 резюме — и тихая остановка до завтра
        keys = await redis.keys("browser:budget:hh:*")
        assert len(keys) == 1

    async def test_captcha_on_search_raises_blocked_with_screenshot(self, site, tmp_path):
        site.captcha_on_search_page = 1

        with pytest.raises(SourceBlockedError, match="капча") as exc:
            await collect(FakeSiteParser(site))

        assert "скриншот" in str(exc.value)
        assert list((tmp_path / "debug").glob("hh-*-blocked.png"))

    async def test_captcha_on_resume_page_raises_blocked(self, site):
        site.captcha_on_resume = "h1002"
        with pytest.raises(SourceBlockedError, match="капча"):
            await collect(FakeSiteParser(site))

    @pytest.mark.parametrize("status", [403, 429])
    async def test_block_status_raises_blocked(self, site, status):
        site.status = status
        with pytest.raises(SourceBlockedError, match=f"HTTP {status}"):
            await collect(FakeSiteParser(site))

    async def test_page_without_state_raises_blocked(self, site):
        site.no_state_on_page = 0
        with pytest.raises(SourceBlockedError, match="нет данных"):
            await collect(FakeSiteParser(site))

    async def test_required_login_without_session_asks_for_manual_login(self, site, monkeypatch):
        monkeypatch.setattr(hh_parser.settings, "hh_require_login", True)

        with pytest.raises(SourceBlockedError, match="browser-login hh"):
            await collect(FakeSiteParser(site))
        assert site.resumes_opened == []

    async def test_required_login_with_session_works(self, site, monkeypatch):
        monkeypatch.setattr(hh_parser.settings, "hh_require_login", True)
        assert len(await collect(FakeSiteParser(site, logged_in=True))) == 7

    async def test_is_logged_in_reads_user_type(self, site):
        for logged_in, expected in [(False, False), (True, True)]:
            parser = FakeSiteParser(site, logged_in=logged_in)
            try:
                page = await parser.open(search_url("python", 0))
                assert await parser.is_logged_in(page) is expected
            finally:
                await parser.close()


# --- вход из интерфейса: run_login + настоящий Chromium + человек-робот, отвечающий в канал ---

CANCEL = {"__cancel__": "1"}


async def wait_state(channel: LoginChannel, predicate: Callable[[LoginState], bool], timeout: float = 30) -> LoginState:
    async with asyncio.timeout(timeout):
        while True:
            state = await channel.get()
            if state and predicate(state):
                return state
            await asyncio.sleep(0.05)


async def drive_login(site: FakeHH, monkeypatch, answers: list[dict]) -> tuple[LoginState, list[LoginState]]:
    """Запускает вход и отвечает на вопросы по порядку. Возвращает итоговое состояние и все заданные вопросы."""
    from app.tasks import login as login_task

    monkeypatch.setattr(login_task, "create_parser", lambda source: FakeSiteParser(site))
    channel = LoginChannel(Source.HH)
    await channel.update(LoginStatus.QUEUED, started_by="Анна")
    asked: list[LoginState] = []

    async def human() -> None:
        seen = None
        for answer in answers:
            state = await wait_state(
                channel, lambda s, seen=seen: s.status == LoginStatus.NEED_INPUT and s.updated_at != seen
            )
            seen = state.updated_at
            asked.append(state)
            await (channel.cancel() if answer is CANCEL else channel.answer(answer))

    helper = asyncio.create_task(human())
    try:
        await asyncio.wait_for(login_task.run_login(Source.HH), 60)
    finally:
        helper.cancel()
    return await channel.get(), asked


@pytest.mark.usefixtures("chromium_available")
class TestUILogin:
    async def test_login_by_code_saves_session_and_unpauses_source(self, site, monkeypatch, session):
        from app.models import SourceHealth, SourceState
        from app.services.sources import set_health

        await set_health(session, Source.HH, SourceHealth.NEEDS_ATTENTION, "нет входа работодателя")

        final, asked = await drive_login(site, monkeypatch, [{"login": EMPLOYER_LOGIN}, {"value": EMPLOYER_CODE}])

        assert final.status == LoginStatus.DONE
        assert final.started_by == "Анна"
        assert [a.step for a in asked] == [LoginStep.LOGIN, LoginStep.CODE]
        assert all(a.screenshot.startswith("data:image/jpeg;base64,") for a in asked)
        assert asked[0].error is None
        assert site.login_attempts[-1] == {"login": EMPLOYER_LOGIN, "code": EMPLOYER_CODE}
        assert (hh_parser.settings.browser_state_dir / "hh.json").exists()
        state = await session.get(SourceState, Source.HH, populate_existing=True)
        assert state.health == SourceHealth.OK

    async def test_session_from_ui_login_is_used_by_collector(self, site, monkeypatch):
        await drive_login(site, monkeypatch, [{"login": EMPLOYER_LOGIN}, {"value": EMPLOYER_CODE}])
        monkeypatch.setattr(hh_parser.settings, "hh_require_login", True)

        resumes = await collect(FakeSiteParser(site))

        assert len(resumes) == 7
        assert resumes[0].data.full_name == "Тестов0 Иван"

    async def test_wrong_code_is_asked_again_with_hh_error(self, site, monkeypatch):
        final, asked = await drive_login(
            site, monkeypatch, [{"login": EMPLOYER_LOGIN}, {"value": "000000"}, {"value": EMPLOYER_CODE}]
        )

        assert final.status == LoginStatus.DONE
        assert [a.step for a in asked] == [LoginStep.LOGIN, LoginStep.CODE, LoginStep.CODE]
        assert (asked[1].error, asked[2].error) == (None, "Неверный код")

    async def test_unknown_login_is_asked_again(self, site, monkeypatch):
        final, asked = await drive_login(
            site, monkeypatch, [{"login": "nobody@example.com"}, {"login": EMPLOYER_LOGIN}, {"value": EMPLOYER_CODE}]
        )

        assert final.status == LoginStatus.DONE
        assert [a.step for a in asked] == [LoginStep.LOGIN, LoginStep.LOGIN, LoginStep.CODE]
        assert asked[1].error == "Аккаунт не найден"

    async def test_captcha_step(self, site, monkeypatch):
        site.login_captcha = True

        final, asked = await drive_login(
            site, monkeypatch, [{"login": EMPLOYER_LOGIN}, {"value": CAPTCHA_TEXT}, {"value": EMPLOYER_CODE}]
        )

        assert final.status == LoginStatus.DONE
        assert [a.step for a in asked] == [LoginStep.LOGIN, LoginStep.CAPTCHA, LoginStep.CODE]

    async def test_login_with_password(self, site, monkeypatch):
        final, asked = await drive_login(site, monkeypatch, [{"login": EMPLOYER_LOGIN, "password": EMPLOYER_PASSWORD}])

        assert final.status == LoginStatus.DONE
        assert [a.step for a in asked] == [LoginStep.LOGIN]
        assert site.login_attempts == [{"login": EMPLOYER_LOGIN, "password": EMPLOYER_PASSWORD}]

    async def test_cancel(self, site, monkeypatch):
        final, _ = await drive_login(site, monkeypatch, [CANCEL])
        assert final.status == LoginStatus.CANCELLED

    async def test_no_answer_times_out(self, site, monkeypatch):
        monkeypatch.setattr(hh_parser.settings, "browser_login_input_timeout", 1)

        final, _ = await drive_login(site, monkeypatch, [])

        assert final.status == LoginStatus.FAILED
        assert "не дождались" in final.error

    async def test_unexpected_page_fails_with_screenshot(self, site, monkeypatch):
        site.login_page_broken = True

        final, asked = await drive_login(site, monkeypatch, [])

        assert final.status == LoginStatus.FAILED
        assert "browser-login hh" in final.error
        assert final.screenshot.startswith("data:image/jpeg;base64,")
        assert asked == []

    async def test_cancelled_while_queued_does_not_open_browser(self, site, monkeypatch):
        from app.tasks import login as login_task

        channel = LoginChannel(Source.HH)
        await channel.update(LoginStatus.QUEUED)
        await channel.cancel()

        assert await login_task.run_login(Source.HH) == LoginStatus.CANCELLED
        assert site.visited == []
