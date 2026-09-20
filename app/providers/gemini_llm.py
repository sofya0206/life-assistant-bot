"""Провайдер Gemini (google-genai SDK): structured output через
response_schema (pydantic-модель) + thinking_level для моделей Gemini 3.

Бесплатный тариф Gemini API есть у flash-моделей, но по условиям Google на
бесплатном тарифе запросы используются для обучения и могут читаться людьми.
Для личных данных о здоровье лучше платный тариф (предоплата от $5, копейки в месяц).
"""
from __future__ import annotations

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


def _thinking(level: str) -> types.ThinkingConfig | None:
    """thinking_level есть только у Gemini 3.x; 2.5 управляется thinking_budget,
    для дешёвого разбора там просто ничего не задаём."""
    if settings.gemini_model.startswith("gemini-3"):
        return types.ThinkingConfig(thinking_level=level)
    return None


def _to_contents(history: list[dict], last_user_text: str) -> list[types.Content]:
    contents: list[types.Content] = []
    for m in history:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=last_user_text)]))
    return contents


def _log_usage(response) -> None:
    usage = getattr(response, "usage_metadata", None)
    if usage:
        log.info("Gemini: in=%s out=%s thoughts=%s", usage.prompt_token_count,
                 usage.candidates_token_count, getattr(usage, "thoughts_token_count", None))


async def interpret(user_text: str, context_text: str, history: list[dict]) -> AssistantOutput:
    client = _client_or_raise()
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_schema=AssistantOutput,
        thinking_config=_thinking(settings.gemini_thinking),
        max_output_tokens=8000,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents = _to_contents(history, f"КОНТЕКСТ:\n{context_text}\n\nСООБЩЕНИЕ СОНИ:\n{user_text}")
    response = await client.aio.models.generate_content(model=settings.gemini_model, contents=contents, config=config)
    _log_usage(response)
    text = response.text
    if not text:
        raise RuntimeError("Gemini вернул пустой ответ (возможно, сработал фильтр)")
    return AssistantOutput.model_validate_json(text)


async def prose(prompt: str, max_tokens: int = 1200) -> str:
    client = _client_or_raise()
    config = types.GenerateContentConfig(
        thinking_config=_thinking("low"),
        max_output_tokens=max_tokens,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    response = await client.aio.models.generate_content(model=settings.gemini_model, contents=prompt, config=config)
    _log_usage(response)
    return (response.text or "").strip()


def model_name() -> str:
    return settings.gemini_model
