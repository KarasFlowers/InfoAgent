"""
Source adapters: pluggable content producers for boards.

Each adapter implements ``SourceAdapter.produce(board, session, ...)`` which
returns a ``DailySummaryResponse`` (or None on failure). The router dispatches
to the correct adapter based on ``board.source_type``.

Built-in adapters:
  - ``rss``      : pull from RSS feeds in ``board.source_config["feeds"]``
  - ``pure_llm`` : ask the LLM to generate N items, no external sources
"""
from app.services.source_adapters.base import SourceAdapter, UnknownSourceTypeError
from app.services.source_adapters.rss_adapter import RSSAdapter
from app.services.source_adapters.pure_llm_adapter import PureLLMAdapter

_REGISTRY: dict[str, SourceAdapter] = {
    "rss": RSSAdapter(),
    "pure_llm": PureLLMAdapter(),
}


def get_adapter(source_type: str) -> SourceAdapter:
    """Return the adapter for a board's source_type. Raises if unknown."""
    adapter = _REGISTRY.get(source_type)
    if adapter is None:
        raise UnknownSourceTypeError(
            f"No adapter registered for source_type='{source_type}'. "
            f"Valid types: {list(_REGISTRY.keys())}"
        )
    return adapter


__all__ = [
    "SourceAdapter",
    "UnknownSourceTypeError",
    "get_adapter",
    "RSSAdapter",
    "PureLLMAdapter",
]
