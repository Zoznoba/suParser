# HR-парсер соискателей

Собирает анкеты с SuperJob / hh.ru / LinkedIn в общую ленту для команды HR.
Статусы и комментарии синхронизируются между всеми пользователями в реальном времени.
Описание MVP — [refs/HR-parser_MVP.pdf](refs/HR-parser_MVP.pdf).

**Стек:** Python 3.12, FastAPI, SQLAlchemy (async) + Alembic, PostgreSQL 17, Redis 7, TaskIQ, Playwright ·
React 19, TanStack Query, React Router, Tailwind 4, Vite (Node 22).

## Состояние

Готово: лента с фильтрами и поиском, карточки, статусы, комментарии, склейка дублей между площадками,
актуальность анкет, realtime и присутствие, профили поиска и управление источниками из интерфейса.

| Источник | Как собирается | Статус |
|---|---|---|
| SuperJob | сайт через Playwright (`SUPERJOB_MODE=browser`), пока API-приложение не верифицировано | работает, но **без ФИО** |
| hh.ru | сайт через Playwright, вход работодателя из интерфейса | работает |
| LinkedIn | актор Apify, без своего аккаунта | работает, ~25 профилей в сутки |

Не готово к проду: фронт отдаётся dev-сервером Vite, нет TLS, ограничения попыток входа и бэкапов БД.
Открытые задачи по приоритетам — в [BACKLOG.md](BACKLOG.md).

## Архитектура

```
 React SPA ──HTTP /api──► FastAPI ──► PostgreSQL
     ▲                      │  ▲
     └────WebSocket /api/ws─┘  │ Redis pub/sub "events"
                               │
 taskiq scheduler ─► Redis ─► worker-api      (SuperJob API, LinkedIn/Apify, dispatch)
   (dispatch/мин)    queues └► worker-browser (Playwright: hh, SuperJob-сайт; concurrency 1)
```

- **Парсеры** (`backend/app/parsers`) реализуют общий `SourceParser.search()` → `ParsedResume`.
  API-парсеры (SuperJob) и браузерные (`BrowserParser`: сессия, паузы, детект капчи) живут в разных очередях.
- **Сбор**: `dispatch` раз в минуту ставит задачи по профилям, у которых подошёл интервал.
  Один источник — один активный сбор (Redis-lock). Капча / ошибка → источник `needs_attention`, в UI плашка.
- **Карточка** = `candidates`, её резюме на площадках = `candidate_sources` (unique `source+external_id`).
  Повторный сбор обновляет данные резюме, но не трогает статус и комментарии.
- **Актуальность** (`services/stale.py`): анкета неактуальна, если все её резюме сняты с площадок (404)
  или не попадались в поиске `STALE_AFTER_DAYS` (2) дня. Отсчёт — от последнего *полного* обхода площадки:
  пока источник на паузе или обход обрывается дневным лимитом страниц, резюме не «стареют». Неактуальные скрыты
  из ленты по умолчанию (фильтр «Актуальность»), из базы не удаляются; попалось снова — вернётся в ленту.
- **Совместная работа**: статус меняется с проверкой «кто успел первым» — если коллега сменил его раньше, 409
  с именем и новым статусом. Кто сейчас открыл анкету (карточку или тред), видно в ленте и в карточке
  (WS-сообщение `view`, состояние в Redis). Свои комментарии можно править и удалять.
- **Realtime**: любое изменение публикуется в Redis-канал, каждый процесс API пересылает событие своим
  WebSocket-клиентам, фронт обновляет кэш TanStack Query.
- **Доступ**: регистрации нет, пользователей заводит админ через CLI. Сессия — httpOnly cookie, хранится в Redis.

## Запуск

Всё в Docker:

```bash
cp backend/.env.example backend/.env    # по умолчанию SUPERJOB_MODE=mock — фейковые резюме без ключей
docker compose up --build
docker compose exec api python -m app.cli create-user admin "Имя Фамилия"
# http://localhost:5173
```

Локальная разработка (в Docker только Postgres и Redis):

```bash
docker compose up -d postgres redis
cd backend && cp .env.example .env && uv sync
uv run alembic upgrade head
uv run python -m app.cli create-user admin "Имя Фамилия"
uv run uvicorn app.main:app --reload
uv run taskiq worker app.tasks.broker:api_broker app.tasks.collect --reload
uv run taskiq scheduler app.tasks.scheduler:scheduler

cd frontend && nvm use && npm install && npm run dev    # Node 22
```

