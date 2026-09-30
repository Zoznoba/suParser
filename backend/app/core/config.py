import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # тесты не читают локальный .env: там реальные токены (APIFY_TOKEN включает LinkedIn) и боевые режимы
    model_config = SettingsConfigDict(
        env_file=None if os.getenv("ENVIRONMENT") == "test" else ".env", env_ignore_empty=True, extra="ignore"
    )

    environment: str = "dev"  # dev | prod | test

    database_url: str = "postgresql+asyncpg://hr:hr@localhost:5432/hr"
    redis_url: str = "redis://localhost:6379/0"

    session_ttl_seconds: int = 60 * 60 * 24 * 7
    session_cookie_name: str = "hr_session"
    cookie_secure: bool = False

    # SuperJob API: https://api.superjob.ru/
    superjob_app_id: int | None = None  # client_id
    superjob_secret: str | None = None  # X-Api-App-Id / client_secret
    superjob_login: str | None = None  # аккаунт работодателя
    superjob_password: str | None = None
    # mock — фейковые резюме; api — официальный API (нужны app id/secret);
    # browser — сайт superjob.ru через Playwright (пока API-приложение не верифицировано)
    superjob_mode: Literal["mock", "api", "browser"] = "mock"
    superjob_max_pages: int = 5  # API: страниц по 100 резюме за один запуск профиля
    superjob_web_max_pages: int = 3  # сайт: страниц по ~30 резюме за один запуск профиля

    # hh.ru через Playwright; вход работодателя — из интерфейса (кнопка «Войти») или python -m app.cli browser-login hh
    hh_max_pages: int = 2  # страниц поиска по 20 резюме за один запуск профиля
    # только резюме, обновлённые за последние N дней (0 — все), отсортированные по релевантности:
    # и свежие, и без шума (сортировка по дате при поиске по полному тексту тащит нерелевантные резюме)
    hh_search_period_days: Literal[0, 1, 3, 7, 14, 30, 365] = 3
    hh_open_resumes: bool = True  # заходить в каждое новое резюме (полные данные, +1 страница бюджета за резюме)
    hh_require_login: bool = True  # без сессии работодателя источник встаёт на паузу, а не собирает урезанные резюме
    hh_resume_cache_days: int = 7  # не открывать повторно резюме, которое не менялось

    @field_validator("hh_search_period_days", mode="before")
    @classmethod
    def _period_from_env(cls, value: object) -> object:
        # из .env приходит строка "3", а Literal[int] её к числу не приводит
        return int(value) if isinstance(value, str) and value.strip().isdigit() else value

    # LinkedIn через Apify (актор harvestapi/linkedin-profile-search, без аккаунта LinkedIn): https://console.apify.com
    # без токена источник выключен. Актор платный по событиям: $0.10 за страницу поиска (до 25 профилей),
    # в Full — ещё $0.004 за профиль; бесплатный план Apify — $5 кредитов в месяц
    apify_token: str | None = None
    linkedin_actor: str = "harvestapi~linkedin-profile-search"
    linkedin_profile_mode: Literal["Short", "Full"] = "Short"  # Short — только выдача; Full — опыт, навыки, образование
    linkedin_location: str | None = None  # фильтр «где живёт», как в LinkedIn: "Russia", "Moscow"
    linkedin_max_pages: int = 1  # страниц поиска по 25 профилей за один запуск профиля
    linkedin_daily_page_limit: int = 1  # страниц в сутки на все профили — держит расход в бесплатных $5/мес
    linkedin_run_timeout: int = 280  # секунд на синхронный запуск актора (у Apify предел 300)

    # браузерные парсеры: темп «как человек» и жёсткий дневной бюджет, чтобы не словить блокировку
    browser_headless: bool = True
    browser_state_dir: Path = Path(".browser-state")  # сессии (cookies) и скриншоты при блокировках
    browser_min_delay: float = 8.0  # секунд между переходами по страницам
    browser_max_delay: float = 20.0
    browser_daily_page_limit: int = 150  # страниц в сутки на один источник
    browser_login_input_timeout: int = 300  # вход из интерфейса: сколько секунд ждать ответа человека на шаге

    # как часто планировщик проверяет, каким профилям пора собирать анкеты
    dispatch_cron: str = "* * * * *"

    # анкета неактуальна, если все её резюме сняты с площадок (404) или не попадались в поиске столько дней
    stale_after_days: int = 2
    stale_cron: str = "*/15 * * * *"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
