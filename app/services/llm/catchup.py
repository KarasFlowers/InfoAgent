"""Catch-up digest generation — condenses multiple days of summaries into one briefing."""
import json
import logging

from app.core.config import settings
from app.models.schemas import DailySummaryResponse
from app.prompts import get_prompt

logger = logging.getLogger(__name__)


def _build_catchup_data(summaries: list[dict]) -> str:
    """Build a dense text representation of multiple days' summaries for the LLM."""
    daily_inputs = []
    for s in summaries:
        date = s.get("date", "Unknown Date")
        overview = s.get("overview", "")
        items_detail = []
        for n in s.get("top_news", []):
            headline = n.get("headline", "")
            key_points = n.get("key_points", [])
            source = n.get("source", "")
            link = n.get("original_link", "")
            items_detail.append(
                f"  - {headline} ({source}) {link}\n    Key: {'; '.join(key_points[:3])}"
            )
        daily_inputs.append(
            f"### {date}\nOverview: {overview}\nItems:\n" + "\n".join(items_detail)
        )
    return "\n\n".join(daily_inputs)


class CatchupMixin:
    """Mixin providing catch-up digest generation for LLMService."""

    async def generate_catchup_digest(
        self,
        summaries: list[dict],
    ) -> DailySummaryResponse | None:
        """
        Generate a condensed catch-up digest from multiple days of summaries.

        Args:
            summaries: List of DailySummaryResponse.model_dump() dicts.

        Returns:
            A DailySummaryResponse representing the condensed digest, or None.
        """
        if not settings.effective_llm_api_key:
            return None

        if not summaries:
            logger.info("No summaries provided for catch-up digest.")
            return None

        catchup_data = _build_catchup_data(summaries)
        prompt = get_prompt("catchup_digest")

        # Derive a representative date (latest date in the set)
        dates = sorted(s.get("date", "") for s in summaries)
        date_hint = dates[-1] if dates else ""

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": f"Here are the summaries from the past {len(summaries)} days:\n\n{catchup_data}",
                    },
                ],
                tier="smart",
                label="catchup_digest",
                temperature=0.5,
                max_tokens=3000,
            )
            raw = response.choices[0].message.content.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw.rsplit("```", 1)[0]
            raw = raw.strip()

            parsed = json.loads(raw)
            # Ensure the date field reflects the digest, not a single day
            if date_hint:
                parsed["date"] = date_hint
            return DailySummaryResponse(**parsed)

        except Exception as error:
            logger.error("Error during catch-up digest generation: %s", error)
            return None
