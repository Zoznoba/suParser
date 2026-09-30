"""Разбор резюме из состояния страниц hh.ru (<template id="HH-Lux-InitialState">).

Приём из hh-stats: вместо вёрстки читаем JSON, который hh рендерит в страницу, — он стабильнее селекторов.
- страница поиска: resumeSearchResult.resumes — краткие карточки, поля обёрнуты в списки ([{"string": ...}]);
- страница резюме: resume — поля обёрнуты в {"value": ...}.

Анонимно hh скрывает ФИО, опыт, образование, фото и контакты (permission = view_without_contacts);
под аккаунтом работодателя с доступом к базе они заполнены. Структура опыта/образования у работодателя
живьём не проверена, поэтому ключи разбираются с запасными вариантами (как в официальном API).
Контакты не открываем никогда — на hh это платное действие.
id резюме = hash из URL, он же id в официальном API hh.
"""

import re
from datetime import UTC, date, datetime
from typing import Any

from app.models.enums import Source
from app.parsers.base import ParsedResume, ResumeData, WorkItem

SITE_URL = "https://hh.ru"

# служебные поля страницы резюме — в raw не сохраняем
NOISE_FIELDS = {"humanDatesRules", "creds", "fieldStatuses", "proftest", "hasUnpaidPfpTopics", "moderationNotes"}


# https://hh.ru/resume/<hash>, региональные поддомены (spb.hh.ru), параметры после ? не важны
RESUME_LINK = re.compile(r"^(?:https?://)?(?:[\w-]+\.)*hh\.ru/resume/([0-9a-z]+)/?(?:[?#].*)?$", re.IGNORECASE)


def resume_url(resume_hash: str) -> str:
    return f"{SITE_URL}/resume/{resume_hash}"


def parse_resume_link(url: str) -> str | None:
    """Ссылка на резюме hh → hash резюме, иначе None."""
    match = RESUME_LINK.match(url.strip())
    return match.group(1).lower() if match else None


def _value(resume: dict[str, Any], name: str) -> Any:
    """Поле страницы резюме: {"value": x, "type": "field", ...} → x."""
    field = resume.get(name)
    return field.get("value") if isinstance(field, dict) and "value" in field else field


def _first(items: Any, key: str = "string") -> Any:
    """Поле карточки поиска: [{"string": x}] → x."""
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return items[0].get(key)
    return None


def _strings(items: Any) -> list[str]:
    return [str(s) for i in items or [] if isinstance(i, dict) and (s := i.get("string") or i.get("name"))]


def _ms(value: Any) -> datetime | None:
    return datetime.fromtimestamp(value / 1000, UTC) if isinstance(value, int | float) and value else None


def _salary(salary: Any) -> tuple[int | None, str | None]:
    if isinstance(salary, list):
        salary = salary[0] if salary else None
    amount = (salary or {}).get("amount")
    if not amount:
        return None, None
    currency = (salary or {}).get("currency")
    return int(amount), "rub" if currency in (None, "RUR", "RUB") else currency.lower()


def _month(value: Any) -> str | None:
    """'2021-03-01' / '2021-03' / {"year": 2021, "month": 3} → '03.2021'."""
    if isinstance(value, dict):
        year, month = value.get("year"), value.get("month")
        return f"{int(month):02d}.{year}" if year and month else (str(year) if year else None)
    if not value:
        return None
    year, _, rest = str(value).partition("-")
    return f"{rest[:2]}.{year}" if rest else year


def _name(obj: Any) -> str | None:
    if isinstance(obj, dict):
        return obj.get("name") or obj.get("title")
    return obj or None


def _work(item: dict[str, Any]) -> WorkItem:
    start = _month(item.get("startDate") or item.get("start"))
    end = _month(item.get("endDate") or item.get("end"))
    return WorkItem(
        company=_name(item.get("companyName") or item.get("company")),
        position=item.get("position"),
        period=f"{start} — {end or 'н.в.'}" if start else None,
        description=item.get("description") or None,
    )


def _education(item: dict[str, Any]) -> str:
    parts = [item.get("name"), item.get("organization"), item.get("result")]
    text = ", ".join(str(p) for p in parts if p)
    return f"{item['year']} — {text}" if item.get("year") else text


def _photo(resume: dict[str, Any]) -> str | None:
    photo = _value(resume, "photoUrls") or _value(resume, "photo")
    if isinstance(photo, list):
        photo = photo[0] if photo else None
    if isinstance(photo, dict):
        photo = photo.get("big") or photo.get("medium") or photo.get("small") or photo.get("url")
    return photo if isinstance(photo, str) and photo else None


def _full_name(resume: dict[str, Any]) -> str | None:
    parts = [_value(resume, k) for k in ("lastName", "firstName", "middleName")]
    return " ".join(p for p in parts if isinstance(p, str) and p) or None


def _birth_date(resume: dict[str, Any]) -> date | None:
    """Поле birthday у работодателя живьём не проверено: ожидаем 'YYYY-MM-DD', иначе пропускаем."""
    value = _value(resume, "birthday")
    try:
        return date.fromisoformat(value[:10]) if isinstance(value, str) else None
    except ValueError:
        return None


def map_resume(resume: dict[str, Any]) -> ParsedResume:
    """Полное резюме со страницы /resume/<hash>."""
    resume_hash = _value(resume, "hash")
    salary, currency = _salary(_value(resume, "salary"))
    skills = _strings(_value(resume, "keySkills")) or _strings(_value(resume, "advancedKeySkills"))
    return ParsedResume(
        source=Source.HH,
        external_id=resume_hash,
        url=resume_url(resume_hash),
        published_at=_ms(_value(resume, "updated")),
        data=ResumeData(
            full_name=_full_name(resume),
            title=_value(resume, "title"),
            city=_name(_value(resume, "area")),
            age=_value(resume, "age") or None,
            birth_date=_birth_date(resume),
            salary=salary,
            currency=currency,
            photo_url=_photo(resume),
            about=_value(resume, "skills") or None,  # «Обо мне» в терминах hh
            experience=[_work(e) for e in _value(resume, "experience") or [] if isinstance(e, dict)],
            education=[_education(e) for e in _value(resume, "primaryEducation") or [] if isinstance(e, dict)],
            skills=skills,
        ),
        raw={
            "resume": {
                k: v for k in resume if k not in NOISE_FIELDS and (v := _value(resume, k)) not in (None, [], {}, "")
            },
            "via": "web",
        },
    )


def search_item_hash(item: dict[str, Any]) -> str | None:
    return (item.get("_attributes") or {}).get("hash")


def search_item_updated(item: dict[str, Any]) -> int | None:
    return (item.get("_attributes") or {}).get("updated")


def map_search_item(item: dict[str, Any]) -> ParsedResume:
    """Краткое резюме из карточки поиска — когда в само резюме не заходим (HH_OPEN_RESUMES=false)."""
    resume_hash = search_item_hash(item)
    salary, currency = _salary(item.get("salary"))
    return ParsedResume(
        source=Source.HH,
        external_id=resume_hash,
        url=resume_url(resume_hash),
        published_at=_ms(search_item_updated(item)),
        data=ResumeData(
            title=_first(item.get("title")),
            age=_first(item.get("age")) or None,
            salary=salary,
            currency=currency,
            skills=_strings(item.get("keySkills")),
        ),
        raw={"item": {k: v for k, v in item.items() if k != "negotiationLinks"}, "via": "web"},
    )
