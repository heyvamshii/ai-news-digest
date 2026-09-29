"""A thin Groq wrapper that always returns parsed JSON."""

import json
import time
from typing import Protocol

from groq import APIStatusError, Groq, GroqError

from config import FALLBACK_MODELS, LLM_MAX_RETRIES, LLM_PAUSE_SECONDS


class LLMError(Exception):
    """Raised when no model could answer."""


class JSONModel(Protocol):
    """Anything that can answer a prompt with a dict. Tests pass a fake one."""

    name: str

    def ask(self, system: str, user: str) -> dict: ...


class GroqJSON:
    def __init__(self, api_key: str, model: str, fallbacks: tuple[str, ...] = FALLBACK_MODELS):
        if not api_key:
            raise LLMError("GROQ_API_KEY is missing. Copy .env.example to .env and paste your key in it.")
        # max_retries makes the SDK wait and retry on 429 rate-limit replies.
        self._client = Groq(api_key=api_key, max_retries=LLM_MAX_RETRIES)
        self._models = tuple(dict.fromkeys((model, *fallbacks)))
        self.name = model

    def _call(self, model: str, system: str, user: str) -> dict:
        extra = {"reasoning_effort": "low"} if model.startswith("openai/gpt-oss") else {}
        response = self._client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_completion_tokens=2500,
            **extra,
        )
        return json.loads(response.choices[0].message.content or "{}")

    def ask(self, system: str, user: str) -> dict:
        """Try the configured model, then the fallbacks (models do get retired)."""
        errors = []
        for model in self._models:
            try:
                result = self._call(model, system, user)
                self.name = model
                time.sleep(LLM_PAUSE_SECONDS)      # stay gentle with the free tier
                return result
            except APIStatusError as exc:
                errors.append(f"{model}: HTTP {exc.status_code}")
                if exc.status_code not in (400, 404, 413, 429, 503):
                    break
            except (GroqError, json.JSONDecodeError) as exc:
                errors.append(f"{model}: {exc.__class__.__name__}")
        raise LLMError("; ".join(errors))
