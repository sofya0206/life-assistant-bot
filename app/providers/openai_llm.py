"""Провайдер OpenAI (SDK openai, Responses API): structured output через
responses.parse с pydantic-моделью. Дешёвые модели класса gpt-5-mini / gpt-5-nano
для разбора сообщений хватает с головой.

Ключ — с platform.openai.com (pay-as-you-go). Подписка ChatGPT / Codex к API
не относится, а токены Codex использовать в своих ботах запрещено условиями OpenAI.
"""
from __future__ import annotations

import logging

import httpx
from openai import AsyncOpenAI

from ..config import settings
from ..models import AssistantOutput
from ..prompts import SYSTEM_PROMPT

log = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _client_or_raise() -> AsyncOpenAI:
    global _client
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY не задан")
    if _client is None:
        http_client = httpx.AsyncClient(proxy=settings.llm_proxy_url, timeout=120) if settings.llm_proxy_url else None
        _client = AsyncOpenAI(api_key=settings.openai_api_key, http_client=http_client)
    return _client


def _reasoning(effort: str) -> dict:
    """reasoning.effort есть у gpt-5* и o-серии; для остальных не передаём."""
    model = settings.openai_model
    if model.startswith(("gpt-5", "o1", "o3", "o4")):
        return {"reasoning": {"effort": effort}}
    return {}


def _log_usage(response) -> None:
    usage = getattr(response, "usage", None)
    if usage:
        log.info("OpenAI: in=%s out=%s", usage.input_tokens, usage.output_tokens)


async def interpret(user_text: str, context_text: str, history: list[dict]) -> AssistantOutput:
    client = _client_or_raise()
    messages = [*history, {
        "role": "user",
        "content": f"КОНТЕКСТ:\n{context_text}\n\nСООБЩЕНИЕ СОНИ:\n{user_text}",
    }]
    response = await client.responses.parse(
        model=settings.openai_model,
        instructions=SYSTEM_PROMPT,
        input=messages,
        text_format=AssistantOutput,
        max_output_tokens=8000,
        **_reasoning(settings.openai_reasoning),
    )
    _log_usage(response)
    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError("OpenAI вернул пустой ответ (возможно, сработал фильтр или отказ)")
    return parsed


async def prose(prompt: str, max_tokens: int = 1200) -> str:
    client = _client_or_raise()
    response = await client.responses.create(
        model=settings.openai_model,
        input=prompt,
        max_output_tokens=max_tokens,
        **_reasoning("low"),
    )
    _log_usage(response)
    return (response.output_text or "").strip()


def model_name() -> str:
    return settings.openai_model
