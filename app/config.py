"""Настройки из .env.

Обязателен только BOT_TOKEN. Всё остальное опционально: без ключа LLM бот
работает в «тупом» режиме (записи как заметки + брифы по правилам), без
календарей/Todoist соответствующие блоки просто пропускаются.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _ids(raw: str) -> frozenset[int]:
    parts = raw.replace(";", ",").split(",")
    return frozenset(int(p.strip()) for p in parts if p.strip().lstrip("-").isdigit())


def _bool(raw: str | None, default: bool) -> bool:
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "да"}


def _opt(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _str(name: str, default: str) -> str:
    return os.getenv(name, "").strip() or default


def _hhmm(raw: str, default: str) -> tuple[int, int]:
    value = (raw or default).strip()
    try:
        hh, mm = value.split(":")
        return int(hh), int(mm)
    except ValueError:
        hh, mm = default.split(":")
        return int(hh), int(mm)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    allowed_ids: frozenset[int]
    chat_id: int | None
    proxy_url: str | None

    tz_name: str
    tz: ZoneInfo
    morning_time: tuple[int, int]
    breakfast_check_time: tuple[int, int]
    evening_time: tuple[int, int]
    morning_brief_enabled: bool
    health_checkins_enabled: bool
    wake_target: tuple[int, int]
    sleep_target_hours: float

    llm_provider_env: str          # auto | openai | gemini | anthropic
    llm_proxy_url: str | None      # прокси для вызовов LLM (из России без него API недоступны)
    openai_api_key: str | None
    openai_model: str
    openai_reasoning: str          # minimal | low | medium | high (gpt-5*)
    gemini_api_key: str | None
    gemini_model: str
    gemini_thinking: str           # low | medium | high (Gemini 3.x)
    anthropic_api_key: str | None
    claude_model: str
    llm_prose_in_brief: bool

    whisper_model: str
    whisper_language: str

    google_sa_file: str | None
    google_calendar_id: str | None
    google_apps_script_url: str | None
    google_apps_script_secret: str | None
    google_calendar_ids: tuple[str, ...]
    calcom_api_key: str | None
    calcom_api_version: str
    todoist_token: str | None

    db_path: str
    knowledge_dir: Path

    @property
    def llm_provider(self) -> str | None:
        env = self.llm_provider_env
        if env in {"anthropic", "claude"}:
            return "anthropic" if self.anthropic_api_key else None
        if env == "gemini":
            return "gemini" if self.gemini_api_key else None
        if env == "openai":
            return "openai" if self.openai_api_key else None
        if self.openai_api_key:
            return "openai"
        if self.gemini_api_key:
            return "gemini"
        if self.anthropic_api_key:
            return "anthropic"
        return None

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider is not None

    @property
    def llm_model(self) -> str:
        return {"openai": self.openai_model, "gemini": self.gemini_model}.get(self.llm_provider, self.claude_model)

    @property
    def google_enabled(self) -> bool:
        apps_script = bool(self.google_apps_script_url and self.google_apps_script_secret)
        service_account = bool(
            self.google_sa_file and self.google_calendar_id and Path(self.google_sa_file).exists()
        )
        return apps_script or service_account

    @property
    def calcom_enabled(self) -> bool:
        return bool(self.calcom_api_key)

    @property
    def todoist_enabled(self) -> bool:
        return bool(self.todoist_token)


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN не задан: скопируй .env.example в .env и заполни его")

    allowed = _ids(os.getenv("ALLOWED_IDS", ""))
    chat_raw = os.getenv("CHAT_ID", "").strip()
    if chat_raw.lstrip("-").isdigit():
        chat_id: int | None = int(chat_raw)
    else:
        chat_id = min(allowed) if allowed else None

    tz_name = _str("TZ_NAME", "Europe/Moscow")
    db_path = _str("DB_PATH", "./data/assistant.sqlite3")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    return Settings(
        bot_token=token,
        allowed_ids=allowed,
        chat_id=chat_id,
        proxy_url=_opt("PROXY_URL"),
        tz_name=tz_name,
        tz=ZoneInfo(tz_name),
        morning_time=_hhmm(os.getenv("MORNING_TIME", ""), "08:00"),
        breakfast_check_time=_hhmm(os.getenv("BREAKFAST_CHECK_TIME", ""), "11:00"),
        evening_time=_hhmm(os.getenv("EVENING_TIME", ""), "21:30"),
        morning_brief_enabled=_bool(os.getenv("MORNING_BRIEF_ENABLED"), True),
        health_checkins_enabled=_bool(os.getenv("HEALTH_CHECKINS_ENABLED"), False),
        wake_target=_hhmm(os.getenv("WAKE_TARGET", ""), "07:30"),
        sleep_target_hours=float(os.getenv("SLEEP_TARGET_HOURS", "7.5") or 7.5),
        llm_provider_env=_str("LLM_PROVIDER", "auto").lower(),
        llm_proxy_url=_opt("LLM_PROXY_URL") or _opt("PROXY_URL"),
        openai_api_key=_opt("OPENAI_API_KEY"),
        openai_model=_str("OPENAI_MODEL", "gpt-5-mini"),
        openai_reasoning=_str("OPENAI_REASONING", "low").lower(),
        gemini_api_key=_opt("GEMINI_API_KEY"),
        gemini_model=_str("GEMINI_MODEL", "gemini-3.8-flash"),
        gemini_thinking=_str("GEMINI_THINKING", "low").lower(),
        anthropic_api_key=_opt("ANTHROPIC_API_KEY"),
        claude_model=_str("CLAUDE_MODEL", "claude-sonnet-5"),
        llm_prose_in_brief=_bool(os.getenv("LLM_PROSE_IN_BRIEF"), True),
        whisper_model=_str("WHISPER_MODEL", "small"),
        whisper_language=_str("WHISPER_LANGUAGE", "ru"),
        google_sa_file=_opt("GOOGLE_SA_FILE"),
        google_calendar_id=_opt("GOOGLE_CALENDAR_ID"),
        google_apps_script_url=_opt("GOOGLE_APPS_SCRIPT_URL"),
        google_apps_script_secret=_opt("GOOGLE_APPS_SCRIPT_SECRET"),
        google_calendar_ids=tuple(
            item.strip()
            for item in os.getenv("GOOGLE_CALENDAR_IDS", "").split(",")
            if item.strip()
        ),
        calcom_api_key=_opt("CALCOM_API_KEY"),
        calcom_api_version=_str("CALCOM_API_VERSION", "2024-08-13"),
        todoist_token=_opt("TODOIST_TOKEN"),
        db_path=db_path,
        knowledge_dir=Path(_str("KNOWLEDGE_DIR", str(PROJECT_DIR / "knowledge"))),
    )


settings = load_settings()
