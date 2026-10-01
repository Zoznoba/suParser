import asyncio
import base64
import logging
import random
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from app.core.config import settings
from app.core.redis import redis
from app.models.enums import Source
from app.parsers.base import PageGoneError, ParsedResume, SearchQuery
from app.parsers.browser.base import BrowserParser
from app.parsers.browser.login import LoginChannel, LoginFailed, LoginStep
from app.parsers.hh.mapper import (
    SITE_URL,
    map_resume,
    map_search_item,
    resume_url,
    search_item_hash,
    search_item_updated,
)

if TYPE_CHECKING:
    from playwright.async_api import Page

log = logging.getLogger(__name__)

SEARCH_URL = f"{SITE_URL}/search/resume"
EMPLOYER = "employer"
CAPTCHA_MARKERS = ("captcha", "Я не робот", "подтвердите, что вы не робот")

# вход работодателя: «Я ищу сотрудников» → почта/телефон → «Дальше» (код) или «Войти с паролем».
# Первые шаги сняты с живой страницы; поля кода и капчи hh показывает только после отправки логина,
# поэтому для них селекторы с запасом — при непонятной странице вход падает со скриншотом.
EMPLOYER_CARD = "[data-qa='account-type-card-EMPLOYER']"
ROLE_SUBMIT = "[data-qa='submit-button']"
USERNAME = "[data-qa='login-input-username']"
BY_CODE = "[data-qa='account-login-submit-by-code']"
BY_PASSWORD = "[data-qa='account-login-submit-by-password']"
PASSWORD = "input[type='password']"
CODE_INPUT = "input[data-qa*='code' i], input[autocomplete='one-time-code'], input[name*='code' i]"
CAPTCHA_IMAGE = "img[data-qa*='captcha' i], img[src*='captcha']"
CAPTCHA_INPUT = "input[data-qa*='captcha' i], input[name*='captcha' i]"
FORM_ERROR = "[data-qa='form-helper-error'], [data-qa*='error-text' i], [role='alert']"
LOGIN_PROMPTS = {
    LoginStep.LOGIN: "Почта или телефон аккаунта работодателя на hh.ru",
    LoginStep.CODE: "Код подтверждения из SMS или письма от hh.ru",
    LoginStep.CAPTCHA: "Символы с картинки",
}
STEP_FIELDS = {LoginStep.LOGIN: USERNAME, LoginStep.CODE: CODE_INPUT, LoginStep.CAPTCHA: CAPTCHA_INPUT}
MAX_LOGIN_STEPS = 8
MANUAL_LOGIN = "войдите вручную: python -m app.cli browser-login hh"

# из огромного состояния страницы (~0.5 МБ) забираем только нужное
STATE_JS = """() => {
  const t = document.getElementById('HH-Lux-InitialState');
  if (!t) return null;
  const s = JSON.parse(t.content ? t.content.textContent : t.textContent);
  return {userType: s.userType ?? null, search: s.resumeSearchResult ?? null, resume: s.resume ?? null};
}"""


def search_url(keywords: str, page: int) -> str:
    # без тройки logic/pos/exp_period (с допустимыми значениями) hh молча игнорирует text и отдаёт всю базу
    params: dict[str, Any] = {
        "text": keywords,
        "logic": "normal",
        "pos": "full_text",
        "exp_period": "all_time",
        "order_by": "relevance",
    }
    if settings.hh_search_period_days:
        params["search_period"] = settings.hh_search_period_days
    if page > 0:  # на hh страницы с нуля
        params["page"] = page
    return f"{SEARCH_URL}?{urlencode(params)}"


