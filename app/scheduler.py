"""Проактивные сообщения по расписанию (Telegram сам ничего не шлёт —
бот должен пушить). APScheduler на asyncio-цикле aiogram."""
from __future__ import annotations

import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from . import briefs
from .config import settings
from .render import split_message

log = logging.getLogger(__name__)


async def _send(bot: Bot, text: str, reply_markup=None) -> None:
    if settings.chat_id is None:
        log.warning("CHAT_ID не задан — некому слать %s", text[:40])
        return
    chunks = split_message(text)
    for i, chunk in enumerate(chunks):
        await bot.send_message(settings.chat_id, chunk,
                               reply_markup=reply_markup if i == len(chunks) - 1 else None)


async def send_morning(bot: Bot) -> None:
    try:
        await _send(bot, await briefs.morning_brief())
    except Exception:  # noqa: BLE001
        log.exception("morning brief failed")


async def send_breakfast_check(bot: Bot) -> None:
    try:
        text = await briefs.breakfast_check()
        if text:
            await _send(bot, text)
    except Exception:  # noqa: BLE001
        log.exception("breakfast check failed")


async def send_evening(bot: Bot) -> None:
    try:
        text, keyboard = await briefs.evening_checkin()
        await _send(bot, text, keyboard)
    except Exception:  # noqa: BLE001
        log.exception("evening check-in failed")


def start(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.tz)
    jobs = []
    if settings.morning_brief_enabled:
        jobs.append(("morning", send_morning, settings.morning_time))
    if settings.health_checkins_enabled:
        jobs.extend((
            ("breakfast", send_breakfast_check, settings.breakfast_check_time),
            ("evening", send_evening, settings.evening_time),
        ))
    for job_id, fn, (hh, mm) in jobs:
        scheduler.add_job(fn, CronTrigger(hour=hh, minute=mm, timezone=settings.tz),
                          args=[bot], id=job_id, misfire_grace_time=3600, coalesce=True)
    scheduler.start()
    log.info("Планировщик: %s", ", ".join(f"{j[0]} {j[2][0]:02d}:{j[2][1]:02d}" for j in jobs) or "выключен")
    return scheduler
