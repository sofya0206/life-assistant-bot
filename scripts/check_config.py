"""Проверка ключей без запуска бота: python -m scripts.check_config"""
from __future__ import annotations

import asyncio

from app import integrations, llm
from app.config import settings


async def main() -> None:
    integrations.init()
    for line in await integrations.healthcheck():
        print("•", line)
    if settings.llm_enabled:
        try:
            print("•", await llm.ping())
        except Exception as exc:  # noqa: BLE001
            print("• Claude: ошибка —", exc)
    print(f"• Telegram: allowed_ids={sorted(settings.allowed_ids) or 'ПУСТО'} chat_id={settings.chat_id}")


if __name__ == "__main__":
    asyncio.run(main())
