"""Thin Gemini wrapper: structured output, backoff on rate limits and timeouts, and a per-run call budget."""

from __future__ import annotations

import logging
import time
from typing import TypeVar

import httpx
from pydantic import BaseModel

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
TIMEOUT_S = 90  # the SDK waits forever by default; an overloaded model once took 7 minutes per email
TRANSIENT = (429, 500, 503, "timeout")


class LlmUnavailable(RuntimeError):
    pass


class Llm:
    def __init__(self, api_key: str | None, model: str, max_calls: int, fallback_model: str | None = None):
        self.model = model
        self.fallback_model = fallback_model
        self.max_calls = max_calls
        self.calls = 0
        self._client = None
        if api_key:
            from google import genai
            from google.genai import types

            self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=TIMEOUT_S * 1000))

    @property
    def available(self) -> bool:
        return self._client is not None and self.calls < self.max_calls

    def structured(self, prompt: str, schema: type[T], retries: int = 4) -> T:
        if self._client is None:
            raise LlmUnavailable("GEMINI_API_KEY is not set")
        if self.calls >= self.max_calls:
            raise LlmUnavailable(f"LLM call budget of {self.max_calls} reached")
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        delay = 15.0
        for attempt in range(retries + 1):
            self.calls += 1
            try:
                response = self._client.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
                if isinstance(response.parsed, schema):
                    return response.parsed
                return schema.model_validate_json(response.text or "{}")
            except (errors.APIError, httpx.TimeoutException) as exc:
                reason = exc.code if isinstance(exc, errors.APIError) else "timeout"
                if reason in TRANSIENT and self.fallback_model and self.model != self.fallback_model:
                    # Overload and free-tier quotas are per model: another model usually answers.
                    log.warning("Gemini %s on %s, switching to %s", reason, self.model, self.fallback_model)
                    self.model = self.fallback_model
                    continue
                if reason in TRANSIENT and attempt < retries:
                    log.warning("Gemini %s, retrying in %.0fs", reason, delay)
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise
        raise AssertionError("unreachable")
