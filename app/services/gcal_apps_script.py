"""Google Calendar через бесплатный Google Apps Script Web App."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import httpx

from ..alerts import Event
from ..config import settings


class GoogleAppsScriptCalendar:
    def __init__(
        self,
        url: str,
        secret: str,
        calendar_ids: tuple[str, ...],
        tz_name: str,
    ):
        self.url = url
        self.secret = secret
        self.calendar_ids = calendar_ids
        self.create_calendar_id = calendar_ids[0] if calendar_ids else "primary"
        self.tz_name = tz_name

    async def _request(self, action: str, **data) -> dict:
        payload = {"action": action, "secret": self.secret, **data}
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.post(self.url, json=payload)
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "Google Apps Script вернул ошибку")
        return result

    @staticmethod
    def _to_event(item: dict) -> Event:
        all_day = bool(item.get("all_day"))
        if all_day:
            start = datetime.combine(date.fromisoformat(item["start"][:10]), time(0), tzinfo=settings.tz)
            end = datetime.combine(date.fromisoformat(item["end"][:10]), time(0), tzinfo=settings.tz)
        else:
            start = datetime.fromisoformat(item["start"].replace("Z", "+00:00")).astimezone(settings.tz)
            end = datetime.fromisoformat(item["end"].replace("Z", "+00:00")).astimezone(settings.tz)
        return Event(
            id=item["id"],
            title=item.get("title") or "(без названия)",
            start=start,
            end=end,
            source="google",
            all_day=all_day,
        )

    async def list_events(self, start: datetime, end: datetime) -> list[Event]:
        result = await self._request(
            "list",
            start=start.isoformat(),
            end=end.isoformat(),
            calendar_ids=list(self.calendar_ids),
        )
        return [self._to_event(item) for item in result.get("events", [])]

    async def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        description: str | None = None,
    ) -> Event:
        result = await self._request(
            "create",
            calendar_id=self.create_calendar_id,
            title=title,
            start=start.isoformat(),
            end=end.isoformat(),
            description=description or "",
        )
        return self._to_event(result["event"])

    async def move_event(self, event_id: str, start: datetime, end: datetime) -> Event:
        result = await self._request(
            "move", event_id=event_id, start=start.isoformat(), end=end.isoformat()
        )
        return self._to_event(result["event"])

    async def delete_event(self, event_id: str) -> None:
        await self._request("delete", event_id=event_id)

    async def ping(self) -> str:
        now = datetime.now(settings.tz)
        events = await self.list_events(now, now + timedelta(days=1))
        return f"Google Calendar OK: {len(events)} событий в ближайшие сутки"
