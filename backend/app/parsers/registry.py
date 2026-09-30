from enum import StrEnum

from app.core.config import settings
from app.models.enums import Source
from app.parsers.base import SourceParser


class Queue(StrEnum):
    API = "api"  # лёгкие HTTP-парсеры
    BROWSER = "browser"  # Playwright: отдельный воркер, concurrency 1


# источники, которые уже реализованы и могут запускаться планировщиком; LinkedIn — только с токеном Apify
ENABLED_SOURCES: set[Source] = {Source.SUPERJOB, Source.HH} | ({Source.LINKEDIN} if settings.apify_token else set())
# браузерные источники, в которые можно войти из интерфейса (BrowserParser.ui_login)
UI_LOGIN_SOURCES: set[Source] = {Source.HH}


def queue_for(source: Source) -> Queue:
    if source == Source.SUPERJOB and settings.superjob_mode != "browser":
        return Queue.API
    if source == Source.LINKEDIN:  # Apify: браузер крутится у них, у нас — один HTTP-запрос
        return Queue.API
    return Queue.BROWSER


def create_parser(source: Source) -> SourceParser:
    match source:
        case Source.SUPERJOB if settings.superjob_mode == "browser":
            from app.parsers.superjob.web_parser import SuperJobWebParser

            return SuperJobWebParser()
        case Source.SUPERJOB:
            from app.parsers.superjob.parser import SuperJobParser

            return SuperJobParser()
        case Source.HH:
            from app.parsers.hh.parser import HHParser

            return HHParser()
        case Source.LINKEDIN:
            from app.parsers.linkedin.parser import LinkedInParser

            return LinkedInParser()
