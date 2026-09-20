"""Форматирование для человека (HTML для Telegram) и для LLM (plain text)."""
from __future__ import annotations

import html
from datetime import datetime

from .alerts import Event
from .db import parse_iso
from .models import AssistantOutput

WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MEAL_RU = {"breakfast": "завтрак", "lunch": "обед", "dinner": "ужин", "snack": "перекус"}
INTENSITY_RU = {"low": "легко", "medium": "средне", "high": "тяжело"}


def esc(text: str | None) -> str:
    return html.escape(text or "", quote=False)


def fmt_dt(dt: datetime) -> str:
    return f"{WEEKDAYS[dt.weekday()]} {dt:%d.%m %H:%M}"


def fmt_range(ev: Event) -> str:
    if ev.all_day:
        return f"{WEEKDAYS[ev.start.weekday()]} {ev.start:%d.%m} весь день"
    if ev.start.date() == ev.end.date():
        return f"{fmt_dt(ev.start)}–{ev.end:%H:%M}"
    return f"{fmt_dt(ev.start)} – {fmt_dt(ev.end)}"


def fmt_iso_range(start: str | None, end: str | None) -> str:
    s, e = parse_iso(start), parse_iso(end)
    if not s:
        return "время не указано"
    if e and e.date() == s.date():
        return f"{fmt_dt(s)}–{e:%H:%M}"
    if e:
        return f"{fmt_dt(s)} – {fmt_dt(e)}"
    return fmt_dt(s)


def entry_line(kind: str, data: dict) -> str:
    """Одна строка про запись журнала, без HTML."""
    if kind == "sleep":
        hours = data.get("hours")
        s, e = parse_iso(data.get("sleep_start")), parse_iso(data.get("sleep_end"))
        if hours is None and s and e:
            hours = (e - s).total_seconds() / 3600
        text = f"сон {hours:.1f} ч" if hours is not None else "сон"
        if s and e:
            text += f" ({s:%H:%M}–{e:%H:%M})"
        if data.get("score"):
            text += f", качество {data['score']}/5"
        return text
    if kind == "meal":
        label = MEAL_RU.get(data.get("meal_type") or "", "еда")
        text = f"{label}: {data.get('description') or '—'}"
        if data.get("score"):
            text += f" ({data['score']}/5)"
        return text
    if kind == "workout":
        text = f"тренировка: {data.get('description') or 'без описания'}"
        if data.get("minutes"):
            text += f", {data['minutes']} мин"
        if data.get("intensity"):
            text += f", {INTENSITY_RU.get(data['intensity'], data['intensity'])}"
        return text
    if kind == "mood":
        text = f"настроение {data.get('score', '?')}/10"
        if data.get("description"):
            text += f" — {data['description']}"
        return text
    if kind in {"weight", "water", "steps"}:
        names = {"weight": "вес", "water": "вода", "steps": "шаги"}
        value = data.get("value")
        unit = data.get("unit") or {"weight": "кг", "water": "мл", "steps": "шагов"}[kind]
        value_text = f"{value:g}" if isinstance(value, (int, float)) else "?"
        return f"{names[kind]} {value_text} {unit}"
    if kind == "symptom":
        return f"самочувствие: {data.get('description') or '—'}"
    return f"заметка: {data.get('description') or '—'}"


def render_output(out: AssistantOutput, saved_entries: list[dict]) -> str:
    parts: list[str] = [esc(out.reply)]

    if saved_entries:
        parts.append("📝 <b>Записала:</b>\n" + "\n".join(
            f"• {esc(entry_line(e['kind'], e['data']))}" for e in saved_entries))

    if out.mits:
        parts.append("🎯 <b>Главное на день:</b>\n" + "\n".join(
            f"{i}. {esc(m)}" for i, m in enumerate(out.mits[:3], 1)))

    if out.calendar_actions:
        icons = {"create": "➕", "move": "🔁", "delete": "🗑"}
        lines = []
        for a in out.calendar_actions:
            src = " (cal.com)" if a.source == "calcom" else ""
            when = fmt_iso_range(a.start, a.end) if a.op != "delete" else ""
            line = f"• {icons[a.op]} {esc(a.title)}{src} {esc(when)}".rstrip()
            if a.why:
                line += f"\n   <i>{esc(a.why)}</i>"
            lines.append(line)
        parts.append("📅 <b>Календарь:</b>\n" + "\n".join(lines))

    if out.task_actions:
        lines = []
        for t in out.task_actions:
            icon = "☑️" if t.op == "complete" else "➕"
            due = f" — {esc(t.due)}" if t.due else ""
            pr = " ❗" if (t.priority or 0) >= 4 else ""
            lines.append(f"• {icon} {esc(t.content)}{due}{pr}")
        parts.append("✅ <b>Задачи:</b>\n" + "\n".join(lines))

    for g in out.goals:
        block = [f"🎯 <b>Цель:</b> {esc(g.title)}" + (f" (до {esc(g.deadline)})" if g.deadline else "")]
        block.append(f"• Измеримо: {esc(g.measurable)}")
        block.append(f"• Срок: {esc(g.time_bound)}")
        if g.milestones:
            block.append("• Вехи: " + "; ".join(esc(m) for m in g.milestones))
        if g.weekly_actions:
            block.append("• На неделю: " + "; ".join(esc(w) for w in g.weekly_actions))
        parts.append("\n".join(block))

    if out.goal_progress:
        parts.append("📈 <b>Прогресс по целям:</b>\n" + "\n".join(
            f"• #{p.goal_id}: {esc(p.note)}" for p in out.goal_progress))

    if out.weekly_focus:
        parts.append(f"🧭 <b>Фокус недели:</b> {esc(out.weekly_focus)}")

    if out.red_flags:
        parts.append("⚠️ <b>Ред-флаги:</b>\n" + "\n".join(f"• {esc(f)}" for f in out.red_flags))

    if out.questions:
        parts.append("\n".join(f"❓ {esc(q.text)}" for q in out.questions))

    return "\n\n".join(p for p in parts if p.strip())


def split_message(text: str, limit: int = 4000) -> list[str]:
    """Telegram ограничивает сообщение 4096 символами; режем по абзацам."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > limit and current:
            chunks.append(current)
            current = para
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks
