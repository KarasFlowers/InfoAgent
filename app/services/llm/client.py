"""
Unified async LLM client wrapping any OpenAI-compatible API.

All LLM calls across the codebase should go through ``LLMClient.chat``
(non-streaming) or ``LLMClient.chat_stream`` (streaming) so that the
model name, API key, and base URL are configured in exactly one place.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from openai import AsyncOpenAI

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletion

logger = logging.getLogger(__name__)


class LLMClient:
    """Provider-agnostic async LLM client.

    Wraps ``AsyncOpenAI`` and injects the configured model name so that
    callers never have to pass ``model=`` themselves.

    Parameters are read from ``Settings.effective_llm_*`` properties,
    which fall back to the legacy ``DEEPSEEK_*`` variables when the new
    ``LLM_*`` variables are not set.
    """

    def __init__(self, settings: Any) -> None:
        self.model: str = settings.LLM_MODEL
        self._client = AsyncOpenAI(
            api_key=settings.effective_llm_api_key,
            base_url=settings.effective_llm_base_url,
            timeout=float(settings.LLM_TIMEOUT),
            max_retries=settings.LLM_MAX_RETRIES,
        )
        logger.info(
            "LLMClient initialised  model=%s  base_url=%s",
            self.model,
            settings.effective_llm_base_url,
        )

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> "ChatCompletion":
        """Non-streaming chat completion.

        Automatically injects ``model`` and records token metrics.
        Callers may pass any extra ``openai`` kwargs (``temperature``,
        ``max_tokens``, ``response_format``, etc.).
        """
        from app.services.metrics_service import metrics_service

        kwargs.setdefault("model", self.model)
        start = time.time()
        response = await self._client.chat.completions.create(
            messages=messages,
            **kwargs,
        )
        duration = time.time() - start

        if response.usage:
            await metrics_service.record_tokens(
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
            )
        await metrics_service.record_latency(duration)
        return response

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ):
        """Streaming chat completion.

        Returns an async iterator of ``ChatCompletionChunk`` objects.
        The caller is responsible for extracting deltas and recording
        usage from the final chunk (when ``chunk.usage`` is set).

        ``stream=True`` and ``stream_options`` are injected automatically.
        """
        kwargs.setdefault("model", self.model)
        kwargs["stream"] = True
        kwargs.setdefault("stream_options", {"include_usage": True})
        return await self._client.chat.completions.create(
            messages=messages,
            **kwargs,
        )

    @property
    def raw(self) -> AsyncOpenAI:
        """Escape-hatch for call-sites that still need the raw client."""
        return self._client
