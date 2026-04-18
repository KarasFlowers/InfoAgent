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
from app.core.db import engine


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

    async with AsyncSession(engine) as session:
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
    for link, headline, key_points_json in rows:
        try:
            kp_list = json.loads(key_points_json)
            kp_text = " ".join(kp_list) if isinstance(kp_list, list) else str(kp_list)
        except (json.JSONDecodeError, TypeError):
            kp_text = str(key_points_json)
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
    async with AsyncSession(engine) as session:
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
            item_tags = json.loads(tags_json)
            for t in item_tags:
                tags[t] = tags.get(t, 0) + 1
        except:
            continue
            
    # Sort and pick top
    sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)
    sorted_tags = sorted(tags.items(), key=lambda x: x[1], reverse=True)
    
    results = []
    for name, count in sorted_cats[:limit]:
        results.append({"name": name, "count": count, "type": "category"})
    for name, count in sorted_tags[:limit]:
        results.append({"name": name, "count": count, "type": "tag"})
        
    return results


async def rerank_summary_items(items: list) -> list:
    """
    Rerank SummaryItem list by user preference vectors.

    For each item, computes:
        persona_score = cos_sim(positive_centroid, item_emb) * 0.7
                      - cos_sim(negative_centroid, item_emb) * 0.3

    Returns items sorted by persona_score descending.
    If no feedback data exists, returns original order with no scores.
    """
    positive_centroid, negative_centroid = await get_user_feedback_profiles()

    if positive_centroid is None and negative_centroid is None:
        return items

    if not items:
        return items

    from app.services.rag_service import get_bi_encoder
    bi_encoder = get_bi_encoder()

    # Build text representations for embedding
    texts = []
    for item in items:
        kp_text = " ".join(item.key_points) if item.key_points else ""
        texts.append(f"{item.headline} {kp_text}")

    embeddings = bi_encoder.encode(texts)

    scored_items = []
    for i, item in enumerate(items):
        emb = _normalize_vector(embeddings[i])
        score = 0.0

        if positive_centroid is not None:
            score += float(np.dot(positive_centroid, emb)) * 0.7
        if negative_centroid is not None:
            score -= float(np.dot(negative_centroid, emb)) * 0.3

        item.persona_score = round(score, 3)
        scored_items.append(item)

    scored_items.sort(key=lambda x: x.persona_score or 0, reverse=True)
    return scored_items
