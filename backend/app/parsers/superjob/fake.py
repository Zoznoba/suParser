"""Фейковые ответы SuperJob для разработки без ключей API (SUPERJOB_MODE=mock)."""

import random
import time
from typing import Any

FIRST_M = ["Иван", "Алексей", "Дмитрий", "Сергей", "Павел"]
FIRST_F = ["Анна", "Мария", "Ольга", "Елена", "Наталья"]
LAST = ["Иванов", "Смирнов", "Кузнецов", "Попов", "Васильев", "Петров", "Соколов", "Михайлов", "Новиков", "Фёдоров"]
TOWNS = ["Москва", "Санкт-Петербург", "Казань", "Новосибирск", "Екатеринбург"]
COMPANIES = ["Яндекс", "Сбер", "Тинькофф", "Ozon", "Wildberries", "VK", "Авито"]


def fake_search(keyword: str, page: int, count: int) -> dict[str, Any]:
    # пул из 300 id: повторные запуски частично пересекаются — видно дедупликацию и новые анкеты
    rnd = random.Random()
    objects = []
    for _ in range(min(count, 10)):
        rid = rnd.randint(1, 300)
        r = random.Random(rid)
        female = r.random() < 0.5
        position = keyword.split(",")[0].strip().capitalize()
        objects.append(
            {
                "id": 900000 + rid,
                "firstname": r.choice(FIRST_F if female else FIRST_M),
                "lastname": r.choice(LAST) + ("а" if female else ""),
                "profession": f"{position} ({r.choice(['Junior', 'Middle', 'Senior'])})",
                "town": {"id": 1, "title": r.choice(TOWNS)},
                "age": r.randint(20, 50),
                "payment": r.randrange(80_000, 400_000, 10_000),
                "currency": "rub",
                "link": f"https://www.superjob.ru/resume/fake-{rid}.html",
                "date_published": int(time.time()) - r.randint(0, 86400 * 30),
                "work_history": [
                    {
                        "name": r.choice(COMPANIES),
                        "profession": keyword,
                        "yearbeg": 2015 + i * 3,
                        "monthbeg": r.randint(1, 12),
                        "yearend": 2018 + i * 3 if i < 2 else None,
                        "work": "Разработка и поддержка сервисов, код-ревью, менторинг.",
                    }
                    for i in range(r.randint(1, 3))
                ],
                "base_education_history": [{"institute": {"title": "МГТУ им. Баумана"}, "yearend": 2014}],
                "catalogues": [{"title": "IT, Интернет, связь, телеком"}],
            }
        )
    return {"objects": objects, "total": len(objects), "more": False}
