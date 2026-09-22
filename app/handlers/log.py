"""Главный поток: текст/голос → (транскрипция) → LLM → записи в журнал
сразу, внешние действия — после кнопки «Применить», уточняющие вопросы —
кнопками с вариантами."""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .. import actions, db, llm
from ..config import settings
from ..context import snapshot, to_llm_text
from ..models import AssistantOutput
from ..render import esc, render_output, split_message
from ..transcribe import transcribe

log = logging.getLogger(__name__)
router = Router(name="log")


def build_keyboard(out: AssistantOutput, chat_id: int) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    if out.questions and out.questions[0].options:
        q = out.questions[0]
        qid = db.save_pending(chat_id, {"question": q.model_dump()})
        rows.append([InlineKeyboardButton(text=opt[:60], callback_data=f"ans:{qid}:{i}")
                     for i, opt in enumerate(q.options[:3])])
    if out.has_external_actions:
        pid = db.save_pending(chat_id, {"actions": out.model_dump()})
        rows.append([
            InlineKeyboardButton(text="✅ Применить", callback_data=f"apply:{pid}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel:{pid}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _save_entries(out: AssistantOutput, raw: str) -> list[dict]:
    saved: list[dict] = []
    for e in out.entries:
        data = e.model_dump(exclude={"kind", "time"}, exclude_none=True)
        ts = e.sleep_end if e.kind == "sleep" and e.sleep_end else e.time
        entry_id = db.add_entry(e.kind, data, ts=ts, raw=raw)
        saved.append({"id": entry_id, "kind": e.kind, "data": data})
    return saved


async def _send(message: Message, text: str, status: Message | None = None,
                reply_markup: InlineKeyboardMarkup | None = None) -> None:
    chunks = split_message(text)
    first, rest = chunks[0], chunks[1:]
    if status is not None:
        await status.edit_text(first, reply_markup=reply_markup if not rest else None)
    else:
        await message.answer(first, reply_markup=reply_markup if not rest else None)
    for i, chunk in enumerate(rest):
        await message.answer(chunk, reply_markup=reply_markup if i == len(rest) - 1 else None)


async def handle_text(message: Message, text: str) -> None:
    chat_id = message.chat.id
    if not settings.llm_enabled:
        db.add_entry("note", {"description": text}, raw=text)
        await message.answer("📝 Записала как заметку. LLM не подключён (нет OPENAI_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY), "
                             "поэтому планировать и разбирать записи пока не могу.")
        return

    status = await message.answer("⏳ Думаю…")
    try:
        snap = await asyncio.wait_for(snapshot(), timeout=15)
        await status.edit_text("🤖 Собираю план…")
        history = [{"role": m["role"], "content": m["content"]} for m in db.recent_messages(chat_id, 6)]
        out = await asyncio.wait_for(
            llm.interpret(text, to_llm_text(snap), history),
            timeout=55,
        )
    except TimeoutError:
        log.warning("Обработка сообщения превысила лимит времени")
        await status.edit_text("⏱ Gemini отвечает слишком долго. Попробуй отправить сообщение ещё раз.")
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("interpret failed")
        await status.edit_text(f"❌ Не получилось обработать: {esc(str(exc))[:300]}")
        return

    saved = _save_entries(out, text)
    if out.weekly_focus:
        db.set_setting("weekly_focus", out.weekly_focus)
    db.add_message(chat_id, "user", text)
    assistant_memory = out.reply
    if out.questions:
        assistant_memory += "\nВопрос: " + " / ".join(q.text for q in out.questions)
    db.add_message(chat_id, "assistant", assistant_memory)

    await _send(message, render_output(out, saved), status=status, reply_markup=build_keyboard(out, chat_id))


@router.message(F.voice | F.audio | F.video_note)
async def on_voice(message: Message, bot: Bot) -> None:
    media = message.voice or message.audio or message.video_note
    suffix = ".oga" if message.voice else ".m4a"
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        note = await message.answer("🎙 Расшифровываю…")
        await bot.download(media, destination=path)
        text = await transcribe(path)
    except Exception as exc:  # noqa: BLE001
        log.exception("transcribe failed")
        await message.answer(f"❌ Не смогла расшифровать: {esc(str(exc))[:200]}")
        return
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if not text:
        await note.edit_text("🎙 Тишина или не разобрала. Попробуй ещё раз.")
        return
    await note.edit_text(f"🎙 <i>{esc(text)}</i>")
    await handle_text(message, text)


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message) -> None:
    await handle_text(message, message.text or "")


@router.callback_query(F.data.startswith("apply:"))
async def on_apply(cb: CallbackQuery) -> None:
    pending_id = cb.data.split(":", 1)[1]
    payload = db.pop_pending(pending_id)
    await cb.answer()
    if payload is None or "actions" not in payload:
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.message.answer("Это предложение уже применено или устарело.")
        return
    out = AssistantOutput.model_validate(payload["actions"])
    results = await actions.apply(out)
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer("\n".join(results) if results else "Нечего применять.")


@router.callback_query(F.data.startswith("cancel:"))
async def on_cancel(cb: CallbackQuery) -> None:
    pending_id = cb.data.split(":", 1)[1]
    db.pop_pending(pending_id)
    await cb.answer("Отменено")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer("Ок, ничего не меняю. Скажи, что поправить.")


@router.callback_query(F.data.startswith("ans:"))
async def on_answer(cb: CallbackQuery) -> None:
    _, qid, idx = cb.data.split(":", 2)
    payload = db.pop_pending(qid)
    await cb.answer()
    if payload is None or "question" not in payload:
        await cb.message.answer("Этот вопрос уже закрыт — напиши ответ текстом.")
        return
    options = payload["question"].get("options") or []
    try:
        answer = options[int(idx)]
    except (ValueError, IndexError):
        await cb.message.answer("Не поняла вариант — напиши ответ текстом.")
        return
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(f"👉 {esc(answer)}")
    await handle_text(cb.message, answer)


@router.callback_query(F.data.startswith("mood:"))
async def on_mood(cb: CallbackQuery) -> None:
    value = cb.data.split(":", 1)[1]
    await cb.answer()
    if value == "voice":
        await cb.message.answer("Слушаю — запиши голосовое, разберу и запишу.")
        return
    db.add_entry("mood", {"score": int(value)}, raw="evening check-in")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(f"Записала настроение {value}/10. Спокойной ночи 🌙")
