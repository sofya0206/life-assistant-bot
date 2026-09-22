"""Провайдер Google GenAI: structured output через Interactions API.

Бесплатный тариф Gemini API есть у flash-моделей, но по условиям Google на
бесплатном тарифе запросы используются для обучения и могут читаться людьми.
Для личных данных о здоровье лучше платный тариф (предоплата от $5, копейки в месяц).
"""
from __future__ import annotations

import asyncio
import logging

from google import genai
from google.genai import types

from ..config import settings
from ..models import AssistantOutput
from ..prompts import SYSTEM_PROMPT

log = logging.getLogger(__name__)

_client: genai.Client | None = None


def _client_or_raise() -> genai.Client:
    global _client
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY не задан")
    if _client is None:
        http_options = None
        if settings.llm_proxy_url:
            proxy = {"proxy": settings.llm_proxy_url}
            http_options = types.HttpOptions(client_args=proxy, async_client_args=proxy)
        _client = genai.Client(api_key=settings.gemini_api_key, http_options=http_options)
    return _client


def _models() -> tuple[str, ...]:
    """Основная и запасные модели без повторов, в порядке приоритета."""
    return tuple(dict.fromkeys((settings.gemini_model, *settings.gemini_fallback_models)))


def _retryable(exc: Exception) -> bool:
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    return code in {429, 500, 502, 503, 504}


def _timed_out(exc: Exception) -> bool:
    return isinstance(exc, TimeoutError) or "Timeout" in type(exc).__name__


async def _interaction(
    input_text: str,
    *,
    system_instruction: str | None = None,
    schema: type[AssistantOutput] | None = None,
    max_tokens: int,
) -> str:
    """Interactions API с быстрым переключением на резервную модель."""
    client = _client_or_raise()
    last_error: Exception | None = None
    models = _models()
    for index, model in enumerate(models):
        # Не заставляем Telegram ждать одну перегруженную модель минутами.
        attempt_timeout = 15 if index == 0 else 18
        try:
            response_format = (
                {
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": schema.model_json_schema(),
                }
                if schema
                else {"type": "text"}
            )
            response = await asyncio.wait_for(
                client.aio.interactions.create(
                    model=model,
                    input=input_text,
                    system_instruction=system_instruction,
                    response_format=response_format,
                    generation_config={"max_output_tokens": max_tokens},
                    store=False,
                    timeout=float(attempt_timeout),
                ),
                timeout=attempt_timeout + 1,
            )
            if index:
                log.warning("Gemini fallback: ответила модель %s", model)
            text = response.output_text
            if not text:
                raise RuntimeError("Gemini вернул пустой ответ")
            return text
        except Exception as exc:  # noqa: BLE001
            if not (_timed_out(exc) or _retryable(exc)):
                raise
            last_error = exc
            code = getattr(exc, "status_code", None) or getattr(exc, "code", None) or "timeout"
            log.warning("Google AI %s временно недоступна (%s), пробую следующую", model, code)
            if index + 1 < len(models):
                await asyncio.sleep(0.2)
    assert last_error is not None
    raise RuntimeError("Google AI сейчас перегружен. Бот уже попробовал основную и запасные модели.") from last_error


def _input_with_history(history: list[dict], last_user_text: str) -> str:
    lines: list[str] = []
    for m in history:
        role = "АССИСТЕНТ" if m["role"] == "assistant" else "СОНЯ"
        lines.append(f"{role}: {m['content']}")
    if lines:
        lines.append("")
    lines.append(last_user_text)
    return "\n".join(lines)


async def interpret(user_text: str, context_text: str, history: list[dict]) -> AssistantOutput:
    prompt = _input_with_history(
        history,
        f"КОНТЕКСТ:\n{context_text}\n\nСООБЩЕНИЕ СОНИ:\n{user_text}",
    )
    text = await _interaction(
        prompt,
        system_instruction=SYSTEM_PROMPT,
        schema=AssistantOutput,
        max_tokens=1600,
    )
    return AssistantOutput.model_validate_json(text)


async def prose(prompt: str, max_tokens: int = 1200) -> str:
    return (await _interaction(prompt, max_tokens=max_tokens)).strip()


def model_name() -> str:
    return settings.gemini_model
