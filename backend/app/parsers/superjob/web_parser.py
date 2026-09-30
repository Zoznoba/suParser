import logging
import re
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from app.core.config import settings
from app.models.enums import Source
from app.parsers.base import ParsedResume, SearchQuery
from app.parsers.browser.base import BrowserParser
from app.parsers.superjob.web_mapper import SITE_URL, map_web_resume

if TYPE_CHECKING:
    from playwright.async_api import Page

log = logging.getLogger(__name__)

SEARCH_URL = f"{SITE_URL}/resume/search_resume.html"
RESUME_HREF = re.compile(r"/resume/[^/?#]*?-?(\d+)\.html")
CAPTCHA_MARKERS = ("captcha", "smartcaptcha", "Я не робот", "подтвердите, что вы не робот")

# ссылки на резюме со страницы: id → абсолютный url
LINKS_JS = """els => els.map(e => e.getAttribute('href')).filter(Boolean)"""


def search_url(keywords: str, page: int) -> str:
    params: dict[str, Any] = {"keywords[0][keys]": keywords}
    if page > 1:
        params["page"] = page
    return f"{SEARCH_URL}?{urlencode(params)}"


class SuperJobWebParser(BrowserParser):
    """superjob.ru через Playwright — временная замена API, пока приложение не верифицировано.

    Логин/пароль работодателя (SUPERJOB_LOGIN/PASSWORD) — чтобы видеть ФИО и закрытые резюме.
    Без них поиск тоже работает, но только по открытой части базы.
    """

    source = Source.SUPERJOB
    login_url = f"{SITE_URL}/auth/login/"
    password_step_timeout_ms = 15_000
    login_redirect_timeout_ms = 20_000

    async def search(self, query: SearchQuery) -> AsyncIterator[ParsedResume]:
        keywords = query.keywords or query.title
        logged_in_checked = False
        for page_no in range(1, settings.superjob_web_max_pages + 1):
            if not await self.take_budget():
                return
            page = await self.open(search_url(keywords, page_no))

            if not logged_in_checked and settings.superjob_login:
                logged_in_checked = True
                if not await self.is_logged_in(page):
                    await self.login()
                    if not await self.take_budget():
                        return
                    page = await self.open(search_url(keywords, page_no))

            state = await page.evaluate("() => window.APP_STATE ?? null")
            if not state or "entities" not in state:
                await self.blocked(f"на странице поиска нет данных — капча или изменилась вёрстка ({page.url})")

            ids: list[str] = state.get("ids", {}).get("RESUME_SEARCH_RESULT") or []
            links = self._resume_links(await page.eval_on_selector_all("a[href*='/resume/']", LINKS_JS))
            for resume_id in ids:
                try:
                    yield map_web_resume(state["entities"], resume_id, links.get(resume_id))
                except Exception:
                    log.exception("superjob web: cannot map resume %s", resume_id)

            meta = state.get("metas", {}).get("RESUME_SEARCH_RESULT") or {}
            if not ids or meta.get("offset", 0) + len(ids) >= meta.get("total", 0):
                break
            await self.scroll_like_human()

    @staticmethod
    def _resume_links(hrefs: list[str]) -> dict[str, str]:
        links = {}
        for href in hrefs:
            if (m := RESUME_HREF.search(href)) and "search_resume" not in href:
                links.setdefault(m.group(1), href if href.startswith("http") else f"{SITE_URL}{href}")
        return links

    async def login(self) -> None:
        """Вход работодателя: «Ищу сотрудников» → email/телефон → «Продолжить» → пароль.

        Если вместо пароля просят код из SMS/почты — автоматически не входим, нужен ручной вход:
            python -m app.cli browser-login superjob
        """
        if not await self.take_budget():
            await self.blocked("дневной бюджет страниц исчерпан до входа")
        page = await self.open(self.login_url)
        employer_tab = page.get_by_text("Ищу сотрудников", exact=True)
        if await employer_tab.count():
            await employer_tab.first.click()
            await self.pause(0.8, 2.0)
        await self.type_like_human("input[name='login']", settings.superjob_login or "")
        await self.pause(0.5, 1.5)
        await page.get_by_role("button", name="Продолжить").click()

        password = page.locator("input[type='password']")
        try:
            await password.wait_for(state="visible", timeout=self.password_step_timeout_ms)
        except Exception:
            if await self.is_captcha(page):
                await self.blocked("капча при входе")
            await self.blocked(
                "вместо пароля SuperJob просит код подтверждения — "
                "выполните ручной вход: python -m app.cli browser-login superjob"
            )
        await self.type_like_human("input[type='password']", settings.superjob_password or "")
        await self.pause(0.5, 1.5)
        await page.keyboard.press("Enter")

        try:
            await page.wait_for_url(lambda url: "/auth/" not in url, timeout=self.login_redirect_timeout_ms)
        except Exception:
            await self.blocked("не удалось войти: проверьте SUPERJOB_LOGIN / SUPERJOB_PASSWORD")
        await self.pause(1.5, 3.0)
        await self.save_state()
        log.info("superjob web: logged in")

    async def is_logged_in(self, page: "Page") -> bool:
        if "/auth/" in page.url:
            return False
        return await page.locator("a[href^='/auth/login']").count() == 0

    async def is_captcha(self, page: "Page") -> bool:
        if "captcha" in page.url:
            return True
        if await page.locator("iframe[src*='captcha'], [class*='captcha' i], [id*='captcha' i]").count():
            return True
        text = (await page.title()).lower()
        return any(marker.lower() in text for marker in CAPTCHA_MARKERS)
