"""Единая точка доступа к внешним сервисам. Каждый клиент создаётся только
если для него есть ключи; иначе None — и вызывающий код пропускает блок."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from .alerts import Event
from .config import settings
from .services.calcom import CalCom
from .services.gcal import GoogleCalendar
from .services.todoist_client import Todoist

log = logging.getLogger(__name__)

google: GoogleCalendar | None = None
calcom: CalCom | None = None
todoist: Todoist | None = None


def init() -> None:
    global google, calcom, todoist
    if settings.google_enabled:
        try:
            google = GoogleCalendar(settings.google_sa_file, settings.google_calendar_id, settings.tz_name)
        except Exception as exc:  # noqa: BLE001
            log.warning("Google Calendar не инициализирован: %s", exc)
    if settings.calcom_enabled:
        calcom = CalCom(settings.calcom_api_key, settings.calcom_api_version)
    if settings.todoist_enabled:
        todoist = Todoist(settings.todoist_token)
    log.info("Интеграции: google=%s calcom=%s todoist=%s llm=%s",
             bool(google), bool(calcom), bool(todoist), settings.llm_enabled)


async def gather_events(start: datetime, end: datetime) -> list[Event]:
    """Google + cal.com за период, отсортированные по началу. Ошибки одного
    сервиса не роняют другой."""
    tasks = []
    if google:
        tasks.append(google.list_events(start, end))
    if calcom:
        tasks.append(calcom.upcoming(days=max(1, (end - datetime.now(settings.tz)).days + 1)))
    events: list[Event] = []
    for res in await asyncio.gather(*tasks, return_exceptions=True):
        if isinstance(res, Exception):
            log.warning("Ошибка календаря: %s", res)
            continue
        events.extend(res)
    events = [e for e in events if e.end >= start and e.start <= end]
    events.sort(key=lambda e: e.start)
    return events


async def gather_tasks(query: str = "today | overdue") -> list[dict]:
    if not todoist:
        return []
    try:
        return await todoist.tasks(query)
    except Exception as exc:  # noqa: BLE001
        log.warning("Ошибка Todoist: %s", exc)
        return []


async def healthcheck() -> list[str]:
    lines: list[str] = []
    for name, client in (("Google Calendar", google), ("cal.com", calcom), ("Todoist", todoist)):
        if client is None:
            lines.append(f"{name}: не настроен")
            continue
        try:
            lines.append(await client.ping())
        except Exception as exc:  # noqa: BLE001
            lines.append(f"{name}: ошибка — {exc}")
    if settings.llm_enabled:
        lines.append(f"LLM: {settings.llm_provider}, модель {settings.llm_model}")
    else:
        lines.append("LLM: ключа нет (GEMINI_API_KEY / ANTHROPIC_API_KEY), тупой режим")
    return lines


def default_window(days_ahead: int = 7) -> tuple[datetime, datetime]:
    now = datetime.now(settings.tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=days_ahead)
