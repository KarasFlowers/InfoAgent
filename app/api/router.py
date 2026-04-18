import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.models.schemas import DailySummaryResponse, RSSResponse, SummaryHistoryResponse
from app.services.db_service import db_service
from app.services.learning_service import get_inferred_interests, rerank_summary_items
from app.services.llm_service import llm_service
from app.services.rss_service import fetch_all_feeds

api_router = APIRouter()
logger = logging.getLogger(__name__)
_summary_generation_lock = asyncio.Lock()


@api_router.get("/ping")
async def ping():
    """
    Health check endpoint.
    """
    return {"status": "ok", "message": "pong"}


@api_router.get("/feeds", response_model=list[RSSResponse])
async def manually_trigger_rss_fetch():
    """
    Manually fetch updates from all configured RSS feeds.
    """
    return await fetch_all_feeds(settings.RSS_FEEDS)


@api_router.get("/summary", response_model=DailySummaryResponse)
async def generate_summary(
    force: bool = False,
    date: Optional[str] = None,
    preference: Optional[str] = None,
    save_preference: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """
    Returns AI summary for today or a specific date.
    If date is provided, only fetch from DB (no external generation for history).
    """
    search_date = date if date else datetime.now().strftime("%Y-%m-%d")

    # 1. Check database first (FAST PATH)
    if not force:
        existing_summary = await db_service.get_summary_by_date(session, search_date)
        if existing_summary:
            try:
                existing_summary.top_news = await rerank_summary_items(existing_summary.top_news)
            except Exception:
                logger.debug("Persona reranking skipped (no feedback data or model not loaded)")
            return existing_summary

    # If it's a historical date and not in DB, we don't generate (to save costs/avoid confusion)
    if date and date != datetime.now().strftime("%Y-%m-%d"):
        raise HTTPException(status_code=404, detail=f"No historical summary found for {date}.")

    async with _summary_generation_lock:
        if not force:
            existing_summary = await db_service.get_summary_by_date(session, search_date)
            if existing_summary:
                try:
                    existing_summary.top_news = await rerank_summary_items(existing_summary.top_news)
                except Exception:
                    pass
                return existing_summary

        results = await fetch_all_feeds(settings.RSS_FEEDS)
        summary = await llm_service.generate_daily_summary(
            results,
            session=session,
            one_time_preference=preference,
        )

        if not summary:
            raise HTTPException(status_code=500, detail="Failed to generate AI summary.")

        try:
            if force:
                await db_service.replace_summary(session, summary)
            else:
                await db_service.save_summary(session, summary)
        except IntegrityError:
            logger.warning("Summary for %s already exists, returning stored version.", search_date)
            await session.rollback()
            existing_summary = await db_service.get_summary_by_date(session, search_date)
            if existing_summary:
                return existing_summary
            raise HTTPException(status_code=500, detail="Failed to save AI summary.")
        except Exception:
            logger.exception("Failed to persist summary for %s", search_date)
            await session.rollback()
            raise HTTPException(status_code=500, detail="Failed to save AI summary.")

        if preference and save_preference:
            try:
                await db_service.save_persona(session, content=preference, category="instruction")
            except Exception:
                logger.exception("Failed to save persona preference")
                raise HTTPException(status_code=500, detail="Summary was generated but the preference could not be saved.")

        # 成功生成新简报后，尝试触发一次清理任务 (静默执行)
        try:
            await db_service.cleanup_old_data(session, days_to_keep=settings.HISTORY_DAYS_TO_KEEP)
        except Exception:
            logger.warning("Auto-cleanup task failed, skipping...")

        stored_summary = await db_service.get_summary_by_date(session, search_date)
        final = stored_summary or summary
        try:
            final.top_news = await rerank_summary_items(final.top_news)
        except Exception:
            logger.debug("Persona reranking skipped for fresh summary")
        return final


@api_router.get("/persona")
async def get_persona(session: AsyncSession = Depends(get_session)):
    """
    Get all active persona instructions.
    """
    return await db_service.get_active_personas(session)


@api_router.post("/persona")
async def add_persona(
    content: str,
    category: str = "instruction",
    session: AsyncSession = Depends(get_session),
):
    """
    Add a new persona instruction.
    """
    await db_service.save_persona(session, content, category)
    return {"status": "ok"}


@api_router.delete("/persona/{persona_id}")
async def delete_persona(persona_id: int, session: AsyncSession = Depends(get_session)):
    """
    Delete a persona instruction.
    """
    await db_service.delete_persona(session, persona_id)
    return {"status": "ok"}


@api_router.get("/persona/inferred")
async def get_inferred_persona(session: AsyncSession = Depends(get_session)):
    """
    Analyze feedback history to infer user interests.
    """
    return await get_inferred_interests(session)


@api_router.get("/history", response_model=SummaryHistoryResponse)
async def get_summary_history(limit: int = 7, session: AsyncSession = Depends(get_session)):
    """
    Retrieve lightweight archive cards and weekly recap for recent summaries.
    """
    safe_limit = max(1, min(limit, 30))
    return await db_service.get_summary_history(session, limit=safe_limit)


@api_router.get("/history/weekly_insight")
async def get_weekly_insight(limit: int = 7, session: AsyncSession = Depends(get_session)):
    """
    Generate a deep, Wired-style weekly consolidation from recent summaries.
    """
    safe_limit = max(1, min(limit, 10))
    
    # 1. Fetch recent summaries with enough detail
    history = await db_service.get_summary_history(session, limit=safe_limit)
    if not history.archive_items:
        raise HTTPException(status_code=404, detail="No history found to summarize.")

    # 2. Re-fetch or pass full data to LLM
    # For now, let's just get the recent dates and fetch full data for those
    summaries_data = []
    for item in history.archive_items:
        full = await db_service.get_summary_by_date(session, item.date)
        if full:
            summaries_data.append(full.dict())

    if not summaries_data:
        raise HTTPException(status_code=404, detail="Failed to retrieve history content.")

    # 3. Generate consolidation
    insight = await llm_service.generate_weekly_consolidation(summaries_data)
    if not insight:
        raise HTTPException(status_code=500, detail="Failed to generate weekly insight.")

    return {"weekly_insight": insight}
