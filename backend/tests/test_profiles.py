import pytest
from sqlalchemy import func, select

from app.models import Candidate, candidate_profiles

PROFILE = {"title": "Go-разработчик", "keywords": "golang, grpc", "interval_minutes": 30}


async def test_profile_crud(auth_client):
    created = (await auth_client.post("/api/profiles", json=PROFILE)).json()
    assert created["sources"] == ["superjob"]  # по умолчанию
    assert created["is_active"] is True
    assert created["last_run_at"] is None

    updated = await auth_client.put(f"/api/profiles/{created['id']}", json={**PROFILE, "is_active": False})
    assert updated.json()["is_active"] is False

    assert [p["title"] for p in (await auth_client.get("/api/profiles")).json()] == ["Go-разработчик"]

    assert (await auth_client.delete(f"/api/profiles/{created['id']}")).status_code == 204
    assert (await auth_client.get("/api/profiles")).json() == []


@pytest.mark.parametrize(
    "patch",
    [{"title": ""}, {"interval_minutes": 5}, {"sources": ["avito"]}],
    ids=["empty-title", "too-frequent", "unknown-source"],
)
async def test_profile_validation(auth_client, patch):
    assert (await auth_client.post("/api/profiles", json={**PROFILE, **patch})).status_code == 422


async def test_profile_not_found(auth_client):
    assert (await auth_client.put("/api/profiles/999", json=PROFILE)).status_code == 404
    assert (await auth_client.delete("/api/profiles/999")).status_code == 404
    assert (await auth_client.post("/api/profiles/999/run")).status_code == 404


async def test_run_now_collects_candidates(auth_client, session):
    """Сквозной путь: API → очередь TaskIQ → парсер SuperJob (mock) → карточки в ленте."""
    profile = (await auth_client.post("/api/profiles", json=PROFILE)).json()

    resp = await auth_client.post(f"/api/profiles/{profile['id']}/run")

    assert resp.json() == {"queued": ["superjob"]}
    feed = (await auth_client.get("/api/candidates", params={"profile_id": profile["id"]})).json()
    assert feed["total"] > 0
    assert all(c["sources"][0]["source"] == "superjob" for c in feed["items"])


async def test_run_skips_sources_not_implemented_yet(auth_client):
    profile = (await auth_client.post("/api/profiles", json={**PROFILE, "sources": ["linkedin"]})).json()
    assert (await auth_client.post(f"/api/profiles/{profile['id']}/run")).json() == {"queued": []}


async def test_deleting_profile_keeps_candidates(auth_client, session):
    profile = (await auth_client.post("/api/profiles", json=PROFILE)).json()
    await auth_client.post(f"/api/profiles/{profile['id']}/run")
    before = await session.scalar(select(func.count()).select_from(Candidate))

    await auth_client.delete(f"/api/profiles/{profile['id']}")

    assert await session.scalar(select(func.count()).select_from(Candidate)) == before
    assert await session.scalar(select(func.count()).select_from(candidate_profiles)) == 0
