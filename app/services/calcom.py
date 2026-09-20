"""cal.com API v2 (https://api.cal.com/v2). v1 закрыт с 2026-02-28.

Нужен API-ключ (app.cal.com → Settings → Developer → API keys) и заголовок
cal-api-version — без него API молча использует старую версию.
Бронирования читаем опросом (без вебхуков, чтобы не нужен был публичный URL).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from ..alerts import Event
from ..config import settings

BASE = "https://api.cal.com/v2"


class CalCom:
    def __init__(self, api_key: str, api_version: str):
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "cal-api-version": api_version,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _to_event(b: dict) -> Event | None:
        start_raw = b.get("start") or b.get("startTime")
        end_raw = b.get("end") or b.get("endTime")
        if not start_raw or not end_raw:
            return None
        start = datetime.fromisoformat(start_raw.replace("Z", "+00:00")).astimezone(settings.tz)
        end = datetime.fromisoformat(end_raw.replace("Z", "+00:00")).astimezone(settings.tz)
        title = b.get("title") or "cal.com встреча"
        attendees = b.get("attendees") or []
        names = ", ".join(a.get("name") or a.get("email", "") for a in attendees if isinstance(a, dict))
        if names:
            title = f"{title} ({names})"
        return Event(id=str(b.get("uid") or b.get("id")), title=title, start=start, end=end, source="calcom")

    async def upcoming(self, days: int = 7) -> list[Event]:
        params = {"status": "upcoming", "sortStart": "asc", "take": 100}
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(f"{BASE}/bookings", headers=self._headers, params=params)
            r.raise_for_status()
            payload = r.json()
        data = payload.get("data", payload)
        if isinstance(data, dict):
            data = data.get("bookings", [])
        horizon = datetime.now(timezone.utc) + timedelta(days=days)
        events: list[Event] = []
        for b in data:
            ev = self._to_event(b)
            if ev and ev.start.astimezone(timezone.utc) <= horizon:
                events.append(ev)
        return events

    async def reschedule(self, uid: str, start: datetime, reason: str | None = None) -> dict:
        body = {"start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}
        if reason:
            body["reschedulingReason"] = reason
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(f"{BASE}/bookings/{uid}/reschedule", headers=self._headers, json=body)
            r.raise_for_status()
            return r.json()

    async def cancel(self, uid: str, reason: str | None = None) -> dict:
        body = {"cancellationReason": reason or "Перенос по личным причинам"}
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(f"{BASE}/bookings/{uid}/cancel", headers=self._headers, json=body)
            r.raise_for_status()
            return r.json()

    async def ping(self) -> str:
        events = await self.upcoming(days=30)
        return f"cal.com OK: {len(events)} броней в ближайшие 30 дней"
