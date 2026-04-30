"""
Hacker News source adapter.

Reads ``board.source_config`` for HN-specific settings (fetch_top_stories,
min_score), fetches via the HN scraper, and hands off to the LLM editor.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.source_adapters.base import SourceAdapter

if TYPE_CHECKING:
    from app.models.domain import Board
    from app.models.schemas import DailySummaryResponse

logger = logging.getLogger(__name__)


class HackerNewsAdapter(SourceAdapter):
    """Fetch Hacker News stories + comments, then generate a curated summary."""

    source_type = "hackernews"

    async def produce(
        self,
        board: "Board",
        session: AsyncSession,
        one_time_preference: str | None = None,
    ) -> "tuple[DailySummaryResponse | None, dict[str, str]]":
        from app.core.http_client import get_http_client
        from app.scrapers.hackernews import HackerNewsScraper

        try:
            config = json.loads(board.source_config or "{}")
        except (json.JSONDecodeError, TypeError):
            config = {}

        scraper_config = {
            "enabled": True,
            "fetch_top_stories": config.get("fetch_top_stories", settings.HN_FETCH_TOP_STORIES),
            "min_score": config.get("min_score", settings.HN_MIN_SCORE),
        }

        since = datetime.now(timezone.utc) - timedelta(hours=24)

        client = get_http_client()
        scraper = HackerNewsScraper(scraper_config, client)
        items = await scraper.fetch(since)

        if not items:
            logger.info("HN adapter: no items fetched for board '%s'", board.slug)
            return None, {}

        from app.services.llm_service import llm_service

        return await llm_service.generate_daily_summary_from_items(
            items,
            session=session,
            one_time_preference=one_time_preference,
            board=board,
        )