## Тесты

```bash
# бэкенд: настоящие Postgres и Redis из compose; база hr_test пересоздаётся миграциями, Redis — db 15
docker compose up -d postgres redis
cd backend && uv run pytest

# фронт: vitest + Testing Library (jsdom)
cd frontend && npm test

# линтер и типы
cd backend && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run typecheck
```

- Задачи TaskIQ в тестах (`ENVIRONMENT=test`) идут через `InMemoryBroker` и выполняются сразу — путь
  «API → очередь → парсер → лента» проверяется целиком в одном процессе.
- HTTP SuperJob мокается через `respx`, WebSocket проверяется через `httpx-ws` (in-process ASGI).
- Другие адреса БД/Redis: `TEST_DATABASE_URL`, `TEST_REDIS_URL`.

## SuperJob

1. Зарегистрировать приложение: https://api.superjob.ru/register → `SUPERJOB_APP_ID` (id) и `SUPERJOB_SECRET` (secret key).
2. Логин/пароль аккаунта **работодателя** → `SUPERJOB_LOGIN` / `SUPERJOB_PASSWORD`
   (поиск резюме доступен только авторизованному работодателю; контакты — по тарифу).
3. `SUPERJOB_MODE=api`.

### Пока API не верифицирован: сайт через Playwright

`SUPERJOB_MODE=browser` — сбор идёт с superjob.ru в браузерной очереди.

- Данные берутся из `window.APP_STATE` страницы поиска: ~30 резюме за переход, в сами резюме не заходим.
  id резюме те же, что в API, — после переключения на `api` карточки не задвоятся.
- Бережный режим: пауза 8–20 с между страницами, до `SUPERJOB_WEB_MAX_PAGES` страниц на профиль за запуск,
  не больше `BROWSER_DAILY_PAGE_LIMIT` страниц в сутки, один браузер на источник, сессия переиспользуется.
- С `SUPERJOB_LOGIN/PASSWORD` парсер входит как работодатель (видно ФИО и больше резюме); без них — только открытая база.
- Если SuperJob при входе просит код из SMS/почты или показывает капчу — источник встаёт на паузу
  (плашка в интерфейсе, скриншот в `backend/.browser-state/debug/`). Войти вручную один раз:
  `uv run python -m app.cli browser-login superjob` → откроется окно браузера, сессия сохранится
  в `backend/.browser-state/` (её же подхватывает docker-воркер). Потом «Исправлено, продолжить» в интерфейсе.
- Воркер: `uv run taskiq worker app.tasks.broker:browser_broker app.tasks.collect app.tasks.login --workers 1 --max-async-tasks 1`
  или `docker compose --profile browser up`.

## hh.ru

Сбор идёт через Playwright в браузерной очереди (`docker compose --profile browser up`).

- Данные берутся не из вёрстки, а из JSON-состояния страницы (`<template id="HH-Lux-InitialState">`):
  поиск → `resumeSearchResult.resumes` (по 20 на страницу), резюме → `resume`.
- Поиск по всему тексту резюме, по релевантности, только среди обновлённых за `HH_SEARCH_PERIOD_DAYS` дней
  (по умолчанию 3) — свежие и без шума. Сортировка «по дате» при поиске по всему тексту тащит нерелевантные
  резюме, поэтому свежесть задаётся фильтром. Без параметров `logic/pos/exp_period` hh молча игнорирует текст.
- Поиск даёт только краткую карточку, поэтому в каждое резюме парсер заходит отдельно (`HH_OPEN_RESUMES=true`):
  это +1 страница дневного бюджета за резюме. Разобранное резюме кешируется в Redis на `HH_RESUME_CACHE_DAYS`
  по времени его обновления — неизменённые резюме повторно не открываются.
- Контакты парсер не открывает никогда: на hh это платное действие.
- Капча / 403 / 429 / страница без данных → пауза источника и скриншот, как у SuperJob.
  404 на резюме — удалено или скрыто соискателем: пропускаем, анкета становится неактуальной.
- **Ручной импорт по ссылке** (кнопка «По ссылке» в ленте) — резервный вариант из ТЗ на случай блокировки
  аккаунта: браузерный воркер открывает резюме *без входа* (без ФИО, опыта и контактов), итог приходит
  WS-событием `import.finished`. Страница тратит дневной бюджет hh; уже известное резюме открывается сразу.

