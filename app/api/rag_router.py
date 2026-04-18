"""
RAG API Router

Endpoints:
  POST /api/v1/rag/ingest  - scrape and index a URL into the vector store
  POST /api/v1/rag/query   - run the RAG pipeline and stream the answer via SSE
"""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import AnyHttpUrl, BaseModel, Field, field_validator

from app.core.url_safety import validate_public_url
from app.services.chat_history_service import get_chat_history
from app.services.learning_service import record_feedback
from app.services.rag_service import _ingested_urls, _prepare_overview_context, ingest, query_stream, stream_article_overview

logger = logging.getLogger(__name__)
rag_router = APIRouter(prefix="/rag", tags=["RAG"])



def _format_sse_data(message: str) -> str:
    normalized = message.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(
        f"data: {line}\n" if line else "data:\n"
        for line in normalized.split("\n")
    ) + "\n"


def _validate_public_url(value: AnyHttpUrl) -> AnyHttpUrl:
    return validate_public_url(value)


class PublicUrlRequest(BaseModel):
    url: AnyHttpUrl

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        return _validate_public_url(value)


class IngestRequest(PublicUrlRequest):
    pass


class QueryRequest(PublicUrlRequest):
    question: str = Field(min_length=1)


class FeedbackRequest(PublicUrlRequest):
    sentiment: Literal[1, -1, 0]


@rag_router.post("/ingest")
async def ingest_article(req: IngestRequest):
    """
    Scrape the given URL and store its chunks + embeddings in the vector DB.
    Returns the number of chunks stored.
    """
    url = str(req.url)

    try:
        result = await ingest(url)
        chunk_count = result["chunks"]
        quality = result["quality"]
        if chunk_count == 0:
            raise HTTPException(status_code=422, detail="Could not extract text from the URL.")
        return {"status": "ok", "chunks": chunk_count, "quality": quality}
    except HTTPException:
        raise
    except ValueError as exc:
        detail = str(exc)
        if "private network" in detail or "blocklist" in detail:
            raise HTTPException(status_code=422, detail=f"安全预检失败：{detail}")
        raise HTTPException(status_code=422, detail=f"内容提取失败：{detail}")
    except Exception:
        logger.exception("Failed to ingest article: %s", url)
        raise HTTPException(status_code=500, detail="Failed to ingest article.")


@rag_router.post("/overview")
async def fetch_article_overview(req: PublicUrlRequest):
    """Generate a richer overview for the article before interactive questioning."""
    url = str(req.url)

    async def event_generator():
        async for token in stream_article_overview(url):
            yield _format_sse_data(token)
        yield _format_sse_data("[DONE]")

    try:
        await _prepare_overview_context(url)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    except ValueError as exc:
        detail = str(exc)
        if "private network" in detail or "blocklist" in detail:
            raise HTTPException(status_code=422, detail=f"安全预检失败：{detail}")
        raise HTTPException(status_code=422, detail=f"概要提取失败：{detail}")
    except Exception:
        logger.exception("Failed to generate article overview for %s", url)
        raise HTTPException(status_code=500, detail="Failed to generate article overview.")


@rag_router.post("/query")
async def query_article(req: QueryRequest):
    """
    Run the two-stage RAG pipeline (Bi-Encoder recall -> Cross-Encoder rerank -> DeepSeek stream).
    Returns an SSE stream of text tokens.
    """
    url = str(req.url)

    if url not in _ingested_urls:
        raise HTTPException(
            status_code=400,
            detail="This URL has not been ingested yet. Please call /ingest first.",
        )

    async def event_generator():
        async for token in query_stream(req.question, url):
            yield _format_sse_data(token)
        yield _format_sse_data("[DONE]")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@rag_router.get("/history")
async def fetch_chat_history(url: AnyHttpUrl = Query(...)):
    """
    Retrieve existing chat history for a URL.
    """
    try:
        public_url = str(_validate_public_url(url))
        history = await get_chat_history(public_url)
        return {
            "status": "ok",
            "history": [
                {
                    "role": "ai" if m.role == "assistant" else m.role,
                    "content": m.content,
                    "timestamp": m.timestamp.isoformat(),
                }
                for m in history
            ],
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        logger.exception("Failed to fetch chat history for %s", url)
        raise HTTPException(status_code=500, detail="Failed to fetch chat history.")


@rag_router.post("/feedback")
async def submit_feedback(req: FeedbackRequest):
    """
    Record explicit user feedback (Like/Dislike) for an article.
    This builds the user's semantic profile for personalized reranking.
    """
    url = str(req.url)

    try:
        await record_feedback(url, req.sentiment)
        return {"status": "ok", "message": "Feedback recorded successfully."}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        logger.exception("Failed to record feedback for %s", url)
        raise HTTPException(status_code=500, detail="Failed to record feedback.")
