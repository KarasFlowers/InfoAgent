"""
Notification sub-package.

Provides a pluggable multi-channel notification system:
- Email (SMTP)
- Webhook (generic HTTP POST with optional HMAC)
- Bark (iOS push)
- Telegram Bot

Usage:
    from app.services.notification import notify_service
    await notify_service.send(summary, channels=["email", "bark"])
"""

from app.services.notification.dispatcher import NotificationDispatcher

notify_service = NotificationDispatcher()

__all__ = ["NotificationDispatcher", "notify_service"]
