"""Фейковый hh.ru для тестов браузерного парсера (синтетические данные, повторяют структуру HH-Lux-InitialState)."""

import html
import json
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

UPDATED_MS = 1790765160000  # 2026-09-30T10:46:00Z


def field_(value) -> dict:
    return {"value": value, "type": "field", "block": None, "_attributes": None}


def search_item(resume_hash: str, i: int = 0, updated: int = UPDATED_MS) -> dict:
    return {
        "forbidden": None,
        "_attributes": {"hash": resume_hash, "id": str(i), "updated": updated, "permission": "view_without_contacts"},
        "title": [{"string": f"Python-разработчик {resume_hash}"}],
        "age": [{"string": 25 + i}],
        "salary": [{"amount": 200000, "currency": "RUR"}] if i % 2 == 0 else [],
        "keySkills": [{"string": "Python"}, {"string": "FastAPI"}],
        "totalExperience": [{"string": 48}],
        "negotiationLinks": {"invite": {"defaultLink": "/employer/negotiations/change_topic"}},
    }


def resume_state(resume_hash: str, logged_in: bool = False, i: int = 0) -> dict:
    hidden = {"lastName": None, "firstName": None, "middleName": None, "experience": [], "primaryEducation": None}
    visible = {
        "lastName": f"Тестов{i}",
        "firstName": "Иван",
        "middleName": None,
        "experience": [
            {
                "companyName": f"Компания {i}",
                "position": "Backend-разработчик",
                "startDate": "2021-03-01",
                "endDate": None,
                "description": "Разработка API на FastAPI",
            },
            {"companyName": "Стартап", "position": "Стажёр", "startDate": "2020-06-01", "endDate": "2021-02-01"},
        ],
        "primaryEducation": [{"name": "МГУ", "organization": "ВМК", "result": "Прикладная математика", "year": 2020}],
        "photoUrls": [{"big": f"https://img.hhcdn.ru/photo/{resume_hash}.jpeg", "small": "s.jpeg"}],
    }
    fields = {
        "hash": resume_hash,
        "updated": UPDATED_MS,
        "title": f"Python-разработчик {resume_hash}",
        "area": {"id": 1, "title": "Москва"},
        "age": 25 + i,
        "salary": {"amount": 200000, "currency": "RUR"},
        "skills": "Люблю асинхронщину",
        "keySkills": [{"string": "Python"}, {"string": "FastAPI"}, {"string": "PostgreSQL"}],
        "humanDatesRules": {"60": {"translation": "минуту"}},
        **(visible if logged_in else hidden),
    }
    return {k: field_(v) for k, v in fields.items()}


def page_html(title: str, state: dict | None, body: str = "") -> str:
    template = (
        f'<template id="HH-Lux-InitialState">{html.escape(json.dumps(state, ensure_ascii=False))}</template>'
        if state is not None
        else ""
    )
    return f"<html><head><title>{title}</title></head><body>{body}{template}</body></html>"


# Разметка первых шагов снята с hh.ru (data-qa); код и капча — наше допущение, как в парсере
LOGIN_PAGE = """<!doctype html><html><head><title>Вход в личный кабинет</title></head><body>
<form data-qa="account-login-form" onsubmit="return false">
 <div class="step" id="role">
  <input type="radio" name="role" data-qa="account-type-card-APPLICANT" checked style="opacity:0;position:absolute">
  <input type="radio" name="role" data-qa="account-type-card-EMPLOYER" style="opacity:0;position:absolute">
  <span>Я ищу сотрудников</span>
  <button type="button" data-qa="submit-button">Войти</button>
 </div>
 <div class="step" id="login" hidden>
  <input type="text" name="username" data-qa="login-input-username">
  <button type="button" data-qa="account-login-submit-by-code">Дальше</button>
  <button type="button" data-qa="account-login-submit-by-password">Войти с паролем</button>
 </div>
 <div class="step" id="password" hidden><input type="password" name="password"></div>
 <div class="step" id="captcha" hidden>
  <img data-qa="account-captcha-picture" src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" width="120" height="40">
  <input type="text" data-qa="account-captcha-input">
 </div>
 <div class="step" id="code" hidden><input type="text" data-qa="otp-code-input" autocomplete="one-time-code"></div>
 <div data-qa="form-helper-error" id="error" hidden></div>
</form>
<script>
const $ = (q) => document.querySelector(q);
const show = (id) => document.querySelectorAll('.step').forEach((e) => (e.hidden = e.id !== id));
const fail = (text) => { $('#error').textContent = text; $('#error').hidden = false; };
const post = (body) => fetch('/account/do-login', {method: 'POST', body: JSON.stringify(body)}).then((r) => r.json());
const onEnter = (q, fn) => $(q).addEventListener('keydown', (e) => { if (e.key === 'Enter') fn(e.target.value); });
const login = () => $('[name=username]').value;
const done = (r) => (r.ok ? (location.href = '/employer') : fail(r.error));
$('[data-qa=submit-button]').onclick = () => {
  if ($('[data-qa=account-type-card-EMPLOYER]').checked) show('login');
};
$('[data-qa=account-login-submit-by-code]').onclick = () =>
  post({login: login()}).then((r) => (r.ok ? show(r.captcha ? 'captcha' : 'code') : fail(r.error)));
$('[data-qa=account-login-submit-by-password]').onclick = () => show('password');
onEnter('[name=password]', (v) => post({login: login(), password: v}).then(done));
onEnter('[data-qa=account-captcha-input]', (v) =>
  post({login: login(), captcha: v}).then((r) => (r.ok ? ($('#error').hidden = true, show('code')) : fail(r.error))));
onEnter('[data-qa=otp-code-input]', (v) => post({login: login(), code: v}).then(done));
</script></body></html>"""

