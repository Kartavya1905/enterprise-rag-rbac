"""
FILE:         app/generation/llm.py
WHAT IT DOES: Talks to the local LLM (Ollama) - sends the system rules + the user message,
              gets the answer text back.
WHERE IT FITS: Phase 7 - the only place the app calls a language model.
USED BY:      generation/answer.py, api/query.py.

Ollama runs in Docker (service "ollama") on your own machine - GPU if available,
otherwise CPU. Free, no API key, and company data never leaves the computer.
"""

from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import get_settings


class LLMUnavailable(RuntimeError):
    """The model server is down, too slow, or returned an error."""


# Anything that can turn (system rules, user message) into text. Tests use a fake.
class LLM(Protocol):
    def generate(self, system: str, user: str) -> str: ...


class OllamaLLM:
    def __init__(self, base_url: str, model: str, *, temperature: float, max_tokens: int,
                 context_tokens: int, timeout: float) -> None:
        self.model = model
        self._client = httpx.Client(base_url=base_url, timeout=timeout)
        self._options = {
            "temperature": temperature,  # low = stick to the facts, little creativity
            "num_predict": max_tokens,  # cap on answer length
            "num_ctx": context_tokens,  # how much text the model can consider at once
        }

    def generate(self, system: str, user: str) -> str:
        # The system rules and the user message are SEPARATE messages - the model is
        # trained to give the system message priority over anything in the user turn.
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": self._options,
        }
        try:
            response = self._client.post("/api/chat", json=payload)
            response.raise_for_status()
            return response.json()["message"]["content"].strip()
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LLMUnavailable(type(exc).__name__) from exc


@lru_cache
def get_llm() -> LLM:
    s = get_settings()
    return OllamaLLM(
        s.ollama_base_url, s.llm_model,
        temperature=s.llm_temperature, max_tokens=s.llm_max_tokens,
        context_tokens=s.llm_context_tokens, timeout=s.llm_timeout_seconds,
    )
