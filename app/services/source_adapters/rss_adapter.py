"""
RSS-based source adapter.

Reads ``board.source_config["feeds"]`` (list of RSS URLs), fetches them,
scores the articles, and hands off to the LLM editor for summarization.
"""
import json
import logging
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.rss_service import fetch_all_feeds
from app.services.source_adapters.base import SourceAdapter

if TYPE_CHECKING:
    from app.models.domain import Board
    from app.models.schemas import DailySummaryResponse

logger = logging.getLogger(__name__)


class RSSAdapter(SourceAdapter):
    """Fetch configured RSS feeds, then generate a curated summary."""

    source_type = "rss"

    async def produce(
        self,
        board: "Board",
        session: AsyncSession,
        one_time_preference: str | None = None,
    ) -> "DailySummaryResponse | None":
        # Resolve feed list: prefer per-board config, fall back to global.
        feeds: list[str] = []
        try:
            config = json.loads(board.source_config or "{}")
            feeds = list(config.get("feeds") or [])
        except (json.JSONDecodeError, TypeError):
            logger.warning("Board '%s' has invalid source_config JSON", board.slug)

        if not feeds:
            feeds = list(settings.RSS_FEEDS)
            logger.info(
                "Board '%s' has no feeds configured; falling back to global RSS_FEEDS (%d)",
                board.slug,
                len(feeds),
            )

        results = await fetch_all_feeds(feeds)

        # Lazy-import llm_service to avoid circulars at module import time.
        from app.services.llm_service import llm_service

        return await llm_service.generate_daily_summary(
            results,
            session=session,
            one_time_preference=one_time_preference,
            board=board,
        )
