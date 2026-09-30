"""Ручной импорт резюме hh по ссылке (ТЗ: резервный вариант, если аккаунт работодателя заблокируют)."""

import pytest
from httpx_ws import aconnect_ws
from sqlalchemy import select

from app.models import Candidate, CandidateSource, Source
from app.parsers.base import PageGoneError, SourceBlockedError
from app.parsers.hh.mapper import parse_resume_link
from app.tasks import collect
from tests.conftest import ws_client
from tests.factories import make_candidate, make_resume
from tests.test_realtime import listener, next_event  # noqa: F401

HASH = "0a1b2c3d4e5f60718293a4b5c6d7e8f9abcdef"
LINK = f"https://hh.ru/resume/{HASH}?query=python&hhtmFrom=resume_search_result"


class FakeImportParser:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.fetched: list[tuple] = []
        self.closed = False

    async def fetch_resume(self, resume_hash, updated):
        self.fetched.append((resume_hash, updated))
        if self.error:
            raise self.error
        return self.result

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def hh(monkeypatch):
    """Подменяет анонимный браузер hh. Возвращает функцию-настройщик."""
    holder: dict[str, FakeImportParser] = {}

    def install(**kwargs) -> FakeImportParser:
        holder["parser"] = FakeImportParser(**kwargs)
        return holder["parser"]

    monkeypatch.setattr(collect, "create_import_parser", lambda: holder["parser"])
    return install


def anonymous_resume(resume_hash: str = HASH, **data):
    data.setdefault("full_name", None)  # без входа hh не показывает ФИО
    data.setdefault("title", "Python-разработчик")
    data.setdefault("city", "Москва")
    return make_resume(resume_hash, source=Source.HH, **data)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (LINK, HASH),
        (f"hh.ru/resume/{HASH}", HASH),
        (f"https://spb.hh.ru/resume/{HASH}/", HASH),
        (f"  https://HH.ru/resume/{HASH.upper()}#contacts ", HASH),
        ("https://hh.ru/vacancy/123", None),
        (f"https://hh.ru.evil.com/resume/{HASH}", None),
        ("https://superjob.ru/resume/python-123.html", None),
    ],
)
def test_parse_resume_link(url, expected):
    assert parse_resume_link(url) == expected


async def test_import_creates_card_and_reports_back(auth_client, session, hh, listener):  # noqa: F811
    parser = hh(result=anonymous_resume())

    async with ws_client(auth_client.cookies) as wc, aconnect_ws("/api/ws", wc) as ws:
        resp = await auth_client.post("/api/candidates/import", json={"url": LINK})
        done = await next_event(ws, "import.finished")

    assert resp.status_code == 202
    assert resp.json()["candidate_id"] is None  # ещё не было — ждём событие
    assert done["request_id"] == resp.json()["request_id"]
    assert done["error"] is None
    assert parser.fetched == [(HASH, None)]  # без кеша: человек хочет свежую версию
    assert parser.closed
    candidate = await session.get(Candidate, done["candidate_id"])
    assert candidate.title == "Python-разработчик"
    card = (await auth_client.get(f"/api/candidates/{candidate.id}")).json()
    assert card["sources"][0]["imported_by"]["name"] == "Анна HR"
    assert card["stale_since"] is None
    assert (await auth_client.get("/api/candidates")).json()["total"] == 1  # сразу в общей ленте


async def test_already_known_resume_returns_card_without_browser(auth_client, session, profile, hh):
    existing = await make_candidate(session, profile.id, HASH, source=Source.HH)
    parser = hh(result=anonymous_resume())

    resp = await auth_client.post("/api/candidates/import", json={"url": LINK})

    assert resp.json()["candidate_id"] == existing.id
    assert parser.fetched == []


async def test_import_does_not_spoil_card_collected_meanwhile(auth_client, session, profile, hh):
    """Пока задача ждала очереди, резюме пришло из поиска с ФИО — анонимная копия его не затирает."""
    hh(result=anonymous_resume())
    existing = await make_candidate(session, profile.id, HASH, source=Source.HH, full_name="Иван Петров")

    result = await collect.import_resume("req", HASH, LINK, 1)

    assert result.candidate_id == existing.id
    assert (await session.get(Candidate, existing.id, populate_existing=True)).full_name == "Иван Петров"


async def test_import_merges_with_same_person_from_other_source(auth_client, session, profile, hh):
    sj = await make_candidate(session, profile.id, "sj-1", full_name="Иван Петров", birth_date="1990-01-01")
    hh(result=anonymous_resume(full_name="Иван Петров", birth_date="1990-01-01"))

    result = await collect.import_resume("req", HASH, LINK, 1)

    assert result.candidate_id == sj.id
    sources = await session.scalars(select(CandidateSource.source).where(CandidateSource.candidate_id == sj.id))
    assert set(sources) == {Source.SUPERJOB, Source.HH}


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"error": PageGoneError(LINK)}, "резюме удалено или скрыто"),
        ({"error": SourceBlockedError("hh: капча")}, "hh не отдал резюме: hh: капча"),
        ({"error": RuntimeError("boom")}, "не удалось открыть резюме"),
        ({"result": None}, "дневной лимит"),
    ],
)
async def test_import_failures_are_reported(auth_client, session, hh, kwargs, error):
    parser = hh(**kwargs)

    result = await collect.import_resume("req", HASH, LINK, 1)

    assert error in result.error
    assert result.candidate_id is None
    assert parser.closed
    assert (await auth_client.get("/api/candidates", params={"freshness": "all"})).json()["total"] == 0


async def test_import_rejects_non_hh_links(auth_client, hh):
    parser = hh(result=anonymous_resume())

    resp = await auth_client.post("/api/candidates/import", json={"url": "https://superjob.ru/resume/1.html"})

    assert resp.status_code == 422
    assert "hh.ru" in resp.json()["detail"]
    assert parser.fetched == []


async def test_import_requires_login(client):
    assert (await client.post("/api/candidates/import", json={"url": LINK})).status_code == 401
