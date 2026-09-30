"""Поиск одного и того же человека среди резюме с разных площадок (и разных резюме на одной).

Ключи, от надёжного к слабому:
- id аккаунта соискателя на площадке (ParsedResume.owner_id) — все его резюме там; склеиваем без вопросов;
- ФИО + дата рождения / ФИО + общее место работы / дата рождения + город + место работы — склеиваем сами;
- совпало только ФИО или только дата рождения — «возможный дубль», решает человек в карточке.

Любое явное противоречие (разные ФИО, даты рождения, возраст больше чем на год) — точно разные люди.
Лучше пропустить дубль, чем слить двух людей: у карточки статус и комментарии HR.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from itertools import combinations
from typing import Any

from sqlalchemy import Select, and_, func, or_, select

from app.models import Candidate
from app.parsers.base import ResumeData

# организационно-правовые формы и мусор вокруг названия компании
COMPANY_NOISE = re.compile(r"\b(ооо|оао|зао|пао|ао|ип|нко|фгуп|гуп|муп|llc|ltd|inc|gmbh|группа компаний|гк)\b")


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").lower().replace("ё", "е")).strip()


def _name_tokens(full_name: str | None) -> frozenset[str]:
    tokens = frozenset(re.findall(r"[\w-]+", _norm(full_name)))
    return tokens if len(tokens) >= 2 else frozenset()  # одно слово — не ФИО, а «Иван» или «Кандидат»


def _company(name: str | None) -> str:
    return " ".join(re.sub(r"[^\w ]+", " ", COMPANY_NOISE.sub(" ", _norm(name))).split())


@dataclass(frozen=True)
class Person:
    name: frozenset[str] = frozenset()
    birth_date: date | None = None
    age: int | None = None
    city: str = ""
    companies: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def build(cls, full_name: str | None, birth_date: date | None, age: int | None, city: str | None, experience: Any):
        companies = {_company(w.get("company")) for w in experience or [] if isinstance(w, dict)}
        return cls(_name_tokens(full_name), birth_date, age, _norm(city), frozenset(c for c in companies if c))

    @classmethod
    def of_resume(cls, data: ResumeData) -> "Person":
        return cls.build(
            data.full_name, data.birth_date, data.age, data.city, [w.model_dump() for w in data.experience]
        )

    @classmethod
    def of_candidate(cls, c: Candidate) -> "Person":
        return cls.build(c.full_name, c.birth_date, c.age, c.city, (c.resume or {}).get("experience"))


@dataclass(frozen=True)
class Match:
    sure: bool = False  # можно склеивать автоматически
    reasons: tuple[str, ...] = ()  # что совпало; пусто — не похожи


def compare(a: Person, b: Person) -> Match:
    if a.name and b.name and not (a.name <= b.name or b.name <= a.name):  # «Иванов Иван» ⊂ «Иванов Иван Иванович»
        return Match()
    if a.birth_date and b.birth_date and a.birth_date != b.birth_date:
        return Match()
    if a.age and b.age and abs(a.age - b.age) > 1:  # резюме могли скачать в разные дни рождения
        return Match()

    name = bool(a.name and b.name)
    birth = bool(a.birth_date and b.birth_date)
    city = bool(a.city and a.city == b.city)
    company = bool(a.companies & b.companies)
    if not (name or birth):
        return Match()

    city_conflict = bool(a.city and b.city and not city)
    sure = (name and birth) or (name and company and not city_conflict) or (birth and city and company)
    reasons = [
        label
        for label, ok in (
            ("ФИО", name),
            ("дата рождения", birth),
            ("возраст", not birth and bool(a.age and b.age)),
            ("город", city),
            ("место работы", company),
        )
        if ok
    ]
    return Match(sure, tuple(reasons))


def similar_stmt(person: Person) -> Select[tuple[Candidate]] | None:
    """Кандидаты, у которых совпадает ФИО или дата рождения, — дальше их проверяет compare()."""
    conditions = []
    if person.birth_date:
        conditions.append(Candidate.birth_date == person.birth_date)
    if person.name:
        full_name = func.replace(func.lower(Candidate.full_name), "ё", "е")
        # любые два слова из ФИО: у одной площадки может не быть отчества
        pairs = combinations(sorted(person.name), 2)
        conditions += [and_(*(full_name.contains(t, autoescape=True) for t in pair)) for pair in pairs]
    if not conditions:
        return None
    return select(Candidate).where(or_(*conditions)).order_by(Candidate.id).limit(50)