class HHParser(BrowserParser):
    """hh.ru через Playwright: поиск резюме → страница каждого нового/обновлённого резюме.

    Вход работодателя — из интерфейса (ui_login: человек вводит логин, код, капчу по скриншотам)
    или вручную на машине с экраном: python -m app.cli browser-login hh.
    Без входа поиск работает, но hh отдаёт урезанные резюме (без ФИО, опыта и образования);
    с HH_REQUIRE_LOGIN=true отсутствие/истечение сессии ставит источник на паузу.

    Страница резюме стоит одну страницу дневного бюджета, поэтому уже разобранное резюме кешируется
    в Redis по (hash, время обновления): пока кандидат его не менял, повторно не открываем.
    """

    source = Source.HH
    login_url = f"{SITE_URL}/account/login?backurl=%2Femployer"
    login_step_polls = 10  # секунд ждать, пока на странице входа появится понятный шаг

    async def search(self, query: SearchQuery) -> AsyncIterator[ParsedResume]:
        keywords = query.keywords or query.title
        login_checked = False
        for page_no in range(settings.hh_max_pages):
            if not await self.take_budget():
                return
            page = await self.open(search_url(keywords, page_no))
            state = await self.read_state(page)
            if not state or not state.get("search"):
                await self.blocked(f"на странице поиска нет данных — капча или изменилась вёрстка ({page.url})")
            if not login_checked:
                login_checked = True
                await self.check_login(state)

            result = state["search"]
            items = [i for i in result.get("resumes") or [] if search_item_hash(i) and not i.get("forbidden")]
            if items:
                await self.scroll_like_human()
            for item in items:
                if not settings.hh_open_resumes:
                    try:
                        yield map_search_item(item)
                    except Exception:
                        log.exception("hh: cannot map search item %s", search_item_hash(item))
                    continue
                try:
                    resume = await self.fetch_resume(search_item_hash(item), search_item_updated(item))
                except PageGoneError:  # соискатель удалил или скрыл резюме, пока мы листали выдачу
                    self.gone = (*self.gone, search_item_hash(item))
                    continue
                if resume is None:  # бюджет на сегодня исчерпан
                    return
                yield resume

            next_page = (result.get("paging") or {}).get("next") or {}
            if not items or next_page.get("disabled", True):
                break

    async def fetch_resume(self, resume_hash: str, updated: int | None) -> ParsedResume | None:
        key = f"hh:resume:{resume_hash}:{updated}"
        if updated and (cached := await redis.get(key)):
            return ParsedResume.model_validate_json(cached)
        if not await self.take_budget():
            return None
        page = await self.open(resume_url(resume_hash))
        state = await self.read_state(page)
        if not state or not state.get("resume"):
            await self.blocked(f"на странице резюме нет данных — капча или изменилась вёрстка ({page.url})")
        resume = map_resume(state["resume"])
        if updated:
            await redis.set(key, resume.model_dump_json(), ex=settings.hh_resume_cache_days * 24 * 60 * 60)
        return resume

    async def read_state(self, page: "Page") -> dict[str, Any] | None:
        try:
            return await page.evaluate(STATE_JS)
        except Exception as e:
            if "context was destroyed" in str(e):  # страница как раз переходит дальше (шаги входа) — это не ошибка
                log.debug("hh: page navigated while reading state on %s", page.url)
            else:
                log.exception("hh: cannot read page state on %s", page.url)
            return None

    async def check_login(self, state: dict[str, Any]) -> None:
        if state.get("userType") == EMPLOYER:
            return
        if settings.hh_require_login:
            await self.blocked("нет входа работодателя — нажмите «Войти» (или python -m app.cli browser-login hh)")
        log.warning("hh: not logged in as employer (userType=%s), resumes will be partial", state.get("userType"))

    async def is_logged_in(self, page: "Page") -> bool:
        state = await self.read_state(page)
        return bool(state) and state.get("userType") == EMPLOYER

    async def is_captcha(self, page: "Page") -> bool:
        if "captcha" in page.url:
            return True
        if await page.locator("[data-qa*='captcha' i], img[src*='captcha'], iframe[src*='captcha']").count():
            return True
        text = (await page.title()).lower()
        return any(marker.lower() in text for marker in CAPTCHA_MARKERS)

    # --- вход из интерфейса ---

    async def ui_login(self, channel: LoginChannel) -> None:
        page = await self.page()
        await page.goto(self.login_url, wait_until="domcontentloaded")
        await self.pause(1.5, 3.0)
        last_step: LoginStep | None = None
        for _ in range(MAX_LOGIN_STEPS):
            step = await self.login_step(page)
            if step == "done":
                await self.save_state()
                return
            if step is None:
                raise LoginFailed(f"hh показал неожиданную страницу — {MANUAL_LOGIN}")
            error = None
            if step == last_step:  # тот же шаг второй раз подряд — hh не принял ответ (неверный код, логин, символы)
                error = await self.login_error(page) or "hh не принял ответ, попробуйте ещё раз"
            answer = await channel.ask(step, LOGIN_PROMPTS[step], await self.snapshot(), error)
            error_before = await self.login_error(page)
            await self.submit_login_step(page, step, answer)
            last_step = step
            field = PASSWORD if step == LoginStep.LOGIN and answer.get("password") else STEP_FIELDS[step]
            await self.wait_login_reaction(page, field, error_before)
        raise LoginFailed(f"слишком много шагов входа — {MANUAL_LOGIN}")

    async def login_step(self, page: "Page") -> LoginStep | str | None:
        """Какой шаг входа сейчас на странице. Выбор «работодатель» проходим сами, без человека."""
        for _ in range(self.login_step_polls):
            if "/account/login" not in page.url and await self.is_logged_in(page):
                return "done"
            if await self.visible(page, CAPTCHA_IMAGE):
                return LoginStep.CAPTCHA
            if await self.visible(page, CODE_INPUT):
                return LoginStep.CODE
            if await self.visible(page, USERNAME) or await self.visible(page, PASSWORD):
                return LoginStep.LOGIN
            if await self.visible(page, EMPLOYER_CARD, attached=True):
                await page.locator(EMPLOYER_CARD).check(force=True)
                await self.pause(0.5, 1.2)
                await page.locator(ROLE_SUBMIT).click()
            await asyncio.sleep(1)
        return None

    async def wait_login_reaction(
        self, page: "Page", field: str, error_before: str | None, timeout: float = 20
    ) -> None:
        """Ждёт, пока hh отреагирует на ответ: переход, новая ошибка или исчезло поле, в которое печатали.
        Без этого старое поле, ещё не успевшее исчезнуть, выглядело бы как «hh не принял ответ»."""
        url = page.url
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(0.3)
            try:
                if page.url != url or not await self.visible(page, field):
                    break
                if await self.login_error(page) not in (None, error_before):
                    break
            except Exception:  # страница в процессе перехода
                continue
        await self.pause(1.0, 2.0)

    async def submit_login_step(self, page: "Page", step: LoginStep, answer: dict[str, str]) -> None:
        match step:
            case LoginStep.LOGIN:
                if await self.visible(page, USERNAME):
                    await page.locator(USERNAME).fill("")
                    await self.type_like_human(USERNAME, answer.get("login", ""))
                if password := answer.get("password"):
                    if not await self.visible(page, PASSWORD):
                        await page.locator(BY_PASSWORD).click()
                        await page.locator(PASSWORD).first.wait_for(state="visible", timeout=10_000)
                    await self.type_into(page, PASSWORD, password)
                    await page.keyboard.press("Enter")
                else:
                    await page.locator(BY_CODE).click()
            case LoginStep.CODE:
                await self.type_into(page, CODE_INPUT, answer.get("value", ""))
                await page.keyboard.press("Enter")
            case LoginStep.CAPTCHA:
                await self.type_into(page, CAPTCHA_INPUT, answer.get("value", ""))
                await page.keyboard.press("Enter")

    async def type_into(self, page: "Page", selector: str, text: str) -> None:
        """Печатает в первое видимое поле; код из нескольких ячеек hh перещёлкивает сам."""
        field = page.locator(selector).locator("visible=true").first
        await field.click()
        await field.fill("")
        await page.keyboard.type(text.strip(), delay=random.randint(80, 160))

    @staticmethod
    async def visible(page: "Page", selector: str, attached: bool = False) -> bool:
        loc = page.locator(selector)
        if attached:  # радиокнопки hh спрятаны под карточками
            return await loc.count() > 0
        return await loc.locator("visible=true").count() > 0

    async def login_error(self, page: "Page") -> str | None:
        texts = [t.strip() for t in await page.locator(FORM_ERROR).locator("visible=true").all_inner_texts()]
        return "; ".join(t for t in texts if t) or None

    async def snapshot(self) -> str | None:
        if self._page is None:
            return None
        try:
            png = await self._page.screenshot(type="jpeg", quality=70)
        except Exception:
            return None
        return "data:image/jpeg;base64," + base64.b64encode(png).decode()
