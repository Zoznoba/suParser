"""Профиль LinkedIn из актора harvestapi/linkedin-profile-search → ParsedResume.

Short (снято с живого запуска): id/profileIdInSearch вида "ACwAA…", ссылка /in/<тот же id> (slug не отдаётся),
firstName/lastName, summary («О себе»), currentPositions[] (title, companyName, startedOn, description),
pictureUrl, location.linkedinText. Заголовка профиля (headline) в Short нет — должность берём из текущей позиции.
Full (по документации актора): ещё publicIdentifier, headline, photo, experience[], education[], skills[].
Месяц в датах актор отдаёт то числом (1), то сокращением ("Aug") — понимаем оба.
"""

from typing import Any
from urllib.parse import unquote

from app.models.enums import Source
from app.parsers.base import ParsedResume, ResumeData, WorkItem

SITE_URL = "https://www.linkedin.com"
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


def profile_id(item: dict[str, Any]) -> str | None:
    """id из поиска — он есть в любом режиме и не меняется, когда человек правит адрес профиля; slug — запасной."""
    if item.get("profileIdInSearch") or item.get("id"):
        return item.get("profileIdInSearch") or item.get("id")
    slug = item.get("publicIdentifier")
    return unquote(slug).lower() if slug else None


def _month(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return MONTHS.get(value[:3].lower()) or (int(value) if value.isdigit() else None)
    return None


def _date(value: Any) -> str | None:
    if not isinstance(value, dict) or not value.get("year"):
        return None
    month = _month(value.get("month"))
    return f"{month:02d}.{value['year']}" if month else str(value["year"])


def _period(item: dict[str, Any]) -> str | None:
    start = _date(item.get("startDate") or item.get("startedOn"))
    if not start:
        return item.get("period") or item.get("duration")
    return f"{start} — {_date(item.get('endDate')) or 'н.в.'}"


def _city(location: Any) -> str | None:
    if isinstance(location, dict):
        if city := (location.get("parsed") or {}).get("city"):
            return city
        location = location.get("linkedinText")
    if isinstance(location, str):  # "Pyatigorsk, Stavropol, Russia" или просто "Russia"
        return location.split(",")[0].strip() or None
    return None


def _skill(value: Any) -> str | None:
    return value.get("name") if isinstance(value, dict) else value


def _work(w: dict[str, Any]) -> WorkItem:
    return WorkItem(
        company=w.get("companyName"),
        position=w.get("position") or w.get("title"),
        period=_period(w),
        description=w.get("description"),
    )


def map_profile(item: dict[str, Any]) -> ParsedResume:
    external_id = profile_id(item)
    if not external_id:
        raise ValueError("профиль без id")
    name = " ".join(p for p in (item.get("firstName"), item.get("lastName")) if p)
    jobs = [w for w in item.get("experience") or item.get("currentPositions") or [] if isinstance(w, dict)]
    current = [w for w in item.get("currentPositions") or [] if isinstance(w, dict)]
    title = item.get("headline") or (current[0].get("title") if current else None)
    photo = item.get("photo") or item.get("pictureUrl")
    return ParsedResume(
        source=Source.LINKEDIN,
        external_id=external_id,
        url=item.get("linkedinUrl") or f"{SITE_URL}/in/{external_id}",
        data=ResumeData(
            full_name=name or None,
            title=title,
            city=_city(item.get("location")),
            photo_url=photo if isinstance(photo, str) else None,
            about=item.get("about") or item.get("summary"),
            experience=[_work(w) for w in jobs],
            education=[
                ", ".join(p for p in (e.get("schoolName"), e.get("degree"), e.get("fieldOfStudy"), _period(e)) if p)
                for e in item.get("education") or []
                if isinstance(e, dict)
            ],
            skills=[s for s in map(_skill, item.get("skills") or []) if s],
        ),
        raw={k: v for k, v in item.items() if k != "_meta"} | {"via": "apify"},
    )
