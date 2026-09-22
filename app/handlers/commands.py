"""Слэш-команды."""
from __future__ import annotations

from datetime import timedelta

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from .. import briefs, db, integrations, llm
from ..config import settings
from ..render import entry_line, esc, fmt_range, split_message

router = Router(name="commands")

HELP = (
    "Я помощник для Google Calendar и Todoist.\n\n"
    "Просто пиши или записывай голосовые:\n"
    "• «завтра в 15 созвон с Никитой»\n"
    "• «добавь в Todoist подготовить презентацию до пятницы»\n"
    "• «что у меня на этой неделе?»\n"
    "• «когда у меня есть свободные два часа?»\n"
    "Изменения сначала покажу, затем создам после кнопки «Применить».\n\n"
    "Команды:\n"
    "/today — события и задачи на сегодня\n"
    "/events — календарь на 7 дней\n"
    "/tasks — задачи Todoist\n"
    "/status — что подключено\n"
    "/id — твой Telegram id"
)


async def _reply_long(message: Message, text: str) -> None:
    for chunk in split_message(text):
        await message.answer(chunk)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer("Привет! " + HELP)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(f"Твой id: <code>{message.from_user.id}</code>, chat id: <code>{message.chat.id}</code>")


@router.message(Command("today"))
async def cmd_today(message: Message) -> None:
    await _reply_long(message, await briefs.morning_brief())


@router.message(Command("evening"))
async def cmd_evening(message: Message) -> None:
    text, keyboard = await briefs.evening_checkin()
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("week"))
async def cmd_week(message: Message) -> None:
    await _reply_long(message, await briefs.week_review())


@router.message(Command("events"))
async def cmd_events(message: Message) -> None:
    start, end = integrations.default_window(7)
    events = await integrations.gather_events(start, end)
    if not events:
        await message.answer("На 7 дней событий нет (или календари не подключены — см. /status).")
        return
    lines = [f"• {esc(fmt_range(e))} {esc(e.title)}" + (" (cal.com)" if e.source == "calcom" else "") for e in events]
    await _reply_long(message, "📅 <b>Ближайшие 7 дней</b>\n" + "\n".join(lines))


@router.message(Command("tasks"))
async def cmd_tasks(message: Message) -> None:
    tasks = await integrations.gather_tasks("7 days | overdue")
    if not tasks:
        await message.answer("Задач нет (или Todoist не подключён — см. /status).")
        return
    lines = []
    for t in tasks[:30]:
        due = (t.get("due") or {}).get("string") or (t.get("due") or {}).get("date") or "без срока"
        lines.append(f"• {esc(t.get('content', ''))} — {esc(due)}")
    await _reply_long(message, "✅ <b>Задачи</b>\n" + "\n".join(lines))


@router.message(Command("goals"))
async def cmd_goals(message: Message) -> None:
    goals = db.list_goals()
    if not goals:
        await message.answer("Целей пока нет. Расскажи, чего хочешь достичь — оформлю по SMART.")
        return
    blocks = []
    for g in goals:
        smart = g.get("smart") or {}
        lines = [f"🎯 <b>#{g['id']} {esc(g['title'])}</b>" + (f" — до {esc(g['deadline'])}" if g.get("deadline") else "")]
        if smart.get("measurable"):
            lines.append(f"• Измеримо: {esc(smart['measurable'])}")
        if smart.get("weekly_actions"):
            lines.append("• На неделю: " + "; ".join(esc(w) for w in smart["weekly_actions"]))
        blocks.append("\n".join(lines))
    await _reply_long(message, "\n\n".join(blocks))


@router.message(Command("log"))
async def cmd_log(message: Message) -> None:
    entries = db.entries_since(db.now_local() - timedelta(days=3))
    if not entries:
        await message.answer("Журнал за 3 дня пуст.")
        return
    lines = []
    for e in entries:
        ts = db.parse_iso(e["ts"])
        stamp = f"{ts:%d.%m %H:%M}" if ts else "?"
        lines.append(f"• <code>#{e['id']}</code> {stamp} — {esc(entry_line(e['kind'], e['data']))}")
    await _reply_long(message, "📓 <b>Журнал</b>\n" + "\n".join(lines))


@router.message(Command("undo"))
async def cmd_undo(message: Message) -> None:
    last = db.last_entry()
    if not last:
        await message.answer("Удалять нечего.")
        return
    db.delete_entry(last["id"])
    await message.answer(f"Удалила: {esc(entry_line(last['kind'], last['data']))}")


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    lines = await integrations.healthcheck()
    if settings.llm_enabled:
        try:
            lines.append(await llm.ping())
        except Exception as exc:  # noqa: BLE001
            lines.append(f"LLM: ошибка — {exc}")
    if settings.morning_brief_enabled:
        h, m = settings.morning_time
        lines.append(f"Утренний обзор: {h:02d}:{m:02d}")
    else:
        lines.append("Утренний обзор: выключен")
    lines.append(f"Чек-ины здоровья: {'включены' if settings.health_checkins_enabled else 'выключены'}")
    lines.append(f"Таймзона: {settings.tz_name}, chat_id {settings.chat_id}")
    await message.answer("\n".join(esc(line) for line in lines))
