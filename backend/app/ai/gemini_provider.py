from __future__ import annotations

import logging
from collections.abc import Iterator

import httpx

from google import genai
from google.genai import errors, types

from app.ai.provider import AIProvider
from app.core.config import get_settings

logger = logging.getLogger(__name__)
RETRYABLE_CODES = {408, 429, 500, 502, 503, 504}


class GeminiProvider(AIProvider):
    def __init__(self, api_key: str | None = None, model: str | None = None, fallback_model: str | None = None, second_fallback_model: str | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = self._normalize_model(model or settings.GEMINI_MODEL)
        fallback = fallback_model if fallback_model is not None else settings.GEMINI_FALLBACK_MODEL
        self.fallback_model = self._normalize_model(fallback) if fallback else None
        second = second_fallback_model if second_fallback_model is not None else settings.GEMINI_SECOND_FALLBACK_MODEL
        self.second_fallback_model = self._normalize_model(second) if second else None

    @staticmethod
    def _normalize_model(model_name: str) -> str:
        name = model_name.strip().removeprefix("models/")
        if not name:
            raise ValueError("A Gemini model name is required.")
        return name

    def _model_candidates(self) -> list[str]:
        return list(dict.fromkeys(m for m in (self.model, self.fallback_model, self.second_fallback_model) if m))

    def _client(self):
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")
        return genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(
                timeout=60000,
                retry_options=types.HttpRetryOptions(
                    attempts=3, initial_delay=1, max_delay=8, exp_base=2,
                    http_status_codes=sorted(RETRYABLE_CODES),
                ),
            ),
        )

    @staticmethod
    def _config():
        return types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level="low")
        )

    def generate(self, prompt: str) -> str:
        last_error = RuntimeError("Gemini returned an empty response.")
        with self._client() as client:
            for model in self._model_candidates():
                try:
                    response = client.models.generate_content(
                        model=model, contents=prompt, config=self._config(),
                    )
                    if response.text and response.text.strip():
                        return response.text.strip()
                    last_error = RuntimeError("Gemini returned an empty response.")
                    logger.warning("Gemini generate returned no text: model=%s", model)
                except errors.APIError as exc:
                    logger.warning("Gemini generate failed: model=%s HTTP=%s", model, exc.code)
                    if exc.code not in RETRYABLE_CODES:
                        raise
                    last_error = exc
                except httpx.TransportError as exc:
                    logger.warning("Gemini generate disconnected: model=%s type=%s", model, type(exc).__name__)
                    last_error = exc
        raise last_error

    def stream_generate(self, prompt: str) -> Iterator[str]:
        last_error = RuntimeError("Gemini returned an empty stream.")
        accumulated = ""
        with self._client() as client:
            for model in self._model_candidates():
                emitted = False
                continuation_prompt = prompt
                if accumulated:
                    continuation_prompt += (
                        "\n\nThe response was interrupted. Continue the existing assistant answer "
                        "from its exact ending. Output only the missing continuation, including any "
                        "needed leading whitespace. Do not repeat or replace the existing text."
                        "\n<existing_answer>" + accumulated + "</existing_answer>"
                    )
                try:
                    stream = client.models.generate_content_stream(
                        model=model, contents=continuation_prompt, config=self._config(),
                    )
                    for chunk in stream:
                        if chunk.text:
                            emitted = True
                            accumulated += chunk.text
                            yield chunk.text
                    if emitted:
                        return
                    last_error = RuntimeError("Gemini returned an empty stream.")
                    logger.warning("Gemini stream returned no text: model=%s", model)
                except errors.APIError as exc:
                    logger.warning("Gemini stream failed: model=%s HTTP=%s partial=%s", model, exc.code, bool(accumulated))
                    if exc.code not in RETRYABLE_CODES:
                        raise
                    last_error = exc
                except httpx.TransportError as exc:
                    logger.warning("Gemini stream disconnected: model=%s type=%s", model, type(exc).__name__)
                    last_error = exc
        raise last_error
