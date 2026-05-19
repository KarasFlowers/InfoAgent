"""
Unified async LLM client wrapping any OpenAI-compatible API.

All LLM calls across the codebase should go through ``LLMClient.chat``
(non-streaming) or ``LLMClient.chat_stream`` (streaming) so that the
model name, API key, and base URL are configured in exactly one place.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Literal

from openai import AsyncOpenAI

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletion

logger = logging.getLogger(__name__)

TierName = Literal["fast", "smart"]


def _parse_tier_spec(spec: str, fallback_base_url: str, fallback_api_key: str | None):
    """Parse a tier spec like 'openai:gpt-4o-mini' into (base_url, api_key, model).

    Supported formats:
      - ""                       → None (use default)
      - "model-name"             → same base_url/api_key, different model
      - "provider:model-name"    → well-known provider base_url, same api_key
      - "base_url|api_key|model" → fully custom endpoint (pipe-separated)
    """
    spec = spec.strip()
    if not spec:
        return None

    # Fully custom: "https://api.example.com/v1|sk-xxx|model-name"
    if "|" in spec:
        parts = spec.split("|", 2)
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
        return None

    # Well-known providers
    _PROVIDER_URLS = {
        "openai": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "anthropic": "https://api.anthropic.com/v1",
        "groq": "https://api.groq.com/openai/v1",
        "together": "https://api.together.xyz/v1",
        "silicon": "https://api.siliconflow.cn/v1",
        "moonshot": "https://api.moonshot.cn/v1",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    }

    if ":" in spec:
        provider, model = spec.split(":", 1)
        provider_lower = provider.lower()
        base_url = _PROVIDER_URLS.get(provider_lower, fallback_base_url)
        return base_url, fallback_api_key, model

    # Plain model name — same endpoint, different model
    return fallback_base_url, fallback_api_key, spec


class LLMClient:
    """Provider-agnostic async LLM client with multi-tier routing.

    Wraps ``AsyncOpenAI`` and injects the configured model name so that
    callers never have to pass ``model=`` themselves.

    Supports ``tier="fast"`` or ``tier="smart"`` to route to different
    models. When a tier is not configured, falls back to the default model.

    Parameters are read from ``Settings.effective_llm_*`` properties,
    which fall back to the legacy ``DEEPSEEK_*`` variables when the new
    ``LLM_*`` variables are not set.
    """

    def __init__(self, settings: Any) -> None:
        self.model: str = settings.LLM_MODEL
        self._default_base_url: str = settings.effective_llm_base_url
        self._default_api_key: str | None = settings.effective_llm_api_key
        self._timeout: float = float(settings.LLM_TIMEOUT)
        self._max_retries: int = settings.LLM_MAX_RETRIES

        # Default client (used for "smart" tier and as fallback)
        self._client = AsyncOpenAI(
            api_key=self._default_api_key,
            base_url=self._default_base_url,
            timeout=self._timeout,
            max_retries=self._max_retries,
        )

        # Tier-specific clients and models (lazily populated)
        self._tier_clients: dict[str, AsyncOpenAI] = {}
        self._tier_models: dict[str, str] = {}

        # Parse tier specs
        self._tier_specs: dict[str, str] = {
            "fast": getattr(settings, "FAST_LLM", ""),
            "smart": getattr(settings, "SMART_LLM", ""),
        }

        logger.info(
            "LLMClient initialised  model=%s  base_url=%s  fast=%s  smart=%s",
            self.model,
            self._default_base_url,
            self._tier_specs["fast"] or "(default)",
            self._tier_specs["smart"] or "(default)",
        )

    def _get_tier(self, tier: TierName | None) -> tuple[AsyncOpenAI, str]:
        """Resolve a tier to (client, model_name). Falls back to default."""
        if not tier:
            return self._client, self.model

        # Check cache
        if tier in self._tier_clients:
            return self._tier_clients[tier], self._tier_models[tier]

        # Parse spec
        spec = self._tier_specs.get(tier, "")
        parsed = _parse_tier_spec(spec, self._default_base_url, self._default_api_key)
        if parsed is None:
            # No config for this tier — use default
            self._tier_clients[tier] = self._client
            self._tier_models[tier] = self.model
            return self._client, self.model

        base_url, api_key, model = parsed

        # Reuse default client if endpoint matches
        if base_url == self._default_base_url and api_key == self._default_api_key:
            self._tier_clients[tier] = self._client
            self._tier_models[tier] = model
        else:
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=self._timeout,
                max_retries=self._max_retries,
            )
            self._tier_clients[tier] = client
            self._tier_models[tier] = model
            logger.info(
                "LLMClient tier '%s' → model=%s base_url=%s", tier, model, base_url
            )

        return self._tier_clients[tier], self._tier_models[tier]

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        tier: TierName | None = None,
        label: str = "",
        **kwargs: Any,
    ) -> "ChatCompletion":
        """Non-streaming chat completion.

        Automatically injects ``model`` and records token metrics.
        Callers may pass any extra ``openai`` kwargs (``temperature``,
        ``max_tokens``, ``response_format``, etc.).

        Args:
            tier: Route to "fast" or "smart" model. None uses default.
            label: Optional label for cost tracking (e.g. "scoring", "summary").
        """
        from app.services.metrics_service import metrics_service

        client, model = self._get_tier(tier)
        kwargs.setdefault("model", model)
        start = time.time()
        response = await client.chat.completions.create(
            messages=messages,
            **kwargs,
        )
        duration = time.time() - start

        if response.usage:
            await metrics_service.record_tokens(
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                label=label,
            )
        await metrics_service.record_latency(duration)
        return response

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        tier: TierName | None = None,
        **kwargs: Any,
    ):
        """Streaming chat completion.

        Returns an async iterator of ``ChatCompletionChunk`` objects.
        The caller is responsible for extracting deltas and recording
        usage from the final chunk (when ``chunk.usage`` is set).

        ``stream=True`` and ``stream_options`` are injected automatically.
        """
        client, model = self._get_tier(tier)
        kwargs.setdefault("model", model)
        kwargs["stream"] = True
        kwargs.setdefault("stream_options", {"include_usage": True})
        return await client.chat.completions.create(
            messages=messages,
            **kwargs,
        )

    @property
    def raw(self) -> AsyncOpenAI:
        """Escape-hatch for call-sites that still need the raw client."""
        return self._client
