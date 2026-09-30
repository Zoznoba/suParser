import pytest

from app.core.config import settings
from tests.conftest import PASSWORD, login


async def test_health(client):
    assert (await client.get("/api/health")).json() == {"status": "ok"}


async def test_login_sets_httponly_session_cookie(client, make_user):
    await make_user(login="anna", name="Анна")

    resp = await client.post("/api/auth/login", json={"login": "anna", "password": PASSWORD})

    assert resp.status_code == 200
    assert resp.json()["name"] == "Анна"
    cookie = resp.headers["set-cookie"]
    assert cookie.startswith(f"{settings.session_cookie_name}=")
    assert "HttpOnly" in cookie
    assert (await client.get("/api/auth/me")).json()["login"] == "anna"


@pytest.mark.parametrize(
    ("login_", "password"),
    [("hr", "wrong-password"), ("nobody", PASSWORD)],
    ids=["wrong-password", "unknown-login"],
)
async def test_login_rejects_bad_credentials(client, make_user, login_, password):
    await make_user()
    resp = await client.post("/api/auth/login", json={"login": login_, "password": password})
    assert resp.status_code == 401


async def test_inactive_user_cannot_login(client, make_user):
    await make_user(is_active=False)
    resp = await client.post("/api/auth/login", json={"login": "hr", "password": PASSWORD})
    assert resp.status_code == 401


async def test_deactivated_user_loses_existing_session(auth_client, session):
    from app.models import User

    user = await session.get(User, 1)
    user.is_active = False
    await session.commit()

    assert (await auth_client.get("/api/auth/me")).status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/auth/me"),
        ("GET", "/api/candidates"),
        ("GET", "/api/candidates/1"),
        ("PATCH", "/api/candidates/1/status"),
        ("POST", "/api/candidates/1/comments"),
        ("GET", "/api/profiles"),
        ("POST", "/api/profiles"),
        ("POST", "/api/profiles/1/run"),
        ("GET", "/api/sources"),
    ],
)
async def test_endpoints_require_auth(client, method, path):
    resp = await client.request(method, path, json={})
    assert resp.status_code == 401


async def test_forged_cookie_is_rejected(client):
    client.cookies.set(settings.session_cookie_name, "forged-token")
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_logout_invalidates_session_server_side(client, make_user):
    await make_user()
    await login(client)
    token = client.cookies[settings.session_cookie_name]

    assert (await client.post("/api/auth/logout")).status_code == 204

    # даже если кто-то сохранил cookie, сессия на сервере уже удалена
    client.cookies.set(settings.session_cookie_name, token)
    assert (await client.get("/api/auth/me")).status_code == 401
