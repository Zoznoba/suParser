"""Фейковый superjob.ru для тестов браузерного парсера (синтетические данные, повторяют структуру APP_STATE)."""

import json
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse


def ref(type_: str, id_: str) -> dict:
    return {"data": {"id": id_, "type": type_}, "meta": {"hidden": False}}


def resume_entities(ids: list[str], logged_in: bool = False) -> dict:
    e: dict[str, dict] = {k: {} for k in ("resume", "town", "resumeSalary", "resumeBirthDate", "resumePhoto")}
    e |= {"resumeExperience": {}, "resumeExperienceCompany": {}, "person": {}}
    e["town"]["4"] = {"id": "4", "type": "town", "attributes": {"name": "Москва"}}
    for i, rid in enumerate(ids):
        exp_id = f"{rid}01"
        e["resumeExperience"][exp_id] = {
            "id": exp_id,
            "type": "resumeExperience",
            "attributes": {
                "position": "Backend-разработчик",
                "stillWorking": i % 2 == 0,
                "dateStart": "2021-03",
                "dateEnd": None if i % 2 == 0 else "2024-11",
                "responsibility": "Разработка API на FastAPI",
                "achievements": "Ускорил сервис в 3 раза" if i == 0 else "",
            },
            "relationships": {"resumeCompany": ref("resumeExperienceCompany", exp_id)},
        }
        e["resumeExperienceCompany"][exp_id] = {"id": exp_id, "attributes": {"title": f"Компания {i}"}}
        e["resumeSalary"][rid] = {"id": rid, "attributes": {"value": 200000 + i * 10000 if i % 3 else 0}}
        e["resumeBirthDate"][rid] = {
            "id": rid,
            "attributes": {"age": 25 + i, "birthDate": f"{2001 - i}-01-17", "hideBirthday": i == 1},
        }
        e["resumePhoto"][rid] = {"id": rid, "attributes": {"medium": f"//public.superjob.ru/images/r{rid}.jpg"}}
        rels = {
            "town": ref("town", "4"),
            "salary": ref("resumeSalary", rid),
            "resumeBirthDate": ref("resumeBirthDate", rid),
            "photo": ref("resumePhoto", rid),
            "experience": {"data": [{"id": exp_id, "type": "resumeExperience"}]},
            "person": {"data": None, "meta": {"hidden": True, "reasons": []}},  # так даже под работодателем
            "ownerActivity": ref("applicantLastActivity", f"9{rid}"),
        }
        if logged_in:  # ФИО — только при оплаченном доступе к базе; структура person предположительная
            e["person"][rid] = {"id": rid, "attributes": {"firstName": "Иван", "lastName": f"Тестов{i}"}}
            rels["person"] = ref("person", rid)
        e["resume"][rid] = {
            "id": rid,
            "type": "resume",
            "attributes": {
                "position": f"Python-разработчик {rid}",
                "datePublish": "2026-09-23T12:04:49+03:00",
                "additionalInformation": "Люблю асинхронщину",
                "skills": "Python, FastAPI\nPostgreSQL",
            },
            "relationships": rels,
        }
    return e


def search_state(ids: list[str], total: int, offset: int, logged_in: bool = False) -> dict:
    return {
        "ids": {"RESUME_SEARCH_RESULT": ids},
        "metas": {"RESUME_SEARCH_RESULT": {"total": total, "offset": offset, "limit": 30}},
        "entities": resume_entities(ids, logged_in),
    }


LOGIN_PAGE = """<!doctype html><html><head><title>Вход</title></head><body>
<button id="tab">Ищу сотрудников</button>
<input name="login" placeholder="Телефон или email">
<button id="next">Продолжить</button>
<div id="step2"></div>
<script>
document.getElementById('next').onclick = () => {
  if (window.CODE_MODE) { document.getElementById('step2').textContent = 'Введите код из SMS'; return; }
  const pwd = document.createElement('input'); pwd.type = 'password';
  pwd.onkeydown = (e) => { if (e.key === 'Enter') {
    fetch('/auth/do-login', {method: 'POST', body: JSON.stringify({
      login: document.querySelector('[name=login]').value, password: pwd.value, employer: window.EMPLOYER})})
      .then(r => { if (r.ok) location.href = '/resume/search_resume.html?page=1'; });
  }};
  document.getElementById('step2').appendChild(pwd);
};
document.getElementById('tab').onclick = () => { window.EMPLOYER = true; };
</script></body></html>"""


@dataclass
class FakeSuperJob:
    per_page: int = 3
    total: int = 7
    captcha_on_page: int | None = None
    no_state_on_page: int | None = None
    code_required: bool = False
    status: int = 200
    visited: list[str] = field(default_factory=list)
    logins: list[dict] = field(default_factory=list)

    def ids_for_page(self, page: int) -> list[str]:
        start = (page - 1) * self.per_page
        return [str(1000 + i) for i in range(start, min(start + self.per_page, self.total))]

    async def handle(self, route) -> None:
        request = route.request
        url = urlparse(request.url)
        self.visited.append(url.path + (f"?{url.query}" if url.query else ""))
        logged_in = "sj_auth=1" in (await request.all_headers()).get("cookie", "")

        if url.path == "/auth/do-login":
            self.logins.append(json.loads(request.post_data or "{}"))
            await route.fulfill(status=200, headers={"Set-Cookie": "sj_auth=1; Path=/"}, body="ok")
        elif url.path == "/auth/login/":
            body = LOGIN_PAGE.replace("<script>", f"<script>window.CODE_MODE = {str(self.code_required).lower()};", 1)
            await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)
        elif url.path == "/resume/search_resume.html":
            page = int(parse_qs(url.query).get("page", ["1"])[0])
            await route.fulfill(
                status=self.status, content_type="text/html; charset=utf-8", body=self.search_page(page, logged_in)
            )
        else:
            await route.fulfill(status=404, body="")

    def search_page(self, page: int, logged_in: bool) -> str:
        header = "<a href='/hr/'>Кабинет</a>" if logged_in else "<a href='/auth/login/?returnUrl=%2F'>Войти</a>"
        if page == self.captcha_on_page:
            captcha = "<iframe src='/smartcaptcha'></iframe>"
            return f"<html><head><title>Я не робот</title></head><body>{header}{captcha}</body></html>"
        if page == self.no_state_on_page:
            return f"<html><head><title>Поиск</title></head><body>{header}</body></html>"
        ids = self.ids_for_page(page)
        state = search_state(ids, self.total, (page - 1) * self.per_page, logged_in)
        links = "".join(f"<a href='/resume/python-razrabotchik-{rid}.html'>{rid}</a>" for rid in ids)
        return (
            f"<html><head><title>Поиск резюме</title></head><body>{header}"
            f"<a href='/resume/search_resume.html?page=2'>2</a>{links}"
            f"<script>window.APP_STATE = {json.dumps(state, ensure_ascii=False)};</script></body></html>"
        )