EMPLOYER_LOGIN = "hr@example.com"
EMPLOYER_CODE = "123456"
EMPLOYER_PASSWORD = "secret-pass"
CAPTCHA_TEXT = "x7kq"


@dataclass
class FakeHH:
    per_page: int = 3
    total: int = 7
    captcha_on_search_page: int | None = None  # номер страницы с нуля, как на hh
    captcha_on_resume: str | None = None
    no_state_on_page: int | None = None
    status: int = 200
    updated: dict[str, int] = field(default_factory=dict)  # hash → время обновления, по умолчанию UPDATED_MS
    login_captcha: bool = False  # перед кодом hh просит символы с картинки
    login_page_broken: bool = False  # hh показал что-то незнакомое вместо формы входа
    gone: set[str] = field(default_factory=set)  # удалённые или скрытые резюме: страница отвечает 404
    visited: list[str] = field(default_factory=list)
    login_attempts: list[dict] = field(default_factory=list)

    def hashes_for_page(self, page: int) -> list[str]:
        start = page * self.per_page
        return [f"h{1000 + i}" for i in range(start, min(start + self.per_page, self.total))]

    @property
    def resumes_opened(self) -> list[str]:
        return [v.removeprefix("/resume/") for v in self.visited if v.startswith("/resume/")]

    async def handle(self, route) -> None:
        request = route.request
        url = urlparse(request.url)
        self.visited.append(url.path + (f"?{url.query}" if url.query else ""))
        logged_in = "hh_auth=1" in (await request.all_headers()).get("cookie", "")

        if url.path == "/account/do-login":
            await self.do_login(route, json.loads(request.post_data or "{}"))
            return
        if url.path == "/search/resume":
            page = int(parse_qs(url.query).get("page", ["0"])[0])
            body = self.search_page(page, logged_in)
        elif url.path.startswith("/resume/") and url.path.removeprefix("/resume/") in self.gone:
            await route.fulfill(status=404, content_type="text/html; charset=utf-8", body=page_html("Не найдено", None))
            return
        elif url.path.startswith("/resume/"):
            body = self.resume_page(url.path.removeprefix("/resume/"), logged_in)
        elif url.path == "/account/login":
            body = page_html("Технические работы", None) if self.login_page_broken else LOGIN_PAGE
        elif url.path == "/employer":
            body = page_html("Кабинет работодателя", {"userType": self.user_type(logged_in)})
        else:
            await route.fulfill(status=404, body="")
            return
        await route.fulfill(status=self.status, content_type="text/html; charset=utf-8", body=body)

    async def do_login(self, route, body: dict) -> None:
        self.login_attempts.append(body)
        headers = {}
        if body.get("login") != EMPLOYER_LOGIN:
            result = {"ok": False, "error": "Аккаунт не найден"}
        elif "password" in body:
            ok = body["password"] == EMPLOYER_PASSWORD
            result = {"ok": ok, "error": None if ok else "Неверный пароль"}
        elif "captcha" in body:
            ok = body["captcha"] == CAPTCHA_TEXT
            result = {"ok": ok, "error": None if ok else "Неверные символы"}
        elif "code" in body:
            ok = body["code"] == EMPLOYER_CODE
            result = {"ok": ok, "error": None if ok else "Неверный код"}
        else:  # отправили логин — hh шлёт код
            result = {"ok": True, "captcha": self.login_captcha}
        if result["ok"] and ("password" in body or "code" in body):
            headers["Set-Cookie"] = "hh_auth=1; Path=/"
        await route.fulfill(status=200, headers=headers, content_type="application/json", body=json.dumps(result))

    def user_type(self, logged_in: bool) -> str:
        return "employer" if logged_in else "anonymous"

    def search_page(self, page: int, logged_in: bool) -> str:
        if page == self.captcha_on_search_page:
            return page_html("Я не робот", None, "<img src='/account/captcha/image'>")
        if page == self.no_state_on_page:
            return page_html("Поиск", None)
        hashes = self.hashes_for_page(page)
        last = (self.total - 1) // self.per_page
        items = [search_item(h, i, self.updated.get(h, UPDATED_MS)) for i, h in enumerate(hashes)]
        items.append({"forbidden": {"reason": "hidden"}, "_attributes": {"hash": "hidden-1"}})
        state = {
            "userType": self.user_type(logged_in),
            "resumeSearchResult": {
                "resumes": items,
                "paging": {"next": {"page": page + 1, "disabled": page >= last}},
            },
        }
        return page_html("Поиск резюме", state)

    def resume_page(self, resume_hash: str, logged_in: bool) -> str:
        if resume_hash == self.captcha_on_resume:
            return page_html("Я не робот", None, "<img src='/account/captcha/image'>")
        i = int(resume_hash.removeprefix("h")) - 1000
        state = {"userType": self.user_type(logged_in), "resume": resume_state(resume_hash, logged_in, i)}
        return page_html("Резюме", state)
