from datetime import UTC, date, datetime
from typing import Any

from app.models.enums import Source
from app.parsers.base import ParsedResume, ResumeData, WorkItem


def _period(item: dict[str, Any]) -> str | None:
    beg = f"{item.get('monthbeg') or ''}.{item['yearbeg']}".lstrip(".") if item.get("yearbeg") else None
    end = f"{item.get('monthend') or ''}.{item['yearend']}".lstrip(".") if item.get("yearend") else "н.в."
    return f"{beg} — {end}" if beg else None


def _title(value: Any) -> str | None:
    return value.get("title") if isinstance(value, dict) else value


def _birth_date(obj: dict[str, Any]) -> date | None:
    """birthyear/birthmonth/birthday из API; неполная дата для склейки дублей бесполезна."""
    try:
        return date(obj["birthyear"], obj["birthmonth"], obj["birthday"])
    except (KeyError, TypeError, ValueError):
        return None


def map_resume(obj: dict[str, Any]) -> ParsedResume:
    name = " ".join(p for p in (obj.get("lastname"), obj.get("firstname"), obj.get("middlename")) if p)
    published = obj.get("date_published") or obj.get("date_last_modified")
    photo = obj.get("photo")
    return ParsedResume(
        source=Source.SUPERJOB,
        external_id=str(obj["id"]),
        url=obj.get("link"),
        published_at=datetime.fromtimestamp(published, UTC) if published else None,
        data=ResumeData(
            full_name=name or None,
            title=obj.get("profession"),
            city=_title(obj.get("town")),
            age=obj.get("age") or None,
            birth_date=_birth_date(obj),
            salary=obj.get("payment") or None,
            currency=obj.get("currency"),
            photo_url=photo if isinstance(photo, str) else None,
            about=obj.get("achievements") or obj.get("additional_info"),
            experience=[
                WorkItem(
                    company=w.get("name"),
                    position=w.get("profession"),
                    period=_period(w),
                    description=w.get("work"),
                )
                for w in obj.get("work_history") or []
            ],
            education=[
                ", ".join(
                    p for p in (_title(e.get("institute")), e.get("speciality"), str(e.get("yearend") or "")) if p
                )
                for e in obj.get("base_education_history") or []
            ],
            skills=[c["title"] for c in obj.get("catalogues") or [] if c.get("title")],
        ),
        raw=obj,
    )
