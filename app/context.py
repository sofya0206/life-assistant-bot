"""Снимок «мира» для LLM и брифов: время, фокус недели, календарь, задачи,
цели, журнал, базовые нормы и ред-флаги по правилам."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import mean

from . import db, integrations
from .alerts import Event, collect_alerts, sleep_baseline, sleep_hours_by_night
from .config import settings
from .render import WEEKDAYS, entry_line, fmt_range


@dataclass
class Snapshot:
    now: datetime
    events: list[Event] = field(default_factory=list)
    tasks: list[dict] = field(default_factory=list)
    goals: list[dict] = field(default_factory=list)
    progress: list[dict] = field(default_factory=list)
    entries: list[dict] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    weekly_focus: str | None = None


async def snapshot(days_ahead: int = 7, days_back: int = 14, alert_days: int = 2) -> Snapshot:
    now = db.now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    events = await integrations.gather_events(start, start + timedelta(days=days_ahead))
    tasks = await integrations.gather_tasks("7 days | overdue")
    goals = db.list_goals()
    progress = db.goal_progress_since(now - timedelta(days=30))
    entries = db.entries_since(now - timedelta(days=days_back))
    alerts = collect_alerts(entries, events, goals, progress, now, days_ahead=alert_days)
    return Snapshot(now, events, tasks, goals, progress, entries, alerts, db.get_setting("weekly_focus"))


# ── текстовые сводки ─────────────────────────────────────────────────────


def task_line(t: dict) -> str:
    due = t.get("due") or {}
    when = due.get("string") or due.get("date") or "без срока"
    pr = f" p{t['priority']}" if t.get("priority", 1) > 1 else ""
    return f"[todoist:{t.get('id')}] {when}{pr}: {t.get('content', '')}"


def entries_by_day(entries: list[dict]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for e in entries:
        ts = db.parse_iso(e["ts"])
        if not ts:
            continue
        key = f"{WEEKDAYS[ts.weekday()]} {ts:%d.%m}"
        grouped[key].append(entry_line(e["kind"], e["data"]))
    return grouped


def entries_summary(entries: list[dict]) -> str:
    grouped = entries_by_day(entries)
    if not grouped:
        return "журнал пуст"
    return "\n".join(f"{day}: " + "; ".join(items) for day, items in grouped.items())


def baselines_text(entries: list[dict], now: datetime) -> str:
    parts: list[str] = []
    base = sleep_baseline(entries, now.date())
    nights = sleep_hours_by_night(entries)
    if base is not None:
        parts.append(f"сон, медиана за 14 дн: {base:.1f} ч")
    if nights.get(now.date()) is not None:
        parts.append(f"сон этой ночью: {nights[now.date()]:.1f} ч")
    week_ago = now - timedelta(days=7)
    workouts = [e for e in entries if e["kind"] == "workout" and (db.parse_iso(e["ts"]) or now) >= week_ago]
    parts.append(f"тренировок за 7 дн: {len(workouts)}")
    moods = [e["data"].get("score") for e in entries
             if e["kind"] == "mood" and isinstance(e["data"].get("score"), (int, float))
             and (db.parse_iso(e["ts"]) or now) >= week_ago]
    if moods:
        parts.append(f"среднее настроение за 7 дн: {mean(moods):.1f}/10")
    parts.append(f"целевой подъём: {settings.wake_target[0]:02d}:{settings.wake_target[1]:02d}, "
                 f"целевой сон: {settings.sleep_target_hours:g} ч")
    return "; ".join(parts)


def goals_text(goals: list[dict]) -> str:
    if not goals:
        return "целей нет"
    lines = []
    for g in goals:
        smart = g.get("smart") or {}
        weekly = "; ".join(smart.get("weekly_actions") or [])
        deadline = f", дедлайн {g['deadline']}" if g.get("deadline") else ""
        lines.append(f"[goal:{g['id']}] {g['title']}{deadline}" + (f" — на неделю: {weekly}" if weekly else ""))
    return "\n".join(lines)


def events_text(events: list[Event]) -> str:
    if not events:
        return "событий нет"
    return "\n".join(f"[{e.source}:{e.id}] {fmt_range(e)} {e.title}" for e in events)


def to_llm_text(snap: Snapshot) -> str:
    now = snap.now
    header = (f"Сейчас: {WEEKDAYS[now.weekday()]} {now.isoformat(timespec='minutes')} "
              f"(таймзона {settings.tz_name}). Даты в ответе — в этой таймзоне.")
    integrations_line = ("Подключено: "
                         f"google={'да' if integrations.google else 'нет'}, "
                         f"calcom={'да' if integrations.calcom else 'нет'}, "
                         f"todoist={'да' if integrations.todoist else 'нет'}")
    sections = [
        header,
        integrations_line,
        "ФОКУС НЕДЕЛИ: " + (snap.weekly_focus or "не выбран"),
        "КАЛЕНДАРЬ (ближайшие 7 дней):\n" + events_text(snap.events),
        "ЗАДАЧИ TODOIST (7 дней + просроченные):\n" + ("\n".join(task_line(t) for t in snap.tasks) or "задач нет"),
        "ЦЕЛИ:\n" + goals_text(snap.goals),
        "НОРМЫ: " + baselines_text(snap.entries, now),
        "ЖУРНАЛ (последние 14 дней):\n" + entries_summary(snap.entries),
        "РЕД-ФЛАГИ ПО ПРАВИЛАМ:\n" + ("\n".join(f"- {a}" for a in snap.alerts) or "нет"),
    ]
    return "\n\n".join(sections)
