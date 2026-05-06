"""
Individual notification channel implementations.

Each channel is a simple async function that accepts a ``DailySummaryResponse``
and sends it via the appropriate transport.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import TYPE_CHECKING

import httpx

from app.core.config import settings

if TYPE_CHECKING:
    from app.models.schemas import DailySummaryResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Webhook (generic HTTP POST)
# ---------------------------------------------------------------------------

async def send_webhook(summary: DailySummaryResponse) -> bool:
    """POST a JSON payload to the configured webhook URL.

    The payload structure follows a common bot-friendly format:
    {
        "event": "daily_summary",
        "date": "YYYY-MM-DD",
        "overview": "...",
        "items_count": N,
        "items": [{"headline": ..., "category": ..., "link": ...}, ...]
    }

    If ``WEBHOOK_SECRET`` is set, an ``X-Signature-256`` header is included
    (HMAC-SHA256 of the raw JSON body).
    """
    if not settings.WEBHOOK_URL:
        return False

    payload = _build_payload(summary)
    body = json.dumps(payload, ensure_ascii=False)
    headers = {"Content-Type": "application/json"}

    if settings.WEBHOOK_SECRET:
        sig = hmac.new(
            settings.WEBHOOK_SECRET.encode(),
            body.encode(),
            hashlib.sha256,
        ).hexdigest()  # type: ignore[attr-defined]
        headers["X-Signature-256"] = f"sha256={sig}"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(settings.WEBHOOK_URL, content=body, headers=headers)
            resp.raise_for_status()
        logger.info("Webhook sent successfully to %s", settings.WEBHOOK_URL)
        return True
    except Exception as e:
        logger.error("Webhook send failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Bark (iOS)
# ---------------------------------------------------------------------------

async def send_bark(summary: DailySummaryResponse) -> bool:
    """Push notification via Bark (iOS app).

    Bark API: GET/POST https://api.day.app/{key}/{title}/{body}
    We use POST JSON for richer control.
    """
    if not settings.BARK_URL:
        return False

    title = f"InfoAgent 日报 - {summary.date}"
    # Bark body: short overview + first 3 headlines
    headlines = [item.headline for item in summary.top_news[:3]]
    body = summary.overview + "\n\n" + "\n".join(f"• {h}" for h in headlines)
    if len(summary.top_news) > 3:
        body += f"\n… 共 {len(summary.top_news)} 条"

    payload = {
        "title": title,
        "body": body,
        "group": settings.BARK_GROUP,
        "url": "http://127.0.0.1:8000",  # deeplink to dashboard
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(settings.BARK_URL, json=payload)
            resp.raise_for_status()
        logger.info("Bark push sent successfully")
        return True
    except Exception as e:
        logger.error("Bark push failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Telegram Bot
# ---------------------------------------------------------------------------

async def send_telegram(summary: DailySummaryResponse) -> bool:
    """Send summary as a Telegram message via Bot API."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return False

    # Build markdown message
    lines = [f"*InfoAgent 日报 — {summary.date}*\n"]
    lines.append(f"_{summary.overview}_\n")
    for item in summary.top_news[:8]:
        link = item.original_link or ""
        if link.startswith("llm://"):
            lines.append(f"• *{item.headline}*")
        else:
            lines.append(f"• [{item.headline}]({link})")
    if len(summary.top_news) > 8:
        lines.append(f"\n_… 共 {len(summary.top_news)} 条_")

    text = "\n".join(lines)

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        logger.info("Telegram message sent successfully")
        return True
    except Exception as e:
        logger.error("Telegram send failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_payload(summary: DailySummaryResponse) -> dict:
    """Build a universal JSON payload for webhook consumers."""
    items = []
    for item in summary.top_news:
        items.append({
            "headline": item.headline,
            "category": item.category,
            "tags": item.tags,
            "link": item.original_link,
            "source": item.source,
        })
    return {
        "event": "daily_summary",
        "date": summary.date,
        "overview": summary.overview,
        "items_count": len(items),
        "items": items,
    }
