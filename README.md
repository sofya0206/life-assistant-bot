# Life Assistant Bot

Личный ассистент в Telegram: говоришь голосом, что хочешь сделать, а он
раскладывает это по Google Calendar и Todoist, оформляет цели по SMART,
ведёт журнал сна / еды / тренировок / настроения и присылает алерты
(«спишь меньше нормы», «3 дня без тренировки», «не забудь завтрак»).

Мозг — Gemini или Claude (переключается в `.env`), голос — локальный
faster-whisper, данные — один SQLite-файл на твоём диске. Как планировать,
бот знает сам: методология лежит в `knowledge/planning.md` и целиком
попадает в его системный промпт.

## Как это работает

```
голосовое/текст ──► faster-whisper ──► LLM (JSON по схеме AssistantOutput)
                                            │
        ┌───────────────────────────────────┼──────────────────────────┐
        ▼                                   ▼                          ▼
  entries (сон, еда,             calendar/task/goal actions        red_flags,
  тренировки, настроение)        → кнопка «Применить» →            questions
  → в SQLite сразу               Google Calendar / cal.com / Todoist   (кнопки-варианты)
```

Плюс планировщик: утренний бриф (сон + календарь + задачи + цели + ред-флаги),
проверка завтрака в 11:00, вечерний чек-ин с кнопками настроения.
Ред-флаги считаются правилами (`app/alerts.py`) даже без LLM, а LLM
добавляет свои поверх.

## Быстрый старт

```bash
cp .env.example .env      # заполнить BOT_TOKEN, ALLOWED_IDS и один ключ LLM
./start.sh                # создаст .venv, поставит зависимости, запустит
```

Проверить ключи без запуска бота:

```bash
.venv/bin/python -m scripts.check_config
```

Тесты:

```bash
BOT_TOKEN=x .venv/bin/python -m pytest -q
```

## Мозг: OpenAI, Gemini или Claude

| | OpenAI | Gemini | Claude |
|---|---|---|---|
| Ключ | platform.openai.com → API keys, предоплата от $5 | aistudio.google.com, без карты | console.anthropic.com, предоплата от $5 |
| Подписка (ChatGPT/Codex, Google AI Pro, Claude Max) | к API не относится | к API не относится | к API не относится |
| Модель по умолчанию | `gpt-5-mini` | `gemini-3.8-flash` | `claude-sonnet-5` |
| Бесплатный тариф | нет | есть, но запросы идут на обучение и их могут читать люди | нет |
| Цена | доли цента за сообщение | доли цента за сообщение | несколько долларов в месяц |

Для этой задачи (разобрать сообщение, разложить по времени) тяжёлая модель не нужна.
`LLM_PROVIDER=auto` берёт первого, у кого есть ключ: OpenAI → Gemini → Claude.

**Из России** все три API без прокси недоступны: укажи `LLM_PROXY_URL` (или он
возьмётся из `PROXY_URL`, который уже нужен для Telegram). Токены Codex / ChatGPT
использовать в своём боте нельзя по условиям OpenAI, нужен обычный API-ключ.

## База знаний (`knowledge/`)

- `planning.md` — методология: как классифицировать входящее, иерархия приоритетов
  (люди → здоровье → дедлайны 48 ч → главная цель недели → остальное), матрица
  Эйзенхауэра, 3 главных дела в день, time-blocking по энергии, буферы, защита сна,
  недельное планирование, SMART-цели, когда задавать вопрос (только один и с вариантами).
- `about_me.md` — твой профиль: подъём/отбой, хронотип, окна для глубокой работы и
  встреч, тренировки, еда, текущие цели, люди, личные правила. **Заполни его**,
  это сильно уменьшает число вопросов от бота.

Любой `*.md` в этой папке подхватывается при запуске.

## Ключи интеграций (все опциональны)

| Что | Где взять | Без него |
|---|---|---|
| `BOT_TOKEN` | @BotFather (можно взять токен tg-transcribe-bot, но старый бот остановить) | не запустится |
| `ALLOWED_IDS` | `/id` в боте или @userinfobot | бот отвечает всем |
| `OPENAI_API_KEY` / `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` | см. выше | «тупой режим»: сообщения сохраняются заметками, брифы только по правилам |
| `GOOGLE_SA_FILE` + `GOOGLE_CALENDAR_ID` | см. ниже | календарь не читается/не пишется |
| `CALCOM_API_KEY` | app.cal.com → Settings → Developer → API keys | брони cal.com не видны |
| `TODOIST_TOKEN` | Todoist → Settings → Integrations → Developer | задачи не читаются/не создаются |

