"""Планировщик: один экземпляр на всю систему, иначе задачи задвоятся.

taskiq scheduler app.tasks.scheduler:scheduler
"""

from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

import app.tasks.collect  # noqa: F401  регистрирует задачи с расписанием
from app.tasks.broker import api_broker

scheduler = TaskiqScheduler(api_broker, sources=[LabelScheduleSource(api_broker)])
