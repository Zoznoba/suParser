from datetime import date

import pytest

from app.models import CandidateStatus, Comment, Source
from app.parsers.base import WorkItem
from app.services.candidates import upsert_resume
from app.services.matching import Person, compare
from tests.factories import make_candidate, make_resume

BIRTH = date(1990, 5, 12)


def person(name=None, birth=None, age=None, city=None, companies=()):
    return Person.build(name, birth, age, city, [{"company": c} for c in companies])


class TestCompare:
    @pytest.mark.parametrize(
        ("a", "b", "sure", "reasons"),
        [
            (
                person("Иванов Иван Иванович", BIRTH, city="Москва"),
                person("иванов иван", BIRTH, city="Москва"),
                True,
                ("ФИО", "дата рождения", "город"),
            ),
            (  # ё/е и ОПФ компании не мешают
                person("Семёнов Пётр", age=30, companies=['ООО "Ромашка"']),
                person("Семенов Петр", age=31, companies=["Ромашка"]),
                True,
                ("ФИО", "возраст", "место работы"),
            ),
            (  # SuperJob без ФИО: дата рождения + город + компания
                person(None, BIRTH, city="Казань", companies=["Яндекс"]),
                person("Иванов Иван", BIRTH, city="казань", companies=["Яндекс"]),
                True,
                ("дата рождения", "город", "место работы"),
            ),
            (  # только ФИО — однофамилец вероятен, решает человек
                person("Иванов Иван", city="Москва"),
                person("Иванов Иван", city="Москва"),
                False,
                ("ФИО", "город"),
            ),
            (  # ФИО + компания, но разные города — не уверены
                person("Иванов Иван", city="Москва", companies=["Сбер"]),
                person("Иванов Иван", city="Самара", companies=["Сбер"]),
                False,
                ("ФИО", "место работы"),
            ),
        ],
    )
    def test_similar(self, a, b, sure, reasons):
        assert compare(a, b).sure is sure
        assert compare(a, b).reasons == reasons
        assert compare(b, a).sure is sure

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            (person("Иванов Иван", BIRTH), person("Петров Иван", BIRTH)),
            (person("Иванов Иван", BIRTH), person("Иванов Иван", date(1991, 5, 12))),
            (person("Иванов Иван", age=30), person("Иванов Иван", age=35)),
            (person("Иван", city="Москва"), person("Иван", city="Москва")),  # одно слово — не ФИО
            (person(None, city="Москва", companies=["Сбер"]), person(None, city="Москва", companies=["Сбер"])),
        ],
    )
    def test_different(self, a, b):
        assert compare(a, b).reasons == ()


def exp(*companies):
    return [WorkItem(company=c, position="Разработчик") for c in companies]


async def test_same_superjob_owner_is_one_card(session, profile):
    r1 = make_resume("1", full_name=None, title="Python")
    r2 = make_resume("2", full_name=None, title="Go")
    r1.owner_id = r2.owner_id = "owner-7"
    first, _ = await upsert_resume(session, r1, profile.id)
    second, created = await upsert_resume(session, r2, profile.id)

    assert (second.id, created) == (first.id, False)
    assert {s.external_id for s in second.sources} == {"1", "2"}


async def test_cross_source_match_keeps_name_from_hh(session, profile):
    hh, _ = await upsert_resume(
        session,
        make_resume("abc", Source.HH, full_name="Иванов Иван", birth_date=BIRTH, city="Москва", experience=exp("СБЕР")),
        profile.id,
    )
    sj, created = await upsert_resume(
        session,
        make_resume(
            "5", full_name=None, birth_date=BIRTH, city="Москва", experience=exp("Сбер", "Тинькофф"), salary=300000
        ),
        profile.id,
    )

    assert (sj.id, created) == (hh.id, False)
    assert sj.full_name == "Иванов Иван"  # SuperJob без ФИО не затирает имя с hh
    assert sj.salary == 300000
    assert len(sj.resume["experience"]) == 2


async def test_namesakes_are_not_merged(session, profile):
    a, _ = await upsert_resume(
        session, make_resume("abc", Source.HH, full_name="Иванов Иван", birth_date=BIRTH), profile.id
    )
    b, created = await upsert_resume(
        session, make_resume("5", full_name="Иванов Иван", birth_date=date(1985, 1, 1)), profile.id
    )

    assert created and a.id != b.id


async def test_same_source_is_not_merged_by_heuristic(session, profile):
    a = await make_candidate(session, profile.id, "1", full_name="Иванов Иван", birth_date=BIRTH)
    b = await make_candidate(session, profile.id, "2", full_name="Иванов Иван", birth_date=BIRTH)
    assert a.id != b.id


async def test_duplicates_and_merge(auth_client, session, profile):
    a = await make_candidate(session, profile.id, "1", full_name="Иванов Иван", city="Москва")
    b = await make_candidate(
        session, profile.id, "2", status=CandidateStatus.INTERESTING, full_name="Иванов Иван Иванович", age=30
    )
    await make_candidate(session, profile.id, "3", full_name="Петров Пётр")
    session.add(Comment(candidate_id=b.id, text="Звонил"))
    await session.commit()

    [dup] = (await auth_client.get(f"/api/candidates/{a.id}/duplicates")).json()
    assert (dup["candidate"]["id"], dup["reasons"], dup["sure"]) == (b.id, ["ФИО"], False)

    resp = await auth_client.post(f"/api/candidates/{a.id}/merge", json={"other_id": b.id})

    assert resp.status_code == 200
    merged = resp.json()
    assert {s["external_id"] for s in merged["sources"]} == {"1", "2"}
    assert (merged["full_name"], merged["city"], merged["age"]) == ("Иванов Иван", "Москва", 30)
    assert merged["status"] == "interesting"  # у «новой» карточки статус берётся из вливаемой
    assert merged["comments_count"] == 1
    assert (await auth_client.get(f"/api/candidates/{b.id}")).status_code == 404
    assert (await auth_client.get(f"/api/candidates/{a.id}/duplicates")).json() == []
    feed = (await auth_client.get("/api/candidates", params={"profile_id": profile.id})).json()
    assert feed["total"] == 2


async def test_merge_validation(auth_client, session, profile):
    a = await make_candidate(session, profile.id, "1")
    assert (await auth_client.post(f"/api/candidates/{a.id}/merge", json={"other_id": a.id})).status_code == 400
    assert (await auth_client.post(f"/api/candidates/{a.id}/merge", json={"other_id": 999})).status_code == 404
