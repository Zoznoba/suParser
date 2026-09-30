"""Разбор резюме из window.APP_STATE страницы поиска superjob.ru.

Состояние нормализовано в стиле JSON:API: entities[type][id] = {attributes, relationships}.
Страница поиска уже содержит почти всё резюме (должность, опыт, зарплату, «о себе»),
поэтому в каждое резюме отдельно не заходим — меньше запросов, меньше риск блокировки.
id резюме совпадает с id в официальном API: после перехода на API дублей не будет.

ФИО и контакты скрыты даже под аккаунтом работодателя, пока не пополнен баланс
(relationships.person = {"data": null, "meta": {"hidden": true}}). Для склейки дублей есть:
- ownerActivity — id аккаунта соискателя, общий для всех его резюме;
- resumeBirthDate.birthDate — точная дата рождения (если соискатель её не скрыл).
"""

import re
from datetime import date, datetime
from typing import Any

from app.models.enums import Source
from app.parsers.base import ParsedResume, ResumeData, WorkItem

Entities = dict[str, dict[str, dict[str, Any]]]

SITE_URL = "https://www.superjob.ru"


def _rel(entities: Entities, entity: dict[str, Any], name: str) -> Any:
    """Разворачивает relationship: одну сущность или список сущностей (без отсутствующих)."""
    data = (entity.get("relationships", {}).get(name) or {}).get("data")
    if isinstance(data, list):
        return [e for ref in data if (e := entities.get(ref["type"], {}).get(ref["id"]))]
    if isinstance(data, dict):
        return entities.get(data["type"], {}).get(data["id"])
    return None


def _attr(entity: dict[str, Any] | None, name: str) -> Any:
    return (entity or {}).get("attributes", {}).get(name)


def _month(value: str | None) -> str | None:
    """'2014-10' → '10.2014'."""
    if not value:
        return None
    year, _, month = value.partition("-")
    return f"{month}.{year}" if month else year


def _person_name(person: dict[str, Any] | None) -> str | None:
    """ФИО открывается только при оплаченном доступе; структура person живьём не проверена."""
    attrs = (person or {}).get("attributes", {})
    parts = [attrs.get(k) for k in ("lastName", "firstName", "middleName")]
    return " ".join(p for p in parts if p) or attrs.get("fullName") or attrs.get("name") or None


def _rel_id(entity: dict[str, Any], name: str) -> str | None:
    data = (entity.get("relationships", {}).get(name) or {}).get("data")
    return str(data["id"]) if isinstance(data, dict) and data.get("id") else None


def _birth_date(birth: dict[str, Any] | None) -> date | None:
    if _attr(birth, "hideBirthday") or not (value := _attr(birth, "birthDate")):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _skills(value: str | None) -> list[str]:
    return [s.strip() for s in re.split(r"[,;\n]", value or "") if s.strip()]


def _date(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _photo(photo: dict[str, Any] | None) -> str | None:
    url = _attr(photo, "medium") or _attr(photo, "large")
    return f"https:{url}" if url and url.startswith("//") else url


def map_web_resume(entities: Entities, resume_id: str, url: str | None = None) -> ParsedResume:
    resume = entities["resume"][resume_id]
    attrs = resume.get("attributes", {})

    experience = []
    for exp in _rel(entities, resume, "experience") or []:
        company = _rel(entities, exp, "resumeCompany")
        start, end = _month(_attr(exp, "dateStart")), _month(_attr(exp, "dateEnd"))
        description = "\n\n".join(t for t in (_attr(exp, "responsibility"), _attr(exp, "achievements")) if t)
        experience.append(
            WorkItem(
                company=_attr(company, "title"),
                position=_attr(exp, "position"),
                period=f"{start} — {'н.в.' if _attr(exp, 'stillWorking') or not end else end}" if start else None,
                description=description or None,
            )
        )

    salary = _attr(_rel(entities, resume, "salary"), "value") or None
    birth = _rel(entities, resume, "resumeBirthDate")
    return ParsedResume(
        source=Source.SUPERJOB,
        external_id=str(resume_id),
        url=url or f"{SITE_URL}/resume/{resume_id}.html",
        owner_id=_rel_id(resume, "ownerActivity"),
        published_at=_date(attrs.get("datePublish") or attrs.get("dateUpdate")),
        data=ResumeData(
            full_name=_person_name(_rel(entities, resume, "person")),
            title=attrs.get("position"),
            city=_attr(_rel(entities, resume, "town"), "name"),
            age=_attr(birth, "age") or None,
            birth_date=_birth_date(birth),
            salary=salary,
            currency="rub" if salary else None,
            photo_url=_photo(_rel(entities, resume, "photo")),
            about=attrs.get("additionalInformation") or None,
            experience=experience,
            skills=_skills(attrs.get("skills")),
        ),
        raw={"resume": resume, "via": "web"},
    )
