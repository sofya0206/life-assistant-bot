"""Точка входа: python -m app.main"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from . import db, integrations, scheduler
from .config import settings
from .handlers import commands, log as log_handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("googleapiclient").setLevel(logging.WARNING)
log = logging.getLogger("main")


def build_bot() -> Bot:
    session = AiohttpSession(proxy=settings.proxy_url) if settings.proxy_url else None
    return Bot(settings.bot_token, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    if settings.allowed_ids:
        dp.message.filter(F.from_user.id.in_(settings.allowed_ids))
        dp.callback_query.filter(F.from_user.id.in_(settings.allowed_ids))
    else:
        log.warning("ALLOWED_IDS пуст — бот ответит любому. Заполни .env!")
    dp.include_routers(commands.router, log_handlers.router)
    return dp


async def main() -> None:
    db.connect()
    integrations.init()
    bot = build_bot()
    dp = build_dispatcher()
    scheduler.start(bot)
    me = await bot.get_me()
    log.info("Запущен @%s, LLM %s (%s)", me.username, settings.llm_provider or "выключен", settings.llm_model)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