### Google Calendar за 5 минут (сервисный аккаунт)

1. console.cloud.google.com → создать проект → «APIs & Services» → включить **Google Calendar API**.
2. IAM & Admin → Service Accounts → Create → после создания: Keys → Add key → JSON. Файл положить в `data/google-sa.json`.
3. Открыть Google Календарь в браузере → настройки своего календаря → «Доступ для отдельных пользователей» → добавить email сервисного аккаунта (вида `name@project.iam.gserviceaccount.com`) с правом **«Внесение изменений в мероприятия»**.
4. В `.env`: `GOOGLE_CALENDAR_ID=твой@gmail.com` (не `primary`).

Почему так, а не OAuth: не нужен consent screen, и токен не протухает каждые 7 дней (у OAuth-приложений в статусе Testing это так). Ограничение: сервисный аккаунт не может звать участников в событие, для личного планирования это не нужно.

## Что умеет

Пишешь или говоришь как угодно:

- «легла в час, встала в восемь, спала нормально» → запись сна
- «завтракала овсянкой, потом бегала 30 минут» → еда + тренировка
- «завтра в 15 созвон с Никитой, зал перенеси на вечер» → предложение изменений в календаре → кнопка «Применить»
- «спланируй завтра» / «спланируй неделю» → 3 главных дела + блоки в календаре с учётом задач, целей, тренировок и сна
- «хочу к декабрю английский до B2» → SMART-цель с вехами и действиями на неделю (+ задачи в Todoist)
- «сделала два урока английского» → прогресс по цели
- если два дела не помещаются, бот спросит «что важнее?» кнопками с вариантами и запомнит ответ как фокус недели

Команды: `/today` бриф, `/evening` чек-ин, `/week` обзор недели, `/events`, `/tasks`, `/goals`, `/log`, `/undo`, `/status`, `/id`.

## Запуск 24/7 на Mac

Бот должен работать постоянно, чтобы слать брифы. Вариант без сервера — launchd:

```bash
sed "s|__PROJECT_DIR__|$(pwd)|g" deploy/com.sofia.life-assistant.plist > ~/Library/LaunchAgents/com.sofia.life-assistant.plist
launchctl load ~/Library/LaunchAgents/com.sofia.life-assistant.plist
```

Логи: `data/bot.log`. Остановить: `launchctl unload ~/Library/LaunchAgents/com.sofia.life-assistant.plist`.
Ноутбук в режиме сна бота убивает — держи его на зарядке с `caffeinate -s` или в Настройках → Батарея → «Не выключать при закрытой крышке».
Когда надоест — VPS в ЕС за 3–4 €/мес, Whisper там заменить на API-транскрипцию или оставить на Mac.

## Структура

```
app/
  main.py          точка входа (aiogram polling + планировщик)
  config.py        .env → settings (в т.ч. выбор LLM-провайдера)
  db.py            SQLite: entries, goals, goal_progress, pending, messages, settings
  models.py        pydantic-схема ответа LLM (AssistantOutput)
  prompts.py       правила формата + склейка knowledge/*.md в системный промпт
  llm.py           единый вход: interpret / prose / ping
  providers/       openai_llm.py, gemini_llm.py, anthropic_llm.py (официальные SDK, прокси через LLM_PROXY_URL)
  context.py       снимок мира для LLM/брифов (фокус недели, календарь, задачи, цели, журнал, нормы)
  alerts.py        правила ред-флагов (чистые функции, покрыты тестами)
  briefs.py        утренний бриф, проверка завтрака, вечерний чек-ин, обзор недели
  actions.py       применение подтверждённых действий во внешние сервисы
  render.py        форматирование для Telegram (HTML) и для LLM
  scheduler.py     APScheduler: 08:00 / 11:00 / 21:30
  transcribe.py    faster-whisper
  integrations.py  фабрика клиентов + gather_events/gather_tasks
  handlers/        commands.py (слэш-команды), log.py (текст/голос/кнопки)
  services/        gcal.py, calcom.py, todoist_client.py
knowledge/         planning.md (методология), about_me.md (профиль)
scripts/check_config.py   проверка ключей
tests/                    правила, промпт, рендер
deploy/                   launchd plist
```

Дальнейший план и правила для агентов-кодеров — в `AGENTS.md`.
