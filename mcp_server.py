"""
Argos MCP Server

Exposes Argos's core capabilities as MCP (Model Context Protocol) tools,
allowing AI assistants (Claude, Cursor, Windsurf, etc.) to:

- Read today's tech briefing
- Ask RAG questions about articles
- List/search news history
- Manage boards and user preferences

Run standalone:
    python mcp_server.py            # stdio transport (default for IDE integrations)
    python mcp_server.py --http     # HTTP transport for remote access
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from typing import Optional

from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# FastMCP app
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "argos",
    instructions=(
        "Argos is an intelligent daily tech briefing assistant. "
        "Use these tools to query today's news, ask questions about articles, "
        "manage content boards, and control user preferences."
    ),
)


# ---------------------------------------------------------------------------
# Helpers — lazily initialise DB/services only when a tool is called
# ---------------------------------------------------------------------------

_db_ready = False


async def _ensure_db():
    global _db_ready
    if not _db_ready:
        from app.core.db import init_db
        await init_db()
        _db_ready = True


async def _get_session():
    from app.core.db import AsyncSessionLocal
    return AsyncSessionLocal()


# ---------------------------------------------------------------------------
# Tools: Daily Briefing
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_daily_summary(
    board_slug: str = "tech",
    date: Optional[str] = None,
) -> str:
    """Get the daily briefing for a specific board.

    Args:
        board_slug: Board identifier (e.g. "tech", "trivia"). Default "tech".
        date: Date in YYYY-MM-DD format. Defaults to today.

    Returns:
        JSON with overview, top_news items, and metadata.
    """
    await _ensure_db()
    from app.core.db import AsyncSessionLocal
    from app.services.db_service import db_service

    search_date = date or datetime.now().strftime("%Y-%m-%d")

    async with AsyncSessionLocal() as session:
        # Find the board
        boards = await db_service.list_boards(session, active_only=False)
        board = next((b for b in boards if b.slug == board_slug), None)
        if not board:
            available = [b.slug for b in boards]
            return json.dumps(
                {"error": f"Board '{board_slug}' not found. Available: {available}"},
                ensure_ascii=False,
            )

        summary = await db_service.get_summary_by_date(
            session, search_date, board_id=board.id
        )
        if not summary:
            return json.dumps(
                {"error": f"No summary found for board '{board_slug}' on {search_date}."},
                ensure_ascii=False,
            )

        items = []
        for item in summary.top_news:
            items.append({
                "headline": item.headline,
                "category": item.category,
                "key_points": item.key_points,
                "tags": item.tags,
                "link": item.original_link,
                "source": item.source,
            })

        return json.dumps({
            "board": board_slug,
            "date": summary.date,
            "overview": summary.overview,
            "items_count": len(items),
            "top_news": items,
        }, ensure_ascii=False, indent=2)


@mcp.tool()
async def generate_summary(board_slug: str = "tech") -> str:
    """Trigger generation of today's briefing for a board (if not already generated).

    Args:
        board_slug: Board identifier. Default "tech".

    Returns:
        JSON with the generated summary or an error message.
    """
    await _ensure_db()
    from app.core.db import AsyncSessionLocal
    from app.services.db_service import db_service
    from app.services.source_adapters import get_adapter, UnknownSourceTypeError

    search_date = datetime.now().strftime("%Y-%m-%d")

    async with AsyncSessionLocal() as session:
        boards = await db_service.list_boards(session, active_only=False)
        board = next((b for b in boards if b.slug == board_slug), None)
        if not board:
            return json.dumps({"error": f"Board '{board_slug}' not found."}, ensure_ascii=False)

        # Check if already exists
        existing = await db_service.get_summary_by_date(session, search_date, board_id=board.id)
        if existing:
            return json.dumps({
                "status": "already_exists",
                "message": f"Summary for '{board_slug}' on {search_date} already exists.",
            }, ensure_ascii=False)

        try:
            adapter = get_adapter(board.source_type)
        except UnknownSourceTypeError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

        summary, _ = await adapter.produce(board=board, session=session)
        if summary:
            await db_service.save_summary(session, summary, board_id=board.id)
            return json.dumps({
                "status": "generated",
                "date": summary.date,
                "overview": summary.overview,
                "items_count": len(summary.top_news),
            }, ensure_ascii=False, indent=2)
        else:
            return json.dumps({"error": "Failed to generate summary."}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tools: RAG Q&A
# ---------------------------------------------------------------------------

@mcp.tool()
async def ask_article(question: str, article_url: Optional[str] = None) -> str:
    """Ask a question about a previously ingested article using RAG.

    If article_url is provided, the question is scoped to that article.
    Otherwise, it searches across all ingested content.

    Args:
        question: The question to ask.
        article_url: Optional URL to scope the question to a specific article.

    Returns:
        The AI-generated answer with source citations.
    """
    await _ensure_db()
    from app.services.rag_service import query_stream

    full_answer = ""
    metadata = None
    async for chunk in query_stream(question, article_url=article_url):
        if chunk.startswith("[METADATA]") and chunk.endswith("[/METADATA]"):
            metadata = json.loads(chunk[10:-11])
        else:
            full_answer += chunk

    result = {"answer": full_answer}
    if metadata:
        result["citations"] = metadata.get("citations", [])
        result["chunks_used"] = metadata.get("chunks_used", 0)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tools: Board Management
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_boards() -> str:
    """List all content boards with their configuration.

    Returns:
        JSON array of boards with slug, name, source_type, and status.
    """
    await _ensure_db()
    from app.core.db import AsyncSessionLocal
    from app.services.db_service import db_service

    async with AsyncSessionLocal() as session:
        boards = await db_service.list_boards(session, active_only=False)
        result = []
        for b in boards:
            result.append({
                "slug": b.slug,
                "name": b.name,
                "icon": b.icon,
                "source_type": b.source_type,
                "is_active": b.is_active,
                "schedule": b.schedule or "(global)",
                "description": b.description,
            })
        return json.dumps(result, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tools: News Search
# ---------------------------------------------------------------------------

@mcp.tool()
async def search_news(
    keyword: str,
    board_slug: Optional[str] = None,
    limit: int = 10,
) -> str:
    """Search past news items by keyword in headlines.

    Args:
        keyword: Search term to match against headlines.
        board_slug: Optional board filter.
        limit: Maximum results (default 10, max 50).

    Returns:
        JSON array of matching news items.
    """
    await _ensure_db()
    from app.core.db import AsyncSessionLocal
    from sqlmodel import select
    from app.models.domain import NewsItem, DailySummary, Board

    limit = min(limit, 50)

    async with AsyncSessionLocal() as session:
        stmt = (
            select(NewsItem)
            .where(NewsItem.headline.contains(keyword))
            .order_by(NewsItem.id.desc())
            .limit(limit)
        )

        if board_slug:
            stmt = (
                select(NewsItem)
                .join(DailySummary, NewsItem.summary_id == DailySummary.id)
                .join(Board, DailySummary.board_id == Board.id)
                .where(NewsItem.headline.contains(keyword))
                .where(Board.slug == board_slug)
                .order_by(NewsItem.id.desc())
                .limit(limit)
            )

        result = await session.exec(stmt)
        items = result.all()

        output = []
        for item in items:
            output.append({
                "headline": item.headline,
                "category": item.category,
                "tags": item.tags,
                "link": item.original_link,
                "source": item.source,
            })

        return json.dumps({
            "query": keyword,
            "count": len(output),
            "results": output,
        }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tools: Feedback / Personalization
# ---------------------------------------------------------------------------

@mcp.tool()
async def add_feedback(article_url: str, sentiment: str) -> str:
    """Record user feedback (like/dislike) for an article.

    Args:
        article_url: The article URL to provide feedback on.
        sentiment: Either "like" or "dislike".

    Returns:
        Confirmation message.
    """
    await _ensure_db()
    from app.core.db import AsyncSessionLocal
    from app.services.db_service import db_service

    if sentiment not in ("like", "dislike"):
        return json.dumps({"error": "sentiment must be 'like' or 'dislike'"}, ensure_ascii=False)

    sentiment_val = 1 if sentiment == "like" else -1

    async with AsyncSessionLocal() as session:
        await db_service.save_feedback(session, article_url, sentiment_val)
        return json.dumps({
            "status": "saved",
            "article_url": article_url,
            "sentiment": sentiment,
        }, ensure_ascii=False)


@mcp.tool()
async def get_user_interests(board_slug: Optional[str] = None) -> str:
    """Get the current user persona/interests that guide content personalization.

    Args:
        board_slug: Optional board to scope interests to.

    Returns:
        JSON array of active persona entries.
    """
    await _ensure_db()
    from app.core.db import AsyncSessionLocal
    from app.services.db_service import db_service

    async with AsyncSessionLocal() as session:
        board_id = None
        if board_slug:
            boards = await db_service.list_boards(session, active_only=False)
            board = next((b for b in boards if b.slug == board_slug), None)
            if board:
                board_id = board.id

        personas = await db_service.get_active_personas(session, board_id=board_id)
        result = []
        for p in personas:
            result.append({
                "id": p.id,
                "content": p.content,
                "category": p.category,
                "is_active": p.is_active,
            })
        return json.dumps(result, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tools: System
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_system_status() -> str:
    """Get Argos system status including LLM config, boards count, and metrics.

    Returns:
        JSON with system health information.
    """
    await _ensure_db()
    from app.core.config import settings
    from app.core.db import AsyncSessionLocal
    from app.services.db_service import db_service

    async with AsyncSessionLocal() as session:
        boards = await db_service.list_boards(session, active_only=False)

    return json.dumps({
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "llm_model": settings.LLM_MODEL,
        "llm_base_url": settings.effective_llm_base_url,
        "boards_count": len(boards),
        "active_boards": sum(1 for b in boards if b.is_active),
        "rag_hyde_enabled": settings.RAG_HYDE_ENABLED,
        "notify_channels": settings.NOTIFY_CHANNELS,
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
