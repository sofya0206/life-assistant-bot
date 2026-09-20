"""Google Calendar через сервисный аккаунт.

Почему не OAuth: для одного пользователя проще расшарить свой календарь на
email сервисного аккаунта (право «Внесение изменений»), и никаких consent
screen / протухающих refresh-токенов. Ограничение: сервисный аккаунт не может
добавлять участников (attendees) в события — для личного планирования это не нужно.

API синхронное (googleapiclient), поэтому вызываем через asyncio.to_thread.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build

from ..alerts import Event
from ..config import settings

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class GoogleCalendar:
    def __init__(self, sa_file: str, calendar_id: str, tz_name: str):
        creds = service_account.Credentials.from_service_account_file(sa_file, scopes=SCOPES)
        self._svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
        self.calendar_id = calendar_id
        self.tz_name = tz_name

    # ── parsing ──────────────────────────────────────────────────────────

    def _to_event(self, item: dict) -> Event:
        start_raw = item.get("start", {})
        end_raw = item.get("end", {})
        if "dateTime" in start_raw:
            start = datetime.fromisoformat(start_raw["dateTime"]).astimezone(settings.tz)
            end = datetime.fromisoformat(end_raw["dateTime"]).astimezone(settings.tz)
            all_day = False
        else:
            start = datetime.combine(date.fromisoformat(start_raw["date"]), time(0), tzinfo=settings.tz)
            end = datetime.combine(date.fromisoformat(end_raw["date"]), time(0), tzinfo=settings.tz)
            all_day = True
        return Event(
            id=item["id"],
            title=item.get("summary") or "(без названия)",
            start=start,
            end=end,
            source="google",
            all_day=all_day,
        )

    # ── sync core ────────────────────────────────────────────────────────

    def _list(self, start: datetime, end: datetime) -> list[Event]:
        res = self._svc.events().list(
            calendarId=self.calendar_id,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=200,
        ).execute()
        return [self._to_event(i) for i in res.get("items", []) if i.get("status") != "cancelled"]

    def _create(self, title: str, start: datetime, end: datetime, description: str | None) -> Event:
        body = {
            "summary": title,
            "start": {"dateTime": start.isoformat(), "timeZone": self.tz_name},
            "end": {"dateTime": end.isoformat(), "timeZone": self.tz_name},
        }
        if description:
            body["description"] = description
        item = self._svc.events().insert(calendarId=self.calendar_id, body=body).execute()
        return self._to_event(item)

    def _move(self, event_id: str, start: datetime, end: datetime) -> Event:
        body = {
            "start": {"dateTime": start.isoformat(), "timeZone": self.tz_name},
            "end": {"dateTime": end.isoformat(), "timeZone": self.tz_name},
        }
        item = self._svc.events().patch(calendarId=self.calendar_id, eventId=event_id, body=body).execute()
        return self._to_event(item)

    def _delete(self, event_id: str) -> None:
        self._svc.events().delete(calendarId=self.calendar_id, eventId=event_id).execute()

    # ── async API ────────────────────────────────────────────────────────

    async def list_events(self, start: datetime, end: datetime) -> list[Event]:
        return await asyncio.to_thread(self._list, start, end)

    async def create_event(self, title: str, start: datetime, end: datetime, description: str | None = None) -> Event:
        return await asyncio.to_thread(self._create, title, start, end, description)

    async def move_event(self, event_id: str, start: datetime, end: datetime) -> Event:
        return await asyncio.to_thread(self._move, event_id, start, end)

    async def delete_event(self, event_id: str) -> None:
        await asyncio.to_thread(self._delete, event_id)

    async def ping(self) -> str:
        now = datetime.now(settings.tz)
        events = await self.list_events(now, now + timedelta(days=1))
        return f"Google Calendar OK: {len(events)} событий в ближайшие сутки"
