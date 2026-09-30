import pytest

from app.models import CandidateStatus, Source
from tests.conftest import login
from tests.factories import make_candidate, make_resume


async def test_feed_is_empty(auth_client):
    assert (await auth_client.get("/api/candidates")).json() == {"items": [], "total": 0}


async def test_feed_newest_first_with_pagination(auth_client, session, profile):
    for i in range(5):
        await make_candidate(session, profile.id, external_id=str(i))

    page = (await auth_client.get("/api/candidates", params={"limit": 2, "offset": 1})).json()

    assert page["total"] == 5
    assert [c["full_name"] for c in page["items"]] == ["Кандидат 3", "Кандидат 2"]


async def test_feed_filters(auth_client, session, profile):
    from app.models import SearchProfile

    other = SearchProfile(title="Дизайнер", keywords="figma", sources=["superjob"])
    session.add(other)
    await session.commit()
    await make_candidate(session, profile.id, "1", full_name="Иван Петров", title="Backend")
    await make_candidate(session, profile.id, "2", full_name="Ольга Смирнова", status=CandidateStatus.INTERESTING)
    await make_candidate(session, other.id, "3", full_name="Павел Дизайнов", title="UI дизайнер")

    async def names(**params):
        items = (await auth_client.get("/api/candidates", params=params)).json()["items"]
        return sorted(c["full_name"] for c in items)

    assert await names(status="interesting") == ["Ольга Смирнова"]
    assert await names(profile_id=other.id) == ["Павел Дизайнов"]
    assert await names(q="петров") == ["Иван Петров"]  # регистр не важен
    assert await names(q="дизайнер") == ["Павел Дизайнов"]  # ищет и по должности
    assert await names(source="hh") == []
    assert len(await names(source="superjob")) == 3


async def test_feed_rejects_unknown_status(auth_client):
    assert (await auth_client.get("/api/candidates", params={"status": "hired"})).status_code == 422


async def test_candidate_detail(auth_client, session, profile):
    c = await make_candidate(
        session, profile.id, "77", full_name="Мария Иванова", city="Казань", salary=250000, skills=["Python"]
    )

    data = (await auth_client.get(f"/api/candidates/{c.id}")).json()

    assert data["full_name"] == "Мария Иванова"
    assert data["city"] == "Казань"
    assert data["status"] == "new"
    assert data["resume"]["skills"] == ["Python"]
    assert data["sources"] == [
        {
            "source": "superjob",
            "external_id": "77",
            "url": "https://example.com/resume/77",
            "published_at": None,
            "fetched_at": data["sources"][0]["fetched_at"],
            "last_seen_at": data["sources"][0]["last_seen_at"],
            "gone_at": None,
            "imported_by": None,
        }
    ]
    assert data["stale_since"] is None


async def test_candidate_not_found(auth_client):
    assert (await auth_client.get("/api/candidates/999")).status_code == 404
    assert (await auth_client.patch("/api/candidates/999/status", json={"status": "rejected"})).status_code == 404
    assert (await auth_client.post("/api/candidates/999/comments", json={"text": "?"})).status_code == 404


