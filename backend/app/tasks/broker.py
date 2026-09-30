"""Две очереди TaskIQ поверх Redis.

- api_broker: лёгкие HTTP-парсеры (SuperJob API, LinkedIn через Apify) и служебные задачи (dispatch);
- browser_broker: Playwright-парсеры (hh, SuperJob-сайт), отдельный воркер с concurrency 1.

Воркеры:
    taskiq worker app.tasks.broker:api_broker app.tasks.collect
    taskiq worker app.tasks.broker:browser_broker app.tasks.collect app.tasks.login --workers 1 --max-async-tasks 1
"""

from taskiq import AsyncBroker, InMemoryBroker, TaskiqEvents, TaskiqState
from taskiq_redis import ListQueueBroker

from app.core.config import settings

# redis-py 8 по умолчанию ставит socket_timeout=5s, а воркер висит на блокирующем BRPOP без таймаута
_redis_kwargs = {"socket_timeout": None, "health_check_interval": 30}

api_broker: AsyncBroker
browser_broker: AsyncBroker
if settings.environment == "test":
    # в тестах задачи выполняются сразу в том же процессе, .kiq() дожидается результата
    api_broker = InMemoryBroker(await_inplace=True)
    browser_broker = InMemoryBroker(await_inplace=True)
else:
    api_broker = ListQueueBroker(settings.redis_url, queue_name="hr:queue:api", **_redis_kwargs)
    browser_broker = ListQueueBroker(settings.redis_url, queue_name="hr:queue:browser", **_redis_kwargs)


@api_broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _api_worker_startup(_: TaskiqState) -> None:
    # dispatch из api-воркера ставит задачи и в браузерную очередь
    await browser_broker.startup()


@api_broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def _api_worker_shutdown(_: TaskiqState) -> None:
    await browser_broker.shutdown()
