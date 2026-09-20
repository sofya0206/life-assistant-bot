"""Провайдер Claude (Anthropic SDK): structured output через output_config.format
+ adaptive thinking. Синхронный клиент через asyncio.to_thread."""
from __future__ import annotations

import asyncio
import logging

from anthropic import Anthropic, transform_schema
from pydantic import TypeAdapter

from ..config import settings
from ..models import AssistantOutput
from ..prompts import SYSTEM_PROMPT

log = logging.getLogger(__name__)

_client: Anthropic | None = None
_OUTPUT_SCHEMA = transform_schema(TypeAdapter(AssistantOutput).json_schema())


def _client_or_raise() -> Anthropic:
    global _client
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY не задан")
    if _client is None:
        _client = Anthropic(api_key=settings.anthropic_api_key)
    return _client


def _reasoning(effort: str) -> dict:
    """Adaptive thinking + effort есть у Opus/Sonnet 4.6+ и всей линейки 5.
    Haiku 4.5 их не принимает — для него параметры не передаём."""
    if "haiku" in settings.claude_model:
        return {}
    return {"thinking": {"type": "adaptive"}, "output_config": {"effort": effort}}


def _text_of(response) -> str:
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude отказался отвечать (refusal)")
    for block in response.content:
        if block.type == "text":
            return block.text
    raise RuntimeError("В ответе Claude нет текстового блока")


def _interpret_sync(user_text: str, context_text: str, history: list[dict]) -> AssistantOutput:
    client = _client_or_raise()
    params = _reasoning("medium")
    output_config = dict(params.pop("output_config", {}))
    output_config["format"] = {"type": "json_schema", "schema": _OUTPUT_SCHEMA}
    messages = [*history, {
        "role": "user",
        "content": f"КОНТЕКСТ:\n{context_text}\n\nСООБЩЕНИЕ СОНИ:\n{user_text}",
    }]
    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=8000,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=messages,
        output_config=output_config,
        **params,
    )
    usage = getattr(response, "usage", None)
    if usage:
        log.info("Claude: in=%s out=%s cache_read=%s", usage.input_tokens, usage.output_tokens,
                 getattr(usage, "cache_read_input_tokens", 0))
    return AssistantOutput.model_validate_json(_text_of(response))


def _prose_sync(prompt: str, max_tokens: int) -> str:
    client = _client_or_raise()
    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        **_reasoning("low"),
    )
    return _text_of(response).strip()


async def interpret(user_text: str, context_text: str, history: list[dict]) -> AssistantOutput:
    return await asyncio.to_thread(_interpret_sync, user_text, context_text, history)


async def prose(prompt: str, max_tokens: int = 1200) -> str:
    return await asyncio.to_thread(_prose_sync, prompt, max_tokens)


def model_name() -> str:
    return settings.claude_model
