"""
Source adapters: pluggable content producers for boards.

Each adapter implements ``SourceAdapter.produce(board, session, ...)`` which
returns a ``DailySummaryResponse`` (or None on failure). The router dispatches
to the correct adapter based on ``board.source_type``.

Built-in adapters:
  - ``rss``         : pull from RSS feeds in ``board.source_config["feeds"]``
  - ``pure_llm``    : ask the LLM to generate N items, no external sources
  - ``hackernews``  : fetch Hacker News top stories + comments
  - ``reddit``      : fetch Reddit subreddit/user posts + comments
  - ``github``      : fetch GitHub user events & repo releases
  - ``multi``       : fetch from multiple source types in parallel
"""
from app.services.source_adapters.base import SourceAdapter, UnknownSourceTypeError
from app.services.source_adapters.rss_adapter import RSSAdapter
from app.services.source_adapters.pure_llm_adapter import PureLLMAdapter
from app.services.source_adapters.hackernews_adapter import HackerNewsAdapter
from app.services.source_adapters.reddit_adapter import RedditAdapter
from app.services.source_adapters.github_adapter import GitHubAdapter
from app.services.source_adapters.multi_adapter import MultiSourceAdapter

_REGISTRY: dict[str, SourceAdapter] = {
    "rss": RSSAdapter(),
    "pure_llm": PureLLMAdapter(),
    "hackernews": HackerNewsAdapter(),
    "reddit": RedditAdapter(),
    "github": GitHubAdapter(),
    "multi": MultiSourceAdapter(),
}

VALID_SOURCE_TYPES: tuple[str, ...] = tuple(_REGISTRY.keys())


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
    "VALID_SOURCE_TYPES",
    "RSSAdapter",
    "PureLLMAdapter",
    "HackerNewsAdapter",
    "RedditAdapter",
    "GitHubAdapter",
    "MultiSourceAdapter",
]