### Вход работодателя

Без входа hh отдаёт урезанные резюме (без ФИО, опыта, образования, фото), поэтому по умолчанию
`HH_REQUIRE_LOGIN=true`: нет сессии или она истекла — источник на паузе и в интерфейсе плашка с кнопкой «Войти».

- **Из интерфейса** (Поиск → Источники → «Войти», или кнопка на плашке): браузер в `worker-browser` открывает
  страницу входа hh, а HR по скриншотам вводит почту/телефон, затем код из SMS/письма (или сразу пароль)
  и, если hh попросит, символы капчи. Окно можно закрыть — вход продолжится; коллеги видят тот же вход.
  Шаг ждёт ответа `BROWSER_LOGIN_INPUT_TIMEOUT` секунд (300). Сессия сохраняется в `backend/.browser-state/`.
- **Вручную** на машине с экраном: `uv run python -m app.cli browser-login hh` — если hh покажет
  незнакомый шаг, вход из интерфейса падает со скриншотом и предлагает этот вариант.
- Как это устроено: `app/parsers/browser/login.py` (канал «воркер ↔ UI» через Redis + WS-событие `source.login`),
  `HHParser.ui_login`, задача `app/tasks/login.py`, API `/api/sources/{source}/login`.

## LinkedIn

Своего аккаунта LinkedIn и браузера нет: поиск людей идёт через актор Apify
[harvestapi/linkedin-profile-search](https://apify.com/harvestapi/linkedin-profile-search) — они сами ходят в LinkedIn
и отдают профили JSON-ом. У нас это обычный HTTP-запрос в очереди `api`.

1. Зарегистрироваться на https://console.apify.com (бесплатный план — $5 кредитов в месяц, карта не нужна).
2. Settings → API & Integrations → токен в `APIFY_TOKEN`. Без токена источник в интерфейсе «скоро».
3. Поиск — по ключевым словам профиля, как в строке поиска людей LinkedIn; `LINKEDIN_LOCATION` — фильтр по городу/стране.

- Цена: $0.10 за страницу поиска (до 25 профилей), даже если страница пустая. `LINKEDIN_PROFILE_MODE=Full`
  добавляет опыт, образование и навыки за $0.004 за профиль (страница из 25 — $0.20 вместо $0.10).
- Расход ограничен `LINKEDIN_DAILY_PAGE_LIMIT` страниц в сутки на **все** профили вместе (по умолчанию 1 ≈ $3/мес,
  в бесплатные $5 влезает). Бюджет исчерпан — сбор тихо пропускается до завтра; первым его берёт профиль,
  до которого раньше дошёл планировщик. Каждый запуск актора ещё и ограничен сверху `maxTotalChargeUsd`.
- Неверный токен или закончились кредиты → источник `needs_attention`, плашка в интерфейсе.
- Контактов нет: только то, что видно в профиле.

## Полезное

- API-документация: http://localhost:8000/docs
- Новая миграция: `uv run alembic revision --autogenerate -m "..."`
- Пользователи: `python -m app.cli create-user | set-password | deactivate`
- Браузерный воркер (SuperJob-сайт, hh.ru): `docker compose --profile browser up`
- Настройки не из `.env.example` (полный список — `backend/app/core/config.py`):
  `COOKIE_SECURE` (true за HTTPS), `SESSION_TTL_SECONDS`, `STALE_AFTER_DAYS` / `STALE_CRON`, `DISPATCH_CRON`,
  `HH_RESUME_CACHE_DAYS`, `BROWSER_LOGIN_INPUT_TIMEOUT`, `SUPERJOB_MAX_PAGES`, `LINKEDIN_RUN_TIMEOUT`.

## Структура

```
backend/app/
  api/        HTTP-роуты и WebSocket /api/ws
  services/   лента, склейка дублей (matching), актуальность (stale), источники
  parsers/    superjob/ (api, сайт, mock), hh/, linkedin/, browser/ (общая база и вход из UI)
  tasks/      TaskIQ: брокеры, сбор, вход, планировщик
  realtime/   события Redis pub/sub → WebSocket, присутствие
  models/ schemas/ core/   ORM, Pydantic-схемы, конфиг/БД/Redis/сессии
frontend/src/
  pages/ components/   экраны и компоненты
  api/                 клиент и хуки TanStack Query
  realtime/            WebSocket и обновление кэша по событиям
```
