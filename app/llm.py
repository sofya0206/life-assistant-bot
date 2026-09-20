"""Единый вход к LLM. Провайдер выбирается в настройках (LLM_PROVIDER или
автоматически по наличию ключей): gemini | anthropic. Остальной код знает
только interpret() / prose() / ping()."""
from __future__ import annotations

from .config import settings
from .models import AssistantOutput


class LLMDisabled(RuntimeError):
    pass


def _provider():
    name = settings.llm_provider
    if name == "openai":
        from .providers import openai_llm as p
    elif name == "gemini":
        from .providers import gemini_llm as p
    elif name == "anthropic":
        from .providers import anthropic_llm as p
    else:
        raise LLMDisabled("LLM не настроен: задай OPENAI_API_KEY, GEMINI_API_KEY или ANTHROPIC_API_KEY")
    return p


async def interpret(user_text: str, context_text: str, history: list[dict] | None = None) -> AssistantOutput:
    return await _provider().interpret(user_text, context_text, history or [])


async def prose(prompt: str, max_tokens: int = 1200) -> str:
    return await _provider().prose(prompt, max_tokens)


def model_name() -> str:
    return _provider().model_name()


async def ping() -> str:
    text = await prose("Ответь одним словом: ок", max_tokens=200)
    return f"LLM OK ({settings.llm_provider}, {model_name()}): {text[:40]}"
