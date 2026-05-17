import asyncio
import html as html_mod
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.models.schemas import DailySummaryResponse, RSSResponse, SummaryHistoryResponse
from app.services.db_service import db_service
from app.services.learning_service import get_inferred_interests, rerank_summary_items
from app.services.llm_service import llm_service
from app.services.metrics_service import metrics_service
from app.services.rss_service import fetch_all_feeds
from app.services.email_service import email_service

logger = logging.getLogger(__name__)

class PersonaCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    category: str = Field(default="instruction", max_length=64)
    board_id: Optional[int] = None  # null = global persona


class BoardCreateRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_\-]+$")
    name: str = Field(min_length=1, max_length=128)
    icon: str = Field(default="", max_length=32)
    description: str = Field(default="", max_length=500)
    system_prompt: str = Field(default="", max_length=4000)
    source_type: str = Field(default="rss", max_length=32)
    source_config: dict = Field(default_factory=dict)
    display_order: int = Field(default=0)


class BoardUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    icon: Optional[str] = Field(default=None, max_length=32)
    description: Optional[str] = Field(default=None, max_length=500)
    system_prompt: Optional[str] = Field(default=None, max_length=4000)
    source_type: Optional[str] = Field(default=None, max_length=32)
    source_config: Optional[dict] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class BoardWizardMessage(BaseModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class BoardWizardRequest(BaseModel):
    messages: list[BoardWizardMessage] = Field(min_length=1, max_length=20)


_summary_generation_lock = asyncio.Lock()

api_router = APIRouter()

@api_router.get("/feed")
async def get_rss_feed(session: AsyncSession = Depends(get_session)):
    """
    Export the last 7 daily summaries as a standard RSS 2.0 XML feed.
    """
    history = await db_service.get_summary_history(session, limit=7)
    
    # We'll use the domain of the first incoming request or just a generic placeholder 
    # since we don't have a configured base URL for the app itself in settings.
    site_url = "https://argos.local"
    
    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        '  <channel>',
        '    <title>Argos Daily Briefing</title>',
        f'    <link>{site_url}</link>',
        '    <description>Your personalized daily technology and AI briefing.</description>',
        '    <language>zh-cn</language>'
    ]
    
    from datetime import timezone
    for history_item in history:
        summary = await db_service.get_summary_by_date(session, history_item.date)
        if not summary:
            continue
            
        # Convert date string to proper RFC-822 date format for RSS
        try:
            dt = datetime.strptime(summary.date, "%Y-%m-%d")
            dt = dt.replace(tzinfo=timezone.utc)
            pub_date = dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
        except ValueError:
            pub_date = ""

        # Build the HTML content for the RSS description
        html_content = email_service._render_html(summary)
        
        # Escape XML entities
        escaped_html = html_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")
        
        xml.append('    <item>')
        xml.append(f'      <title>{html_mod.escape(f"Argos 日报 - {summary.date}")}</title>')
        xml.append(f'      <link>{html_mod.escape(f"{site_url}/?date={summary.date}")}</link>')
        xml.append(f'      <guid isPermaLink="false">argos-{html_mod.escape(summary.date)}</guid>')
        if pub_date:
            xml.append(f'      <pubDate>{pub_date}</pubDate>')
        xml.append(f'      <description>{escaped_html}</description>')
        xml.append('    </item>')
        
    xml.append('  </channel>')
    xml.append('</rss>')
    
    return Response(content="\n".join(xml), media_type="application/rss+xml")


@api_router.get("/metrics")
async def get_system_metrics(date: str | None = None):
    """
    Get system metrics (token usage and latency) for a specific date (defaults to today).
    """
    return await metrics_service.get_daily_metrics(date)


@api_router.get("/insights/heatmap")
async def get_insights_heatmap(
    session: AsyncSession = Depends(get_session),
    days: int = Query(default=7, ge=1, le=30),
):
    """
    Get a topic heatmap (category + tag counts per day) for the last N days.
    """
    from app.services.insights_service import get_topic_heatmap
    return await get_topic_heatmap(session, days)


