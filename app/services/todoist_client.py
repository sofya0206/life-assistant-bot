"""Todoist unified API v1 (https://api.todoist.com/api/v1). Старый /rest/v2 закрыт.
Токен: Todoist → Settings → Integrations → Developer."""
from __future__ import annotations

import httpx

BASE = "https://api.todoist.com/api/v1"


class Todoist:
    def __init__(self, token: str):
        self._headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def tasks(self, query: str = "today | overdue", limit: int = 100) -> list[dict]:
        """Задачи по фильтру Todoist (синтаксис как в приложении: 'today', '7 days', 'overdue')."""
        results: list[dict] = []
        cursor: str | None = None
        async with httpx.AsyncClient(timeout=20) as client:
            while True:
                params = {"query": query, "lang": "ru", "limit": 50}
                if cursor:
                    params["cursor"] = cursor
                r = await client.get(f"{BASE}/tasks/filter", headers=self._headers, params=params)
                r.raise_for_status()
                payload = r.json()
                results.extend(payload.get("results", []))
                cursor = payload.get("next_cursor")
                if not cursor or len(results) >= limit:
                    break
        return results[:limit]

    async def add_task(self, content: str, due_string: str | None = None, priority: int | None = None,
                       description: str | None = None) -> dict:
        body: dict = {"content": content}
        if due_string:
            body["due_string"] = due_string
            body["due_lang"] = "ru"
        if priority:
            body["priority"] = max(1, min(4, int(priority)))
        if description:
            body["description"] = description
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(f"{BASE}/tasks", headers=self._headers, json=body)
            r.raise_for_status()
            return r.json()

    async def close_task(self, task_id: str) -> None:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(f"{BASE}/tasks/{task_id}/close", headers=self._headers)
            r.raise_for_status()

    async def ping(self) -> str:
        tasks = await self.tasks("today | overdue")
        return f"Todoist OK: {len(tasks)} задач на сегодня/просрочено"
