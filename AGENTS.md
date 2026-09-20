# AGENTS.md — инструкции для Codex / любого агента-кодера

Проект: личный Telegram-ассистент Сони (планирование, SMART-цели, журнал
здоровья, алерты). Читай `README.md` для картины целиком. Здесь — как
работать с кодом и что делать дальше.

## Стек и правила

- Python 3.14, aiogram 3 (polling), SQLite через `sqlite3`, APScheduler 3,
  httpx для cal.com/Todoist, google-api-python-client для Calendar, faster-whisper.
- LLM: три провайдера за одним интерфейсом `app/llm.py` (`interpret`, `prose`, `model_name`):
  `providers/openai_llm.py` (SDK `openai`, `responses.parse` с `text_format=AssistantOutput`),
  `providers/gemini_llm.py` (SDK `google-genai`, `generate_content` с `response_schema`),
  `providers/anthropic_llm.py` (SDK `anthropic`, `output_config.format` + adaptive thinking).
  Все три умеют ходить через `LLM_PROXY_URL` (httpx proxy, SOCKS поддержан). Новый
  провайдер = новый модуль с теми же функциями + ветка в `config.Settings.llm_provider`.
  Только официальные SDK, без OpenAI-совместимых шимов для чужих провайдеров.
- Язык интерфейса и промптов — русский, обращение на «ты». Комментарии в коде — русские.
- Ответ LLM — строго `app/models.py::AssistantOutput`. Меняешь модель → схема обновляется
  сама у обоих провайдеров. Не используй `dict`-поля, `min/max`, рекурсию — structured
  outputs это не переваривают.
- База знаний `knowledge/*.md` целиком склеивается в системный промпт
  (`prompts.build_system_prompt`). Методологию планирования меняй там, а не в коде.
  `BASE_PROMPT` в `prompts.py` — только правила формата ответа.
- Инварианты:
  1. Записи журнала (`entries`) применяются сразу. Всё, что трогает внешние сервисы
     (календарь, Todoist, цели), проходит через `pending` + кнопку «Применить».
  2. Уточняющий вопрос — максимум один, с вариантами; варианты становятся кнопками
     (`ans:<id>:<n>`), ответ уходит обратно в `handle_text` как обычное сообщение.
  3. `weekly_focus` пишется в `settings` только когда Соня явно выбрала приоритет.
- Правила ред-флагов — чистые функции в `app/alerts.py`, покрыты тестами.
  Новое правило = функция + тест + подключение в `collect_alerts` + строка в
  `knowledge/planning.md` §7, чтобы LLM знал, как реагировать.
- Все datetime — aware, в `settings.tz`. В SQLite — ISO-строки в этой таймзоне
  (`db.to_iso`), чтобы сравнивать строками.
- Внешние клиенты создаются в `app/integrations.py` только при наличии ключей;
  всё остальное обязано корректно работать, когда клиент `None`.
- Telegram: parse_mode HTML, всё пользовательское экранировать через `render.esc`,
  длинные сообщения резать `render.split_message`.

## Как запускать и проверять

```bash
cp .env.example .env                       # заполнить
./start.sh                                 # запуск бота
.venv/bin/python -m scripts.check_config   # проверка ключей
BOT_TOKEN=x .venv/bin/python -m pytest -q  # тесты (BOT_TOKEN нужен из-за импорта config)
```

Быстрый прогон без Telegram и без ключей: собери `AssistantOutput` руками и
прогони `handlers.log._save_entries` → `render.render_output` → `actions.apply`.

## Известные допущения / что проверить на живых ключах

0. `providers/openai_llm.py`: `reasoning.effort` передаётся только моделям `gpt-5*`/`o*`.
   Схема `AssistantOutput` проходит `to_strict_json_schema` (проверено), живой ответ не тестировался.
1. `providers/gemini_llm.py`: используется legacy-путь `generate_content`; Google
   рекомендует новый Interactions API (`client.interactions.create`) — переезжать
   стоит, когда он стабилизируется. `thinking_level` передаётся только моделям
   `gemini-3*`. Проверить, что `response.text` приходит валидным JSON на реальном ключе.
2. `services/calcom.py`: формат ответа `GET /v2/bookings` обработан для списка и
   `data.bookings`; заголовок `cal-api-version` (`CALCOM_API_VERSION`) сверить с
   документацией, если API ругается.
3. `services/todoist_client.py`: unified API v1. Если фильтр `7 days | overdue` не
   принимается — заменить на `due before: +7 days | overdue`.
4. `providers/anthropic_llm.py`: `thinking` / `effort` не передаются для моделей с
   `haiku` в названии.
5. Промпт и `knowledge/planning.md` — первая версия. Настраивать по реальным диалогам.

## Roadmap (в порядке приоритета)

1. **Живая проверка**: `/status`, `/events`, `/tasks`, одно голосовое с планом дня.
   2–3 дня реального использования, правка `planning.md` и `BASE_PROMPT`.
2. **Заполнить `knowledge/about_me.md`** (можно через бота: команда `/me` → бот задаёт
   вопросы из шаблона по одному и дописывает файл).
3. **Редактирование записи**: кнопка «✏️ Исправить» → следующее сообщение правит
   последнюю запись (`db.update_entry`).
4. **Недельный обзор по расписанию** — воскресенье 20:00 (`scheduler.py`, job `week`
   → `briefs.week_review`) плюс «спланируй неделю» сразу после него.
5. **График `/week` картинкой** (matplotlib → `send_photo`): сон по ночам, тренировки,
   настроение.
6. **Apple Health / Apple Watch**: Shortcut по расписанию 09:00 «найти образцы
   сна/шагов → отправить сообщение боту в Telegram» (без сервера). Запись приходит
   текстом «sleep 7h12m steps 8432» → парсер в `handlers/log.py` без LLM.
7. **Telegram Mini App** — дашборд с графиками поверх того же SQLite (маленький
   FastAPI/aiohttp сервер, `initData` валидация, кнопка «📊» в меню). После п.5.
8. **cal.com webhooks** вместо опроса (нужен публичный HTTPS URL).
9. **Экспорт в Obsidian**: ежедневная заметка `YYYY-MM-DD.md` с журналом и брифом.
10. **Деплой на VPS в ЕС**: Whisper заменить на API-транскрипцию или оставить голос
    на Mac; `systemd` unit вместо launchd.
11. Пороги правил (`gap_days`, `late_hour`, `deep_work_min`) в таблицу `settings`
    и команда `/set`.

## Чего не делать

- Не заменять structured outputs на «попроси JSON в промпте» — ломается надёжность.
- Не писать в календарь/Todoist без подтверждения кнопкой.
- Не хранить секреты в коде; только `.env` (в `.gitignore`).
- Не тянуть OpenClaw/Hermes/n8n и прочие фреймворки — проект намеренно маленький.
