"""
Base class for board source adapters.
"""
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.models.domain import Board
    from app.models.schemas import DailySummaryResponse


class UnknownSourceTypeError(ValueError):
    """Raised when a board specifies a source_type with no registered adapter."""


class SourceAdapter(ABC):
    """
    Strategy interface for content producers.

    Each concrete adapter reads the board's configuration and produces a
    ``DailySummaryResponse`` for the current day (or None when nothing can
    be produced).
    """

    source_type: str = ""  # subclasses should set this

    @abstractmethod
    async def produce(
        self,
        board: "Board",
        session: AsyncSession,
        one_time_preference: str | None = None,
    ) -> "DailySummaryResponse | None":
        """Produce today's summary for this board."""
        raise NotImplementedError