async def test_set_status_records_who_and_when(auth_client, session, profile):
    c = await make_candidate(session, profile.id)

    resp = await auth_client.patch(f"/api/candidates/{c.id}/status", json={"status": "contacted"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "contacted"
    assert data["status_changed_by"]["name"] == "Анна HR"
    assert data["status_changed_at"] is not None
    # статус общий: другой HR видит то же самое
    detail = (await auth_client.get(f"/api/candidates/{c.id}")).json()
    assert detail["status"] == "contacted"


@pytest.mark.parametrize("status", [s.value for s in CandidateStatus])
async def test_all_statuses_accepted(auth_client, session, profile, status):
    c = await make_candidate(session, profile.id)
    resp = await auth_client.patch(f"/api/candidates/{c.id}/status", json={"status": status})
    assert resp.json()["status"] == status


async def test_status_conflict_when_colleague_changed_it_first(client, make_user, session, profile):
    """Двое видят «новая» и одновременно жмут: второй получает 409, а не перезаписывает первого."""
    c = await make_candidate(session, profile.id)
    await make_user(login="anna", name="Анна")
    await make_user(login="oleg", name="Олег")

    await login(client, "anna")
    first = await client.patch(f"/api/candidates/{c.id}/status", json={"status": "contacted", "expected": "new"})
    await login(client, "oleg")
    second = await client.patch(f"/api/candidates/{c.id}/status", json={"status": "in_progress", "expected": "new"})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "Статус уже сменили (Анна): «на связи». Проверьте и выберите заново"
    data = (await client.get(f"/api/candidates/{c.id}")).json()
    assert (data["status"], data["status_changed_by"]["name"]) == ("contacted", "Анна")

    # увидел свежий статус — теперь может сменить осознанно
    third = await client.patch(f"/api/candidates/{c.id}/status", json={"status": "new", "expected": "contacted"})
    assert third.json()["status"] == "new"


async def test_status_without_expected_always_wins(auth_client, session, profile):
    c = await make_candidate(session, profile.id, status=CandidateStatus.REJECTED)
    resp = await auth_client.patch(f"/api/candidates/{c.id}/status", json={"status": "interesting"})
    assert resp.json()["status"] == "interesting"


async def test_set_status_rejects_unknown_value(auth_client, session, profile):
    c = await make_candidate(session, profile.id)
    resp = await auth_client.patch(f"/api/candidates/{c.id}/status", json={"status": "hired"})
    assert resp.status_code == 422


async def test_comments_thread(client, make_user, session, profile):
    c = await make_candidate(session, profile.id)
    await make_user(login="anna", name="Анна")
    await make_user(login="oleg", name="Олег")

    await login(client, "anna")
    first = await client.post(f"/api/candidates/{c.id}/comments", json={"text": "  Пишу ему в тг  "})
    await login(client, "oleg")
    await client.post(f"/api/candidates/{c.id}/comments", json={"text": "Ок, я не трогаю"})

    assert first.status_code == 201
    assert first.json()["text"] == "Пишу ему в тг"
    thread = (await client.get(f"/api/candidates/{c.id}/comments")).json()
    assert [(m["author"]["name"], m["text"]) for m in thread] == [
        ("Анна", "Пишу ему в тг"),
        ("Олег", "Ок, я не трогаю"),
    ]
    assert (await client.get(f"/api/candidates/{c.id}")).json()["comments_count"] == 2
    assert (await client.get("/api/candidates")).json()["items"][0]["comments_count"] == 2


@pytest.mark.parametrize("text", ["", "x" * 5001])
async def test_comment_validation(auth_client, session, profile, text):
    c = await make_candidate(session, profile.id)
    resp = await auth_client.post(f"/api/candidates/{c.id}/comments", json={"text": text})
    assert resp.status_code == 422


async def test_candidate_with_several_sources(auth_client, session, profile):
    """Задел под этапы 1–2: у одной карточки может быть несколько площадок."""
    from app.models import CandidateSource

    c = await make_candidate(session, profile.id, "sj-1")
    hh = make_resume("hh-1", source=Source.HH)
    session.add(CandidateSource(candidate_id=c.id, source=hh.source, external_id=hh.external_id, url=hh.url))
    await session.commit()

    data = (await auth_client.get("/api/candidates", params={"source": "hh"})).json()

    assert data["total"] == 1
    assert {s["source"] for s in data["items"][0]["sources"]} == {"superjob", "hh"}


async def test_author_edits_and_deletes_own_comment(auth_client, session, profile):
    c = await make_candidate(session, profile.id)
    comment = (await auth_client.post(f"/api/candidates/{c.id}/comments", json={"text": "Звоню завтра"})).json()
    assert comment["edited_at"] is None

    resp = await auth_client.patch(f"/api/candidates/{c.id}/comments/{comment['id']}", json={"text": " Звоню в пн "})

    assert resp.status_code == 200
    assert resp.json()["text"] == "Звоню в пн"
    assert resp.json()["edited_at"] is not None
    thread = (await auth_client.get(f"/api/candidates/{c.id}/comments")).json()
    assert [m["text"] for m in thread] == ["Звоню в пн"]

    assert (await auth_client.delete(f"/api/candidates/{c.id}/comments/{comment['id']}")).status_code == 204
    assert (await auth_client.get(f"/api/candidates/{c.id}/comments")).json() == []
    assert (await auth_client.get(f"/api/candidates/{c.id}")).json()["comments_count"] == 0


async def test_cannot_touch_colleagues_comment(client, make_user, session, profile):
    c = await make_candidate(session, profile.id)
    await make_user(login="anna", name="Анна")
    await make_user(login="oleg", name="Олег")
    await login(client, "anna")
    comment = (await client.post(f"/api/candidates/{c.id}/comments", json={"text": "Моё"})).json()

    await login(client, "oleg")
    url = f"/api/candidates/{c.id}/comments/{comment['id']}"
    assert (await client.patch(url, json={"text": "Чужое"})).status_code == 403
    assert (await client.delete(url)).status_code == 403
    assert (await client.get(f"/api/candidates/{c.id}/comments")).json()[0]["text"] == "Моё"


async def test_comment_edit_not_found_and_validation(auth_client, session, profile):
    c = await make_candidate(session, profile.id)
    other = await make_candidate(session, profile.id, "2")
    comment = (await auth_client.post(f"/api/candidates/{c.id}/comments", json={"text": "x"})).json()

    assert (await auth_client.patch(f"/api/candidates/{c.id}/comments/999", json={"text": "y"})).status_code == 404
    # комментарий другой анкеты по чужому адресу не найти
    assert (await auth_client.delete(f"/api/candidates/{other.id}/comments/{comment['id']}")).status_code == 404
    resp = await auth_client.patch(f"/api/candidates/{c.id}/comments/{comment['id']}", json={"text": ""})
    assert resp.status_code == 422
