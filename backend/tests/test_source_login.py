"""API входа в площадку из интерфейса. Сам вход в браузере — tests/test_hh.py::TestUILogin."""

import json

import pytest

from app.api import sources as sources_api
from app.core.redis import redis
from app.models import Source
from app.parsers.browser.login import LoginChannel, LoginStatus, LoginStep

HH = LoginChannel(Source.HH)


@pytest.fixture
def queued(monkeypatch) -> list[Source]:
    calls = []

    async def fake_kiq(source):
        calls.append(source)

    # настоящая задача откроет браузер — здесь проверяем только API
    monkeypatch.setattr(sources_api.login_browser, "kiq", fake_kiq)
    return calls


async def pending_answers() -> list[dict]:
    return [json.loads(v) for v in await redis.lrange(HH.input_key, 0, -1)]


async def test_sources_tell_where_ui_login_is_available(auth_client):
    sources = {s["source"]: s for s in (await auth_client.get("/api/sources")).json()}
    assert sources["hh"]["ui_login"] is True
    assert sources["superjob"]["ui_login"] is False


async def test_start_login_queues_browser_task(auth_client, queued):
    assert (await auth_client.get("/api/sources/hh/login")).json() is None

    resp = await auth_client.post("/api/sources/hh/login")

    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    assert resp.json()["started_by"] == "Анна HR"
    assert queued == [Source.HH]
    assert (await auth_client.get("/api/sources/hh/login")).json()["status"] == "queued"


async def test_second_start_joins_running_login(auth_client, queued):
    await auth_client.post("/api/sources/hh/login")
    await HH.update(LoginStatus.NEED_INPUT, step=LoginStep.CODE, prompt="Код")

    resp = await auth_client.post("/api/sources/hh/login")

    assert resp.json()["status"] == "need_input"
    assert queued == [Source.HH]


async def test_restart_after_failure(auth_client, queued):
    await HH.update(LoginStatus.FAILED, error="не дождались ответа")
    assert (await auth_client.post("/api/sources/hh/login")).json()["status"] == "queued"
    assert queued == [Source.HH]


async def test_login_not_supported_for_superjob(auth_client, queued):
    assert (await auth_client.post("/api/sources/superjob/login")).status_code == 400
    assert queued == []


async def test_input_is_passed_to_worker(auth_client):
    await HH.update(LoginStatus.NEED_INPUT, step=LoginStep.LOGIN, prompt="Почта")

    resp = await auth_client.post("/api/sources/hh/login/input", json={"login": "hr@example.com", "password": "p"})

    assert resp.status_code == 200
    assert await pending_answers() == [{"login": "hr@example.com", "password": "p"}]
    assert await redis.ttl(HH.input_key) > 0  # ответ с паролем не залёживается в Redis


@pytest.mark.parametrize(
    ("step", "body"),
    [(LoginStep.LOGIN, {"login": "  "}), (LoginStep.CODE, {}), (LoginStep.CAPTCHA, {"value": ""})],
)
async def test_empty_input_is_rejected(auth_client, step, body):
    await HH.update(LoginStatus.NEED_INPUT, step=step)
    assert (await auth_client.post("/api/sources/hh/login/input", json=body)).status_code == 422
    assert await pending_answers() == []


async def test_input_when_not_asked_is_conflict(auth_client):
    assert (await auth_client.post("/api/sources/hh/login/input", json={"value": "1"})).status_code == 409
    await HH.update(LoginStatus.RUNNING)
    assert (await auth_client.post("/api/sources/hh/login/input", json={"value": "1"})).status_code == 409


async def test_cancel_queued_login_right_away(auth_client, queued):
    await auth_client.post("/api/sources/hh/login")

    resp = await auth_client.post("/api/sources/hh/login/cancel")

    assert resp.json()["status"] == "cancelled"


async def test_cancel_running_login_goes_through_worker(auth_client):
    await HH.update(LoginStatus.NEED_INPUT, step=LoginStep.CODE)

    await auth_client.post("/api/sources/hh/login/cancel")

    assert await pending_answers() == [{"cancel": "1"}]


async def test_login_requires_auth(client):
    assert (await client.post("/api/sources/hh/login")).status_code == 401
