"""Применение подтверждённых действий: календарь, задачи, цели."""
from __future__ import annotations

import logging
from datetime import timedelta

from . import db, integrations
from .db import parse_iso
from .models import AssistantOutput, CalendarAction, TaskAction
from .render import esc, fmt_range

log = logging.getLogger(__name__)


async def _calendar(a: CalendarAction) -> str:
    if a.source == "calcom":
        client = integrations.calcom
        if client is None:
            return f"⚠️ cal.com не настроен: {esc(a.title)}"
        if a.op == "move" and a.event_id and a.start:
            await client.reschedule(a.event_id, parse_iso(a.start), a.note)
            return f"🔁 cal.com: «{esc(a.title)}» перенесена на {esc(fmt_range_iso(a.start, a.end))}"
        if a.op == "delete" and a.event_id:
            await client.cancel(a.event_id, a.note)
            return f"🗑 cal.com: «{esc(a.title)}» отменена"
        return f"⚠️ cal.com: брони создаются только по ссылке, пропустила «{esc(a.title)}»"

    g = integrations.google
    if g is None:
        return f"⚠️ Google Calendar не настроен: {esc(a.title)} {esc(fmt_range_iso(a.start, a.end))}"
    start = parse_iso(a.start)
    end = parse_iso(a.end)
    if a.op == "create":
        if not start:
            return f"⚠️ Не создала «{esc(a.title)}»: нет времени начала"
        end = end or start + timedelta(minutes=60)
        ev = await g.create_event(a.title, start, end, a.note)
        return f"📅 Создано: {esc(fmt_range(ev))} {esc(ev.title)}"
    if a.op == "move":
        if not (a.event_id and start):
            return f"⚠️ Не перенесла «{esc(a.title)}»: нет id или времени"
        end = end or start + timedelta(minutes=60)
        ev = await g.move_event(a.event_id, start, end)
        return f"🔁 Перенесено: {esc(fmt_range(ev))} {esc(ev.title)}"
    if a.op == "delete":
        if not a.event_id:
            return f"⚠️ Не удалила «{esc(a.title)}»: нет id"
        await g.delete_event(a.event_id)
        return f"🗑 Удалено: {esc(a.title)}"
    return f"⚠️ Неизвестная операция {a.op}"


def fmt_range_iso(start: str | None, end: str | None) -> str:
    from .render import fmt_iso_range

    return fmt_iso_range(start, end)


async def _task(t: TaskAction) -> str:
    client = integrations.todoist
    if client is None:
        return f"⚠️ Todoist не настроен: {esc(t.content)}"
    if t.op == "create":
        task = await client.add_task(t.content, t.due, t.priority)
        due = (task.get("due") or {}).get("string") or t.due or "без срока"
        return f"✅ Задача: {esc(task.get('content', t.content))} — {esc(due)}"
    if t.op == "complete" and t.task_id:
        await client.close_task(t.task_id)
        return f"☑️ Закрыта: {esc(t.content)}"
    return f"⚠️ Не поняла задачу: {esc(t.content)}"


async def apply(out: AssistantOutput) -> list[str]:
    results: list[str] = []
    for a in out.calendar_actions:
        try:
            results.append(await _calendar(a))
        except Exception as exc:  # noqa: BLE001
            log.exception("calendar action failed")
            results.append(f"❌ {esc(a.title)}: {esc(str(exc))[:200]}")
    for t in out.task_actions:
        try:
            results.append(await _task(t))
        except Exception as exc:  # noqa: BLE001
            log.exception("task action failed")
            results.append(f"❌ {esc(t.content)}: {esc(str(exc))[:200]}")
    for g in out.goals:
        goal_id = db.add_goal(g.title, g.model_dump(), g.deadline)
        results.append(f"🎯 Цель #{goal_id} сохранена: {esc(g.title)}" + (f" (до {esc(g.deadline)})" if g.deadline else ""))
    for p in out.goal_progress:
        db.add_goal_progress(p.goal_id, p.note, p.value)
        results.append(f"📈 Прогресс по цели #{p.goal_id}: {esc(p.note)}")
    return results
