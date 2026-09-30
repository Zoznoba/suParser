"""Ручной импорт и 404 на настоящем Chromium против фейкового hh.ru."""

import json

import pytest

from app.parsers.base import PageGoneError
from tests.test_hh import QUERY, FakeSiteParser, chromium_available, collect, site  # noqa: F401

pytestmark = pytest.mark.usefixtures("chromium_available")


async def test_search_skips_deleted_resume_and_reports_it(site):  # noqa: F811
    site.gone = {"h1001"}
    parser = FakeSiteParser(site)

    resumes = await collect(parser, QUERY)

    assert "h1001" not in [r.external_id for r in resumes]
    assert len(resumes) == 6  # остальные собраны, источник не встал на паузу
    assert parser.gone == ("h1001",)
    assert parser.complete


async def test_anonymous_parser_ignores_saved_account_session(site):  # noqa: F811
    parser = FakeSiteParser(site)
    parser.state_path.parent.mkdir(parents=True, exist_ok=True)
    cookie = {
        "name": "hh_auth",
        "value": "1",
        "domain": "hh.ru",
        "path": "/",
        "expires": -1,
        "httpOnly": False,
        "secure": False,
        "sameSite": "Lax",
    }
    parser.state_path.write_text(json.dumps({"cookies": [cookie], "origins": []}))
    saved = parser.state_path.read_text()

    anonymous = FakeSiteParser(site)
    anonymous.anonymous = True
    try:
        resume = await anonymous.fetch_resume("h1000", None)
    finally:
        await anonymous.close()

    assert resume.external_id == "h1000"
    assert resume.data.full_name is None  # резюме открыто без входа работодателя
    assert parser.state_path.read_text() == saved  # и сессию аккаунта анонимный браузер не перезаписал


async def test_fetch_of_deleted_resume_raises_gone(site):  # noqa: F811
    site.gone = {"h1000"}
    parser = FakeSiteParser(site)
    parser.anonymous = True
    try:
        with pytest.raises(PageGoneError):
            await parser.fetch_resume("h1000", None)
    finally:
        await parser.close()
