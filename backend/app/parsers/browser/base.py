"""База для парсеров, которые ходят через браузер (SuperJob-сайт, hh.ru).

Главное правило — вести себя как человек и лучше недобрать, чем получить блокировку:
- постоянная сессия: storage_state (cookies) сохраняется на диск и переиспользуется между запусками;
- один браузер на источник (очередь browser, concurrency 1) + Redis-lock в сборщике;
- случайные паузы между переходами, прокрутка страницы, реальный User-Agent, локаль и часовой пояс;
- дневной бюджет страниц на источник (Redis-счётчик): исчерпан — сбор тихо останавливается до завтра;
- капча / 403 / 429 / странная страница → скриншот + SourceBlockedError → источник needs_attention,
  дальше задачи по нему не запускаются, пока человек не разберётся и не нажмёт «продолжить» в интерфейсе.

Playwright импортируется лениво: он нужен только browser-воркеру (extra `browser`).
"""

import asyncio
import logging
import random
from abc import abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.config import settings
from app.core.redis import redis
from app.parsers.base import PageGoneError, SourceBlockedError, SourceParser

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright

    from app.parsers.browser.login import LoginChannel

log = logging.getLogger(__name__)

BLOCK_STATUSES = {403, 429}
GONE_STATUSES = {404, 410}


class BrowserParser(SourceParser):
    login_url: str

    def __init__(self, headless: bool | None = None, anonymous: bool = False) -> None:
        self.headless = settings.browser_headless if headless is None else headless
        # anonymous — чистый браузер без сохранённой сессии аккаунта (ручной импорт, когда аккаунт заблокирован)
        self.anonymous = anonymous
        self.min_delay = settings.browser_min_delay
        self.max_delay = settings.browser_max_delay
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._navigated = False

    # --- сессия и браузер ---

    @property
    def state_path(self) -> Path:
        return settings.browser_state_dir / f"{self.source}.json"

    async def page(self) -> "Page":
        if self._page is None:
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
            # channel="chromium" — полноценный Chromium в новом headless-режиме (headless shell легко распознать)
            # видимое окно (ручной вход) — развёрнутым на весь экран, а не маленьким окном по умолчанию
            args = [] if self.headless else ["--start-maximized"]
            self._browser = await self._pw.chromium.launch(headless=self.headless, channel="chromium", args=args)
            # убираем "HeadlessChrome" из User-Agent, остальное — как у обычного Chrome на десктопе
            ua = (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{self._browser.version} Safari/537.36"
            )
            # без окна — «экран» типичного ноутбука; в видимом окне страница просто занимает всё окно
            # (с фиксированным viewport она обрезалась бы или не растягивалась вместе с окном)
            screen: dict[str, Any] = (
                {"viewport": {"width": random.choice([1366, 1440, 1536]), "height": random.choice([800, 864, 900])}}
                if self.headless
                else {"no_viewport": True}
            )
            self._context = await self._browser.new_context(
                storage_state=self.state_path if not self.anonymous and self.state_path.exists() else None,
                user_agent=ua,
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                **screen,
            )
            self._page = await self._context.new_page()
        return self._page

    async def save_state(self) -> None:
        if self._context and not self.anonymous:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            await self._context.storage_state(path=self.state_path)

    async def close(self) -> None:
        try:
            await self.save_state()
        finally:
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()

    # --- навигация «как человек» ---

    async def pause(self, min_delay: float | None = None, max_delay: float | None = None) -> None:
        await asyncio.sleep(random.uniform(min_delay or self.min_delay, max_delay or self.max_delay))

    async def take_budget(self) -> bool:
        """Списывает одну страницу из дневного бюджета источника. False — бюджет на сегодня исчерпан."""
        key = f"browser:budget:{self.source}:{datetime.now(UTC).date()}"
        used = await redis.incr(key)
        await redis.expire(key, 60 * 60 * 48)
        if used > settings.browser_daily_page_limit:
            log.warning("%s: daily page budget (%d) exhausted", self.source, settings.browser_daily_page_limit)
            self.complete = False
            return False
        return True

    async def open(self, url: str) -> "Page":
        """Единственная точка перехода по страницам: пауза, переход, проверка на блокировку."""
        page = await self.page()
        if self._navigated:
            await self.pause()
        self._navigated = True
        resp = await page.goto(url, wait_until="domcontentloaded")
        await self.pause(1.5, 3.5)  # даём догрузиться скриптам, как живой пользователь
        if resp and resp.status in GONE_STATUSES:
            raise PageGoneError(url)
        if (resp and resp.status in BLOCK_STATUSES) or await self.is_captcha(page):
            await self.blocked(f"капча или блокировка (HTTP {resp.status if resp else '?'}) на {page.url}")
        return page

    async def scroll_like_human(self) -> None:
        page = await self.page()
        for _ in range(random.randint(2, 5)):
            await page.mouse.wheel(0, random.randint(300, 900))
            await self.pause(0.4, 1.5)

    async def type_like_human(self, selector: str, text: str) -> None:
        page = await self.page()
        await page.locator(selector).click()
        await page.locator(selector).press_sequentially(text, delay=random.randint(60, 160))

    async def blocked(self, reason: str) -> None:
        """Фиксирует блокировку: скриншот для разбора и SourceBlockedError."""
        shot = await self.screenshot("blocked")
        raise SourceBlockedError(f"{self.source}: {reason}" + (f" (скриншот: {shot})" if shot else ""))

    async def screenshot(self, name: str) -> Path | None:
        if self._page is None:
            return None
        path = settings.browser_state_dir / "debug" / f"{self.source}-{datetime.now():%Y%m%d-%H%M%S}-{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await self._page.screenshot(path=path)
        except Exception:
            return None
        return path

    # --- ручной вход (CLI) ---

    async def interactive_login(self, timeout: float = 600, notify: Callable[[str], None] = print) -> None:
        """Открывает видимый браузер, человек входит сам (пароль, код из SMS/почты, капча), сессия сохраняется."""
        from playwright.async_api import TimeoutError as PlaywrightTimeout

        page = await self.page()
        try:
            # не ждём "load": на hh он не наступает и за 30 с (счётчики, реклама) — goto падал и закрывал окно
            await page.goto(self.login_url, wait_until="domcontentloaded", timeout=60_000)
        except PlaywrightTimeout:
            notify("Страница входа грузится медленно — дождитесь её или обновите (F5), окно не закроется.")
        notify(f"Войдите в аккаунт в открывшемся окне браузера (ждём до {int(timeout // 60)} мин)…")
        async with asyncio.timeout(timeout):
            while True:
                await asyncio.sleep(2)
                try:
                    if await self.is_logged_in(page):
                        break
                except Exception:  # страница в процессе перехода
                    continue
        await self.save_state()
        notify(f"Готово, сессия сохранена в {self.state_path}")

    async def ui_login(self, channel: "LoginChannel") -> None:
        """Вход из интерфейса по шагам (см. browser.login). Площадки с поддержкой — registry.UI_LOGIN_SOURCES."""
        raise NotImplementedError

    # --- специфика площадки ---

    @abstractmethod
    async def is_captcha(self, page: "Page") -> bool: ...

    @abstractmethod
    async def is_logged_in(self, page: "Page") -> bool: ...
