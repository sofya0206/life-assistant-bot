"""Локальная транскрипция голосовых через faster-whisper (тот же подход,
что в tg-transcribe-bot). Модель грузится лениво при первом голосовом."""
from __future__ import annotations

import asyncio
import logging

from .config import settings

log = logging.getLogger(__name__)
_model = None
_model_lock = asyncio.Lock()


def _load_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel  # тяжёлый импорт — только по требованию

        log.info("Загружаю whisper-модель %s", settings.whisper_model)
        _model = WhisperModel(settings.whisper_model, device="cpu", compute_type="int8")
    return _model


def _transcribe_sync(path: str, language: str | None) -> str:
    model = _load_model()
    segments, _info = model.transcribe(path, language=language or None, vad_filter=True, beam_size=5)
    return " ".join(s.text.strip() for s in segments).strip()


async def transcribe(path: str, language: str | None = None) -> str:
    async with _model_lock:
        return await asyncio.to_thread(_transcribe_sync, path, language or settings.whisper_language)
