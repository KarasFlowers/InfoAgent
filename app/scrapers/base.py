"""Base scraper interface."""

from abc import ABC, abstractmethod
from datetime import datetime

import httpx

from app.models.schemas import ContentItem


class BaseScraper(ABC):
    """Abstract base class for all scrapers."""

    def __init__(self, config: dict, http_client: httpx.AsyncClient):
        self.config = config
        self.client = http_client

    @abstractmethod
    async def fetch(self, since: datetime) -> list[ContentItem]:
        """Fetch content items published since the given time."""
        ...

    @staticmethod
    def _generate_id(source_type: str, subtype: str, native_id: str) -> str:
        return f"{source_type}:{subtype}:{native_id}"
