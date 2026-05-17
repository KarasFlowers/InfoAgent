"""
Learning Service: Explicit Semantic Feedback & Profile Generation

This service manages the user's semantic profile based on Like/Dislike feedback.
Pipeline:
  1. User clicks 👍 or 👎 on an article.
  2. The feedback (sentiment) is explicitly saved to the database.
  3. When RAG reranks, it asks this service for user preference centroids.
  4. Positive and negative centroids are calculated dynamically from feedback history.
  5. Centroids are computed from ARTICLE CONTENT (headline + key_points), not URLs.
"""

import json
import numpy as np
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import UserFeedback, NewsItem
from app.core.db import AsyncSessionLocal


def _normalize_vector(vector: np.ndarray) -> np.ndarray:
    """Normalize a vector for cosine similarity use."""
    norm = np.linalg.norm(vector)
    if norm > 0:
        return vector / norm
    return vector


async def record_feedback(url: str, sentiment: int) -> bool:
    """
    Record, update, or clear explicit feedback for a given article URL.
    Sentiment values: 1 = like, -1 = dislike, 0 = clear.
    """
    if sentiment not in (1, -1, 0):
        raise ValueError("Sentiment must be 1 (Like), -1 (Dislike), or 0 (Clear).")

    async with AsyncSessionLocal() as session:
        statement = select(UserFeedback).where(UserFeedback.article_url == url)
        result = await session.execute(statement)
        existing_rows = result.scalars().all()
        existing = existing_rows[0] if existing_rows else None

        if len(existing_rows) > 1:
            for duplicate in existing_rows[1:]:
                await session.delete(duplicate)

        if sentiment == 0:
            if existing:
                await session.delete(existing)
        elif existing:
            existing.sentiment = sentiment
        else:
            feedback = UserFeedback(article_url=url, sentiment=sentiment)
            session.add(feedback)

        await session.commit()
        return True


async def _get_article_text_for_urls(session: AsyncSession, urls: list[str]) -> list[str]:
    """
    Look up NewsItem entries by original_link to build rich text representations.
    Falls back to URL-derived text if no DB match is found.
    """
    if not urls:
        return []

    statement = select(NewsItem.original_link, NewsItem.headline, NewsItem.key_points).where(
        NewsItem.original_link.in_(urls)
    )
    result = await session.execute(statement)
    rows = result.all()

    # Build a mapping: url -> rich text
    url_to_text = {}
    for link, headline, key_points_raw in rows:
        # key_points is a native JSON column — SQLAlchemy returns a Python list directly.
        # Handle str fallback for legacy rows that may not have been migrated yet.
        if isinstance(key_points_raw, list):
            kp_text = " ".join(key_points_raw)
        elif isinstance(key_points_raw, str):
            try:
                kp_list = json.loads(key_points_raw)
                kp_text = " ".join(kp_list) if isinstance(kp_list, list) else key_points_raw
            except (json.JSONDecodeError, TypeError):
                kp_text = key_points_raw
        else:
            kp_text = str(key_points_raw) if key_points_raw else ""
        url_to_text[link] = f"{headline} {kp_text}"

    # For each URL, use DB content if available, otherwise fallback
    texts = []
    for url in urls:
        if url in url_to_text:
            texts.append(url_to_text[url])
        else:
            # Fallback: derive minimal text from URL
            texts.append(url.replace("-", " ").replace("/", " "))
    return texts


async def get_user_feedback_profiles() -> tuple[np.ndarray | None, np.ndarray | None]:
    """
    Compute positive/negative preference centroids from explicit feedback.
    Uses article headline + key_points for semantically rich embeddings.

    Returns:
        (positive_centroid, negative_centroid), each can be None.
    """
    async with AsyncSessionLocal() as session:
        statement = select(UserFeedback.article_url, UserFeedback.sentiment)
        result = await session.execute(statement)
        rows = result.all()

        if not rows:
            return None, None

        liked_urls = [url for url, sentiment in rows if sentiment == 1]
        disliked_urls = [url for url, sentiment in rows if sentiment == -1]

        # Fetch rich article content from DB
        liked_texts = await _get_article_text_for_urls(session, liked_urls)
        disliked_texts = await _get_article_text_for_urls(session, disliked_urls)

    from app.services.rag_service import get_bi_encoder
    bi_encoder = get_bi_encoder()

    positive_centroid: np.ndarray | None = None
    negative_centroid: np.ndarray | None = None

    if liked_texts:
        liked_embeddings = bi_encoder.encode(liked_texts)
        if len(liked_embeddings) > 0:
            positive_centroid = _normalize_vector(np.mean(liked_embeddings, axis=0))

    if disliked_texts:
        disliked_embeddings = bi_encoder.encode(disliked_texts)
        if len(disliked_embeddings) > 0:
            negative_centroid = _normalize_vector(np.mean(disliked_embeddings, axis=0))

    return positive_centroid, negative_centroid


