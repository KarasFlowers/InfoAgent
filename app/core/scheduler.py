"""
APScheduler-based background jobs.

Currently registered jobs
-------------------------
- **cleanup_old_data** – runs every 6 hours (and once on startup) to prune
  expired summaries, news items, and RAG collections.
- **daily_push** - runs daily at configured time (default 08:00) to auto-generate
  the briefing and notify via all configured channels (email, webhook, bark, telegram).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _run_cleanup() -> None:
    """Synchronous wrapper executed by APScheduler's thread-pool."""
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(_async_cleanup())
    except Exception:
        logger.exception("Scheduled cleanup failed")
    finally:
        loop.close()


async def _async_cleanup() -> None:
    from app.core.db import AsyncSessionLocal
    from app.services.db_service import db_service

    async with AsyncSessionLocal() as session:
        deleted = await db_service.cleanup_old_data(
            session, days_to_keep=settings.HISTORY_DAYS_TO_KEEP
        )
        logger.info("Scheduled cleanup removed %s old summaries", deleted)


def _run_daily_push() -> None:
    """Synchronous wrapper for daily notification push."""
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(_async_daily_push())
    except Exception:
        logger.exception("Scheduled daily push failed")
    finally:
        loop.close()


async def _async_daily_push() -> None:
    """Generate summaries for all active boards and notify via configured channels."""
    from app.core.db import AsyncSessionLocal
    from app.services.db_service import db_service
    from app.services.notification import notify_service
    from app.services.source_adapters import get_adapter, UnknownSourceTypeError

    logger.info("Starting daily background summary generation and push (per-board).")
    search_date = datetime.now().strftime("%Y-%m-%d")

    async with AsyncSessionLocal() as session:
        boards = await db_service.list_boards(session, active_only=True)
        if not boards:
            logger.warning("No active boards found; skipping daily push.")
            return

        for board in boards:
            logger.info("Daily push: processing board '%s'", board.slug)
            existing = await db_service.get_summary_by_date(
                session, search_date, board_id=board.id
            )
            summary = existing
            if not summary:
                try:
                    adapter = get_adapter(board.source_type)
                except UnknownSourceTypeError as error:
                    logger.error("Skipping board '%s': %s", board.slug, error)
                    continue

                try:
                    summary, content_fallback = await adapter.produce(board=board, session=session)
                except Exception:
                    logger.exception("Adapter '%s' failed for board '%s'", board.source_type, board.slug)
                    continue

                if summary:
                    try:
                        await db_service.save_summary(session, summary, board_id=board.id)
                    except Exception:
                        logger.exception(
                            "Failed to save background summary for board '%s'", board.slug
                        )
                        continue

                    # Enqueue URLs for background ingestion (RSS items only).
                    if settings.RAG_BACKGROUND_INGEST_ENABLED:
                        from app.services.rag_service import enqueue_for_ingest
                        article_urls = [
                            item.original_link
                            for item in summary.top_news
                            if item.original_link and not item.original_link.startswith("llm://")
                        ]
                        if article_urls:
                            fb = {u: content_fallback[u] for u in article_urls if u in content_fallback}
                            enqueue_for_ingest(article_urls, fallback_contents=fb if fb else None)

            if summary:
                # Determine per-board notification channels (or use global default)
                board_channels = None
                if hasattr(board, "notify_channels") and board.notify_channels:
                    board_channels = [
                        ch.strip() for ch in board.notify_channels.split(",") if ch.strip()
                    ]
                try:
                    await notify_service.send(summary, channels=board_channels)
                except Exception:
                    logger.exception("Failed to notify for board '%s'", board.slug)
            else:
                logger.warning("No summary produced for board '%s'", board.slug)


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler(daemon=True)
    
    # 1. Cleanup Job
    _scheduler.add_job(
        _run_cleanup,
        trigger=IntervalTrigger(hours=6),
        id="cleanup_old_data",
        name="Prune expired summaries & RAG collections",
        replace_existing=True,
        next_run_time=None,  # skip immediate run; we'll fire once below
    )
    
    # 2. Daily Push Job
    try:
        hour, minute = map(int, settings.DAILY_PUSH_TIME.split(":"))
        _scheduler.add_job(
            _run_daily_push,
            trigger=CronTrigger(hour=hour, minute=minute),
            id="daily_push",
            name="Daily Notification Push",
            replace_existing=True,
        )
        logger.info(f"Scheduled daily push for {hour:02d}:{minute:02d}")
    except ValueError:
        logger.error(f"Invalid DAILY_PUSH_TIME format: {settings.DAILY_PUSH_TIME}. Expected HH:MM.")

    _scheduler.start()
    logger.info("APScheduler started")

    # Fire the first cleanup in a background thread so startup isn't blocked.
    _scheduler.add_job(
        _run_cleanup,
        id="cleanup_startup",
        name="One-shot startup cleanup",
        replace_existing=True,
    )


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("APScheduler stopped")
