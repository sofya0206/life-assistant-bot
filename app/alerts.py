"""Правила ред-флагов. Чистые функции без LLM и без I/O — чтобы их можно было
тестировать и чтобы бот предупреждал даже без ключа Claude.

Входные данные:
- entries: список словарей из db (ts: ISO-строка, kind, data: dict)
- events: список Event (объединённые Google Calendar + cal.com)
- goals / progress: словари из db
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from statistics import median


@dataclass
class Event:
    id: str
    title: str
    start: datetime
    end: datetime
    source: str = "google"  # google | calcom
    all_day: bool = False

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


def _parse_ts(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


# ── сон ──────────────────────────────────────────────────────────────────


def sleep_hours_by_night(entries: list[dict]) -> dict[date, float]:
    """Ключ — дата пробуждения, значение — часы сна. Последняя запись за ночь побеждает."""
    nights: dict[date, float] = {}
    for e in entries:
        if e.get("kind") != "sleep":
            continue
        data = e.get("data") or {}
        hours = data.get("hours")
        start = _parse_ts(data.get("sleep_start"))
        end = _parse_ts(data.get("sleep_end"))
        if hours is None and start and end and end > start:
            hours = (end - start).total_seconds() / 3600
        if hours is None:
            continue
        wake = end or _parse_ts(e.get("ts"))
        if wake is None:
            continue
        nights[wake.date()] = float(hours)
    return nights


def sleep_baseline(entries: list[dict], today: date, window: int = 14) -> float | None:
    nights = sleep_hours_by_night(entries)
    history = sorted((d, h) for d, h in nights.items() if d < today)[-window:]
    if len(history) < 3:
        return None
    return float(median(h for _, h in history))


def sleep_alert(entries: list[dict], today: date, *, short_night: float = 6.0) -> str | None:
    nights = sleep_hours_by_night(entries)
    last = nights.get(today)
    if last is None:
        return None
    base = sleep_baseline(entries, today)
    if base is not None and last < base - 1.0:
        return (f"Сон {last:.1f} ч — заметно меньше твоей нормы ({base:.1f} ч). "
                f"Планируй день полегче и ложись сегодня раньше.")
    if last < short_night:
        return f"Сон {last:.1f} ч — меньше {short_night:g} ч. Сегодня без геройств."
    return None


# ── тренировки ───────────────────────────────────────────────────────────


def workout_gap_alert(entries: list[dict], now: datetime, *, gap_days: int = 3) -> str | None:
    last: datetime | None = None
    earliest: datetime | None = None
    for e in entries:
        ts = _parse_ts(e.get("ts"))
        if ts is None:
            continue
        if earliest is None or ts < earliest:
            earliest = ts
        if e.get("kind") == "workout" and (last is None or ts > last):
            last = ts
    if last is None:
        if earliest is None or (now.date() - earliest.date()).days < gap_days:
            return None
        return f"За последние {gap_days}+ дня тренировок не записано — поставим сегодня хотя бы 30 минут?"
    days = (now.date() - last.date()).days
    if days >= gap_days:
        return f"Тренировки не было {days} дн. — поставим сегодня хотя бы 30 минут?"
    return None


# ── еда ──────────────────────────────────────────────────────────────────


def breakfast_alert(entries: list[dict], now: datetime, *, after_hour: int = 11, before_hour: int = 14) -> str | None:
    if not (after_hour <= now.hour < before_hour):
        return None
    for e in entries:
        if e.get("kind") != "meal":
            continue
        ts = _parse_ts(e.get("ts"))
        if ts and ts.date() == now.date() and (e.get("data") or {}).get("meal_type") == "breakfast":
            return None
    return "Завтрак сегодня не записан — не пропускай его, это твой первый приём пищи."


# ── календарь ────────────────────────────────────────────────────────────


def calendar_flags(
    events: list[Event],
    day: date,
    *,
    max_events: int = 5,
    late_hour: int = 20,
    early_hour: int = 8,
    min_gap_min: int = 15,
    chain_len: int = 3,
    max_busy_hours: float = 6.0,
    deep_work_min: int = 90,
    work_start: int = 9,
    work_end: int = 19,
) -> list[str]:
    evs = sorted((e for e in events if not e.all_day and e.start.date() == day), key=lambda e: e.start)
    flags: list[str] = []
    if not evs:
        return flags

    for a, b in zip(evs, evs[1:]):
        if b.start < a.end:
            flags.append(
                f"Пересечение: «{a.title}» ({a.start:%H:%M}–{a.end:%H:%M}) и «{b.title}» "
                f"({b.start:%H:%M}–{b.end:%H:%M})."
            )

    if len(evs) >= max_events:
        flags.append(f"{len(evs)} событий за день — перегруз, что-то стоит перенести.")

    busy = sum(e.minutes for e in evs) / 60
    if busy > max_busy_hours:
        flags.append(f"Встречи занимают {busy:.1f} ч — почти весь день без свободного времени.")

    for e in evs:
        if e.start.hour >= late_hour:
            flags.append(f"«{e.title}» в {e.start:%H:%M} — поздно, съест вечер и сон.")
        elif e.start.hour < early_hour:
            flags.append(f"«{e.title}» в {e.start:%H:%M} — очень рано, проверь сон накануне.")

    chain = 1
    for a, b in zip(evs, evs[1:]):
        gap = (b.start - a.end).total_seconds() / 60
        chain = chain + 1 if 0 <= gap < min_gap_min else 1
        if chain == chain_len:
            flags.append(f"{chain_len} события подряд без перерыва (около {b.start:%H:%M}) — заложи 15 минут между ними.")

    tz = evs[0].start.tzinfo
    window_start = datetime.combine(day, time(work_start), tzinfo=tz)
    window_end = datetime.combine(day, time(work_end), tzinfo=tz)
    cursor = window_start
    best_gap = 0.0
    for e in evs:
        if e.start > cursor:
            best_gap = max(best_gap, (min(e.start, window_end) - cursor).total_seconds() / 60)
        cursor = max(cursor, e.end)
    if cursor < window_end:
        best_gap = max(best_gap, (window_end - cursor).total_seconds() / 60)
    if best_gap < deep_work_min:
        flags.append(
            f"Нет свободного окна от {deep_work_min} мин с {work_start}:00 до {work_end}:00 — "
            f"негде делать глубокую работу."
        )
    return flags


# ── цели ─────────────────────────────────────────────────────────────────


def goal_stale_alerts(goals: list[dict], progress: list[dict], now: datetime, *, stale_days: int = 5) -> list[str]:
    last_by_goal: dict[int, datetime] = {}
    for p in progress:
        ts = _parse_ts(p.get("ts"))
        gid = p.get("goal_id")
        if ts is None or gid is None:
            continue
        if gid not in last_by_goal or ts > last_by_goal[gid]:
            last_by_goal[gid] = ts
    flags: list[str] = []
    for g in goals:
        if g.get("status", "active") != "active":
            continue
        ref = last_by_goal.get(g["id"]) or _parse_ts(g.get("created_at"))
        if ref is None:
            continue
        days = (now.date() - ref.date()).days
        if days >= stale_days:
            flags.append(f"Цель «{g['title']}»: нет прогресса {days} дн. Что сделаешь по ней на этой неделе?")
    return flags


# ── всё вместе ───────────────────────────────────────────────────────────


def collect_alerts(
    entries: list[dict],
    events: list[Event],
    goals: list[dict],
    progress: list[dict],
    now: datetime,
    *,
    days_ahead: int = 1,
) -> list[str]:
    alerts: list[str] = []
    for fn in (lambda: sleep_alert(entries, now.date()),
               lambda: workout_gap_alert(entries, now),
               lambda: breakfast_alert(entries, now)):
        msg = fn()
        if msg:
            alerts.append(msg)
    for offset in range(days_ahead):
        day = now.date() + timedelta(days=offset)
        prefix = "" if offset == 0 else f"{day:%d.%m}: "
        alerts.extend(prefix + f for f in calendar_flags(events, day))
    alerts.extend(goal_stale_alerts(goals, progress, now))
    return alerts
