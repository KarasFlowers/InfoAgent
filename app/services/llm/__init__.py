"""
LLM service sub-package.

The ``LLMService`` class is assembled here from mixin classes defined
in sibling modules.  The singleton ``llm_service`` is the public entry
point — all existing imports of ``from app.services.llm_service import
llm_service`` continue to work through the facade in ``../llm_service.py``.
"""
import logging

from openai import AsyncOpenAI

from app.core.config import settings
from app.services.llm.scoring import ScoringMixin
from app.services.llm.summary import SummaryMixin
from app.services.llm.weekly import WeeklyMixin
from app.services.llm.wizard import WizardMixin

logger = logging.getLogger(__name__)


class LLMService(ScoringMixin, SummaryMixin, WeeklyMixin, WizardMixin):
    def __init__(self) -> None:
        if not settings.DEEPSEEK_API_KEY:
            logger.warning("DEEPSEEK_API_KEY is not set. LLM features will fail.")
        self.client = AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            timeout=180.0,
            max_retries=1,
        )


llm_service = LLMService()

__all__ = ["LLMService", "llm_service"]
