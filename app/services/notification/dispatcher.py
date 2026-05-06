"""
Unified notification dispatcher.

Routes a ``DailySummaryResponse`` to all enabled notification channels.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:
    from app.models.schemas import DailySummaryResponse

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """Fan-out notifications to configured channels."""

    def _get_enabled_channels(self, override: list[str] | None = None) -> list[str]:
        """Determine which channels to use.

        Priority:
        1. Explicit override (e.g. from board.notify_channels)
        2. Global NOTIFY_CHANNELS setting
        """
        if override:
            return [ch.strip().lower() for ch in override if ch.strip()]
        raw = settings.NOTIFY_CHANNELS or "email"
        return [ch.strip().lower() for ch in raw.split(",") if ch.strip()]

    async def send(
        self,
        summary: "DailySummaryResponse",
        channels: list[str] | None = None,
    ) -> dict[str, bool]:
        """Dispatch summary to all enabled channels.

        Args:
            summary: The daily summary to push.
            channels: Optional override list of channel names.

        Returns:
            Dict mapping channel name -> success boolean.
        """
        enabled = self._get_enabled_channels(channels)
        results: dict[str, bool] = {}

        for channel in enabled:
            try:
                ok = await self._dispatch_one(channel, summary)
                results[channel] = ok
            except Exception as e:
                logger.error("Channel '%s' raised unexpected error: %s", channel, e)
                results[channel] = False

        successes = sum(1 for v in results.values() if v)
        logger.info(
            "Notification dispatch: %d/%d channels succeeded %s",
            successes, len(results), results,
        )
        return results

    async def _dispatch_one(
        self, channel: str, summary: "DailySummaryResponse"
    ) -> bool:
        if channel == "email":
            from app.services.email_service import email_service
            return await email_service.send_daily_summary(summary)
        elif channel == "webhook":
            from app.services.notification.channels import send_webhook
            return await send_webhook(summary)
        elif channel == "bark":
            from app.services.notification.channels import send_bark
            return await send_bark(summary)
        elif channel == "telegram":
            from app.services.notification.channels import send_telegram
            return await send_telegram(summary)
        else:
            logger.warning("Unknown notification channel: '%s'", channel)
            return False
