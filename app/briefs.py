"""Утренний бриф, проверка завтрака, вечерний чек-ин, недельный обзор."""
from __future__ import annotations

import logging
from datetime import timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import db, llm
from .alerts import breakfast_alert, sleep_baseline, sleep_hours_by_night
from .config import settings
from .context import entries_summary, goals_text, snapshot
from .prompts import BRIEF_PROSE_PROMPT, WEEK_REVIEW_PROMPT
from .render import esc, fmt_range

log = logging.getLogger(__name__)


async def _maybe_prose(prompt: str) -> str | None:
    if not settings.llm_enabled:
        return None
    try:
        return await llm.prose(prompt)
    except Exception as exc:  # noqa: BLE001
        log.warning("LLM prose failed: %s", exc)
        return None


async def morning_brief() -> str:
    snap = await snapshot(days_ahead=1, alert_days=1)
    today = snap.now.date()
    lines: list[str] = ["☀️ <b>Утренний бриф</b>"]

    nights = sleep_hours_by_night(snap.entries)
    base = sleep_baseline(snap.entries, today)
    if today in nights:
        extra = f" (норма {base:.1f})" if base is not None else ""
        lines.append(f"😴 Сон: {nights[today]:.1f} ч{extra}")
    else:
        lines.append("😴 Сон не записан — скажи, во сколько легла и встала.")

    todays = [e for e in snap.events if e.start.date() == today]
    if todays:
        lines.append("📅 <b>Сегодня:</b>\n" + "\n".join(f"• {esc(fmt_range(e))} {esc(e.title)}" for e in todays))
    else:
        lines.append("📅 Сегодня календарь пустой.")

    due_today = [t for t in snap.tasks if (t.get("due") or {}).get("date", "9999") <= today.isoformat()]
    if due_today:
        lines.append("✅ <b>Задачи:</b>\n" + "\n".join(f"• {esc(t.get('content', ''))}" for t in due_today[:8]))

    if snap.goals:
        goal_lines = []
        for g in snap.goals:
            weekly = (g.get("smart") or {}).get("weekly_actions") or []
            hint = f" — {esc(weekly[0])}" if weekly else ""
            goal_lines.append(f"• {esc(g['title'])}{hint}")
        lines.append("🎯 <b>Цели:</b>\n" + "\n".join(goal_lines))

    if snap.alerts:
        lines.append("⚠️ <b>Ред-флаги:</b>\n" + "\n".join(f"• {esc(a)}" for a in snap.alerts))

    text = "\n\n".join(lines)
    if settings.llm_prose_in_brief:
        plain = text.replace("<b>", "").replace("</b>", "")
        prose = await _maybe_prose(BRIEF_PROSE_PROMPT.format(brief=plain))
        if prose:
            text += f"\n\n💡 {esc(prose)}"
    return text


async def breakfast_check() -> str | None:
    now = db.now_local()
    entries = db.entries_since(now - timedelta(days=1))
    msg = breakfast_alert(entries, now)
    return f"🍳 {esc(msg)}" if msg else None


def mood_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="😞 2", callback_data="mood:2"),
            InlineKeyboardButton(text="😐 5", callback_data="mood:5"),
            InlineKeyboardButton(text="🙂 7", callback_data="mood:7"),
            InlineKeyboardButton(text="😄 9", callback_data="mood:9"),
        ],
        [InlineKeyboardButton(text="🎙 Расскажу голосом", callback_data="mood:voice")],
    ])


async def evening_checkin() -> tuple[str, InlineKeyboardMarkup]:
    now = db.now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    entries = db.entries_between(start, now + timedelta(hours=3))
    meals = [e for e in entries if e["kind"] == "meal"]
    workouts = [e for e in entries if e["kind"] == "workout"]
    lines = ["🌙 <b>Вечерний чек-ин</b>"]
    lines.append(f"Сегодня записано: приёмов пищи — {len(meals)}, тренировок — {len(workouts)}.")
    missing = []
    if not meals:
        missing.append("еда")
    if not workouts:
        missing.append("тренировка")
    if missing:
        lines.append(f"Не записано: {', '.join(missing)}. Расскажи голосом, если было.")
    lines.append("Как день? Оцени настроение:")
    return "\n".join(lines), mood_keyboard()


async def week_review() -> str:
    now = db.now_local()
    entries = db.entries_since(now - timedelta(days=7))
    goals = db.list_goals()
    nights = sleep_hours_by_night(entries)
    workouts = [e for e in entries if e["kind"] == "workout"]
    meals = [e for e in entries if e["kind"] == "meal"]
    lines = ["📊 <b>Неделя</b>"]
    if nights:
        avg = sum(nights.values()) / len(nights)
        lines.append(f"😴 Сон: {len(nights)} ночей записано, в среднем {avg:.1f} ч "
                     f"(мин {min(nights.values()):.1f}, макс {max(nights.values()):.1f})")
    else:
        lines.append("😴 Сон за неделю не записан.")
    lines.append(f"🏃 Тренировок: {len(workouts)}; приёмов пищи записано: {len(meals)}")
    lines.append("📓 <b>Журнал:</b>\n" + esc(entries_summary(entries)))
    if goals:
        lines.append("🎯 <b>Цели:</b>\n" + esc(goals_text(goals)))
    text = "\n\n".join(lines)
    summary = entries_summary(entries) + "\n\nЦЕЛИ:\n" + goals_text(goals)
    prose = await _maybe_prose(WEEK_REVIEW_PROMPT.format(summary=summary))
    if prose:
        text += f"\n\n💡 {esc(prose)}"
    return text