async def get_user_centroid() -> np.ndarray | None:
    """
    Compute the semantic centroid representing the user's current interests.
    Backward-compatible helper that returns only the positive centroid.
    """
    positive_centroid, _ = await get_user_feedback_profiles()
    return positive_centroid


async def get_inferred_interests(session: AsyncSession, limit: int = 5) -> list[dict]:
    """
    Analyze liked articles to find the most frequent categories and tags.
    Returns a list of {name: str, count: int, type: "category"|"tag"}.
    """
    # 1. Get all liked article URLs
    stmt = select(UserFeedback.article_url).where(UserFeedback.sentiment == 1)
    res = await session.execute(stmt)
    liked_urls = res.scalars().all()
    
    if not liked_urls:
        return []
        
    # 2. Fetch tags and categories for these URLs
    stmt = select(NewsItem.category, NewsItem.tags).where(NewsItem.original_link.in_(liked_urls))
    res = await session.execute(stmt)
    rows = res.all()
    
    categories = {}
    tags = {}
    
    for cat, tags_json in rows:
        if cat:
            categories[cat] = categories.get(cat, 0) + 1
        
        try:
            item_tags = json.loads(tags_json) if tags_json else []
        except (json.JSONDecodeError, TypeError):
            continue
        for t in item_tags:
            tags[t] = tags.get(t, 0) + 1
            
    # Sort and pick top
    sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)
    sorted_tags = sorted(tags.items(), key=lambda x: x[1], reverse=True)
    
    results = []
    for name, count in sorted_cats[:limit]:
        results.append({"name": name, "count": count, "type": "category"})
    for name, count in sorted_tags[:limit]:
        results.append({"name": name, "count": count, "type": "tag"})
        
    return results


async def rerank_summary_items(items: list, session: AsyncSession | None = None) -> list:
    """
    Rerank SummaryItem list by:
      1. Explicit preferences (focus/block topics, prefer/avoid sources)
      2. User preference vectors (like/dislike feedback)

    Blocked topics are completely removed from the list.
    Focus topics receive a +0.3 bonus; avoided sources get a -0.2 penalty.

    Returns items sorted by persona_score descending.
    If no feedback or preferences exist, returns original order.
    """
    if not items:
        return items

    # --- Phase 1: Explicit preferences ---
    prefs: dict[str, list[str]] = {
        "focus_topic": [], "block_topic": [],
        "prefer_source": [], "avoid_source": [],
    }

    if session:
        try:
            from app.services.db_service import db_service
            prefs = await db_service.get_explicit_preferences(session)
        except Exception:
            pass

    block_topics_lower = {t.lower() for t in prefs["block_topic"]}
    focus_topics_lower = {t.lower() for t in prefs["focus_topic"]}
    prefer_sources_lower = {s.lower() for s in prefs["prefer_source"]}
    avoid_sources_lower = {s.lower() for s in prefs["avoid_source"]}

    # Filter out blocked items
    if block_topics_lower:
        filtered = []
        for item in items:
            item_cat = (item.category or "").lower()
            item_tags = {(t.lstrip("#").strip()).lower() for t in (item.tags or [])}
            item_signals = item_tags | {item_cat}
            if item_signals & block_topics_lower:
                continue
            filtered.append(item)
        items = filtered

    # --- Phase 2: Embedding-based reranking ---
    positive_centroid, negative_centroid = await get_user_feedback_profiles()

    has_vectors = positive_centroid is not None or negative_centroid is not None
    has_prefs = any(prefs[k] for k in prefs)

    if not has_vectors and not has_prefs:
        return items

    embeddings = None
    if has_vectors:
        from app.services.rag_service import get_bi_encoder
        bi_encoder = get_bi_encoder()

        texts = []
        for item in items:
            kp_text = " ".join(item.key_points) if item.key_points else ""
            texts.append(f"{item.headline} {kp_text}")

        embeddings = bi_encoder.encode(texts)

    scored_items = []
    for i, item in enumerate(items):
        score = 0.0

        # Vector-based score
        if has_vectors:
            emb = _normalize_vector(embeddings[i])
            if positive_centroid is not None:
                score += float(np.dot(positive_centroid, emb)) * 0.7
            if negative_centroid is not None:
                score -= float(np.dot(negative_centroid, emb)) * 0.3

        # Explicit preference adjustments
        item_cat = (item.category or "").lower()
        item_tags = {(t.lstrip("#").strip()).lower() for t in (item.tags or [])}
        item_signals = item_tags | {item_cat}
        item_source = (item.source or "").lower()

        if item_signals & focus_topics_lower:
            score += 0.3
        if item_source in prefer_sources_lower:
            score += 0.15
        if item_source in avoid_sources_lower:
            score -= 0.2

        item.persona_score = round(score, 3)
        scored_items.append(item)

    scored_items.sort(key=lambda x: x.persona_score or 0, reverse=True)
    return scored_items