@api_router.get("/insights/timeline")
async def get_insights_timeline(
    session: AsyncSession = Depends(get_session),
    entity: str = Query(..., min_length=1),
    days: int = Query(default=30, ge=1, le=90),
):
    """
    Get a timeline of news items mentioning a specific entity keyword.
    """
    from app.services.insights_service import get_entity_timeline
    return await get_entity_timeline(session, entity, days)


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


class TestFeedRequest(BaseModel):
    url: str = Field(min_length=5, max_length=2048)


@api_router.post("/sources/test")
async def test_source_feed(payload: TestFeedRequest):
    """
    Test a single RSS feed URL. Returns status, article count, and sample titles.
    Does NOT cache the result.
    """
    import httpx
    import feedparser

    url = payload.url.strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        async with httpx.AsyncClient(headers=headers) as client:
            resp = await client.get(url, timeout=15.0, follow_redirects=True)
            resp.raise_for_status()

        feed = feedparser.parse(resp.text)
        entries = feed.entries or []
        feed_title = feed.feed.get("title", "Unknown Feed")

        return {
            "ok": True,
            "feed_title": feed_title,
            "article_count": len(entries),
            "sample_titles": [e.get("title", "Untitled") for e in entries[:5]],
        }
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"HTTP {e.response.status_code}"}
    except httpx.TimeoutException:
        return {"ok": False, "error": "请求超时 (15s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


async def _resolve_board(session: AsyncSession, slug: str | None):
    """
    Resolve an optional board slug to a Board row. When slug is None,
    returns the default board. Raises 404 if slug is provided but not found.
    """
    if slug:
        board = await db_service.get_board_by_slug(session, slug)
        if not board or not board.is_active:
            raise HTTPException(status_code=404, detail=f"Board '{slug}' not found or inactive.")
        return board
    return await db_service.get_default_board(session)


@api_router.get("/summary", response_model=DailySummaryResponse)
async def generate_summary(
    force: bool = False,
    date: Optional[str] = None,
    preference: Optional[str] = None,
    save_preference: bool = False,
    board: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Returns AI summary for today or a specific date, scoped to a board.
    If board is not provided, falls back to the default board (tech).
    If date is provided, only fetch from DB (no external generation for history).
    """
    search_date = date if date else datetime.now().strftime("%Y-%m-%d")
    board_obj = await _resolve_board(session, board)
    board_id = board_obj.id if board_obj else None

    # 1. Check database first (FAST PATH)
    if not force:
        existing_summary = await db_service.get_summary_by_date(session, search_date, board_id=board_id)
        if existing_summary:
            try:
                existing_summary.top_news = await rerank_summary_items(existing_summary.top_news, session=session)
            except Exception:
                logger.debug("Persona reranking skipped (no feedback data or model not loaded)")
            return existing_summary

    # If it's a historical date and not in DB, we don't generate (to save costs/avoid confusion)
    if date and date != datetime.now().strftime("%Y-%m-%d"):
        raise HTTPException(status_code=404, detail=f"No historical summary found for {date}.")

    async with _summary_generation_lock:
        if not force:
            existing_summary = await db_service.get_summary_by_date(session, search_date, board_id=board_id)
            if existing_summary:
                try:
                    existing_summary.top_news = await rerank_summary_items(existing_summary.top_news, session=session)
                except Exception:
                    pass
                return existing_summary

        # Dispatch to the correct source adapter based on the board's source_type.
        from app.services.source_adapters import get_adapter, UnknownSourceTypeError
        if board_obj is None:
            raise HTTPException(status_code=500, detail="No board configured — cannot generate summary.")
        try:
            adapter = get_adapter(board_obj.source_type)
        except UnknownSourceTypeError as error:
            logger.error("Board '%s' has unsupported source_type: %s", board_obj.slug, error)
            raise HTTPException(status_code=500, detail=str(error))

        summary, content_fallback = await adapter.produce(
            board=board_obj,
            session=session,
            one_time_preference=preference,
        )

        if not summary:
            raise HTTPException(status_code=500, detail="Failed to generate AI summary.")

        try:
            if force:
                await db_service.replace_summary(session, summary, board_id=board_id)
            else:
                await db_service.save_summary(session, summary, board_id=board_id)
        except IntegrityError:
            logger.warning("Summary for %s already exists, returning stored version.", search_date)
            await session.rollback()
            existing_summary = await db_service.get_summary_by_date(session, search_date, board_id=board_id)
            if existing_summary:
                return existing_summary
            raise HTTPException(status_code=500, detail="Failed to save AI summary.")
        except Exception:
            logger.exception("Failed to persist summary for %s", search_date)
            await session.rollback()
            raise HTTPException(status_code=500, detail="Failed to save AI summary.")

        if preference and save_preference:
            try:
                await db_service.save_persona(
                    session, content=preference, category="instruction", board_id=board_id
                )
            except Exception:
                logger.exception("Failed to save persona preference")
                raise HTTPException(status_code=500, detail="Summary was generated but the preference could not be saved.")

        # NOTE: cleanup_old_data is now handled by APScheduler (see scheduler.py).
        # This eliminates the risk of a failed cleanup tainting the request session.

        # Enqueue articles for background RAG ingestion
        if settings.RAG_BACKGROUND_INGEST_ENABLED:
            from app.services.rag_service import enqueue_for_ingest
            article_urls = [item.original_link for item in summary.top_news if item.original_link]
            fallback = {u: content_fallback[u] for u in article_urls if u in content_fallback}
            enqueue_for_ingest(article_urls, fallback_contents=fallback if fallback else None)

        stored_summary = await db_service.get_summary_by_date(session, search_date, board_id=board_id)
        final = stored_summary or summary
        try:
            final.top_news = await rerank_summary_items(final.top_news, session=session)
        except Exception:
            logger.debug("Persona reranking skipped for fresh summary")
        return final


@api_router.get("/persona")
async def get_persona(
    board: Optional[str] = None,
    include_global: bool = True,
    session: AsyncSession = Depends(get_session),
):
    """
    Get active persona instructions. When board is provided, returns that
    board's personas (plus global ones if include_global=True).
    """
    board_id: int | None = None
    if board is not None:
        board_obj = await _resolve_board(session, board)
        board_id = board_obj.id if board_obj else None
    return await db_service.get_active_personas(
        session, board_id=board_id, include_global=include_global
    )


@api_router.post("/persona")
async def add_persona(
    payload: PersonaCreateRequest,
    board: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Add a new persona instruction.
    Priority: payload.board_id > ?board=slug > global (null).
    """
    target_board_id: int | None = payload.board_id
    if target_board_id is None and board:
        board_obj = await _resolve_board(session, board)
        target_board_id = board_obj.id if board_obj else None
    await db_service.save_persona(
        session, payload.content, payload.category, board_id=target_board_id
    )
    return {"status": "ok"}


@api_router.delete("/persona/{persona_id}")
async def delete_persona(persona_id: int, session: AsyncSession = Depends(get_session)):
    """
    Delete a persona instruction.
    """
    await db_service.delete_persona(session, persona_id)
    return {"status": "ok"}


class InterestOptionsRequest(BaseModel):
    headline: str = Field(min_length=1, max_length=500)
    key_points: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


@api_router.post("/feedback/interest-options")
async def feedback_interest_options(payload: InterestOptionsRequest):
    """
    Given a just-liked article, return 3-4 LLM-suggested abstract interest
    descriptions (e.g. "新 AI 模型发布动态") for the user to choose from,
    so we can capture *real* intent rather than the literal article topic.
    """
    options = await llm_service.extract_interest_options(
        headline=payload.headline,
        key_points=payload.key_points,
        tags=payload.tags,
    )
    return {"options": options}


class SaveInterestReasonRequest(BaseModel):
    content: str = Field(min_length=1, max_length=200)


@api_router.post("/feedback/save-reason")
async def feedback_save_reason(
    payload: SaveInterestReasonRequest,
    board: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Persist the user's chosen abstract interest reason as an `extracted`
    persona, scoped to the current board when provided.
    """
    board_id: int | None = None
    if board:
        board_obj = await _resolve_board(session, board)
        board_id = board_obj.id if board_obj else None
    await db_service.save_persona(
        session, content=payload.content, category="extracted", board_id=board_id
    )
    return {"status": "ok"}


@api_router.get("/persona/inferred")
async def get_inferred_persona(session: AsyncSession = Depends(get_session)):
    """
    Analyze feedback history to infer user interests.
    """
    return await get_inferred_interests(session)


@api_router.get("/preferences")
async def get_explicit_preferences(
    board: Optional[str] = None,
    include_global: bool = True,
    session: AsyncSession = Depends(get_session),
):
    """
    Get all explicit preference tags grouped by category, optionally scoped to a board.
    """
    board_id: int | None = None
    if board is not None:
        board_obj = await _resolve_board(session, board)
        board_id = board_obj.id if board_obj else None

    return await db_service.get_explicit_preferences_detailed(
        session, board_id=board_id, include_global=include_global
    )


# ------------------------------------------------------------------
# Board (custom section) CRUD
# ------------------------------------------------------------------

def _serialize_board(board) -> dict:
    return {
        "id": board.id,
        "slug": board.slug,
        "name": board.name,
        "icon": board.icon,
        "description": board.description,
        "system_prompt": board.system_prompt,
        "source_type": board.source_type,
        "source_config": board.source_config or {},
        "display_order": board.display_order,
        "is_active": board.is_active,
        "is_default": board.is_default,
    }


@api_router.get("/boards")
async def list_boards(
    include_inactive: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """List all boards, ordered by display_order."""
    boards = await db_service.list_boards(session, active_only=not include_inactive)
    return [_serialize_board(b) for b in boards]


@api_router.post("/boards")
async def create_board(
    payload: BoardCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Create a new custom board."""
    existing = await db_service.get_board_by_slug(session, payload.slug)
    if existing:
        raise HTTPException(status_code=409, detail=f"Board '{payload.slug}' already exists.")
    from app.services.source_adapters import VALID_SOURCE_TYPES
    if payload.source_type not in VALID_SOURCE_TYPES:
        raise HTTPException(status_code=400, detail=f"source_type must be one of {VALID_SOURCE_TYPES}.")
    # Validate source_config against the per-type schema
    from app.models.source_configs import SOURCE_CONFIG_MODELS
    config_model = SOURCE_CONFIG_MODELS.get(payload.source_type)
    if config_model and payload.source_config:
        try:
            config_model.model_validate(payload.source_config)
        except Exception as val_err:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid source_config for type '{payload.source_type}': {val_err}",
            )
    board = await db_service.create_board(
        session,
        slug=payload.slug,
        name=payload.name,
        icon=payload.icon,
        description=payload.description,
        system_prompt=payload.system_prompt,
        source_type=payload.source_type,
        source_config=payload.source_config,
        display_order=payload.display_order,
    )
    return _serialize_board(board)


@api_router.post("/boards/wizard")
async def board_wizard(payload: BoardWizardRequest):
    """
    Interactive AI-guided wizard to help users configure a new board.
    Accepts a conversation history, returns a reply plus (when ready) a suggested config.
    """
    result = await llm_service.wizard_suggest_board(
        [m.model_dump() for m in payload.messages]
    )
    return result


@api_router.get("/boards/{slug}")
async def get_board(slug: str, session: AsyncSession = Depends(get_session)):
    """Get a single board by slug."""
    board = await db_service.get_board_by_slug(session, slug)
    if not board:
        raise HTTPException(status_code=404, detail=f"Board '{slug}' not found.")
    return _serialize_board(board)


@api_router.patch("/boards/{slug}")
async def update_board(
    slug: str,
    payload: BoardUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update a board's metadata/config."""
    updates = payload.model_dump(exclude_unset=True)
    from app.services.source_adapters import VALID_SOURCE_TYPES
    if "source_type" in updates and updates["source_type"] not in VALID_SOURCE_TYPES:
        raise HTTPException(status_code=400, detail=f"source_type must be one of {VALID_SOURCE_TYPES}.")
    # Validate source_config (as dict) against the per-type schema
    if "source_config" in updates and updates["source_config"] is not None:
        st = updates.get("source_type")  # may be None if not changing
        if st:
            from app.models.source_configs import SOURCE_CONFIG_MODELS
            config_model = SOURCE_CONFIG_MODELS.get(st)
            if config_model:
                try:
                    config_model.model_validate(updates["source_config"])
                except Exception as val_err:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Invalid source_config for type '{st}': {val_err}",
                    )
        # source_config is a native JSON column; pass dict directly
    board = await db_service.update_board(session, slug, updates)
    if not board:
        raise HTTPException(status_code=404, detail=f"Board '{slug}' not found.")
    return _serialize_board(board)


@api_router.delete("/boards/{slug}")
async def delete_board(slug: str, session: AsyncSession = Depends(get_session)):
    """Soft-delete a board (mark inactive). The default board cannot be deleted."""
    ok = await db_service.delete_board(session, slug)
    if not ok:
        board = await db_service.get_board_by_slug(session, slug)
        if board and board.is_default:
            raise HTTPException(status_code=400, detail="The default board cannot be deleted.")
        raise HTTPException(status_code=404, detail=f"Board '{slug}' not found.")
    return {"status": "ok"}


@api_router.get("/history", response_model=SummaryHistoryResponse)
async def get_summary_history(
    limit: int = 7,
    board: Optional[str] = None,
    session: AsyncSession = Depends(get_session)
):
    """
    Retrieve lightweight archive cards and weekly recap for recent summaries.
    """
    safe_limit = max(1, min(limit, 30))
    board_obj = await _resolve_board(session, board)
    board_id = board_obj.id if board_obj else None
    return await db_service.get_summary_history(session, limit=safe_limit, board_id=board_id)


@api_router.get("/history/weekly_insight")
async def get_weekly_insight(
    limit: int = 7,
    board: Optional[str] = None,
    session: AsyncSession = Depends(get_session)
):
    """
    Generate a deep, Wired-style weekly consolidation from recent summaries.
    """
    safe_limit = max(1, min(limit, 10))
    board_obj = await _resolve_board(session, board)
    board_id = board_obj.id if board_obj else None
    
    # 1. Fetch recent summaries with enough detail
    history = await db_service.get_summary_history(session, limit=safe_limit, board_id=board_id)
    if not history.archive_items:
        raise HTTPException(status_code=404, detail="No history found to summarize.")

    # 2. Re-fetch or pass full data to LLM
    # For now, let's just get the recent dates and fetch full data for those
    summaries_data = []
    for item in history.archive_items:
        full = await db_service.get_summary_by_date(session, item.date, board_id=board_id)
        if full:
            summaries_data.append(full.model_dump())

    if not summaries_data:
        raise HTTPException(status_code=404, detail="Failed to retrieve history content.")

    # 3. Generate consolidation
    insight = await llm_service.generate_weekly_consolidation(summaries_data)
    if not insight:
        raise HTTPException(status_code=500, detail="Failed to generate weekly insight.")

    return {"weekly_insight": insight}
