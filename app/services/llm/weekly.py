"""Weekly consolidation / recap generation."""
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

WIRED_EDITOR_PROMPT = """
You are a Senior Editor at WIRED Magazine. You specialize in identifying the deep tech-cultural shifts and industry power moves. 
I will provide you with a list of daily overviews and key headlines from the past 7 days.

Your goal is to write a "Weekly Deep Insight" — a long-form, magazine-style synthesis that tells the story of the week.

Guidelines:
1. Tone: Tech-forward, provocative, sharp, and narrative-driven. Use strong verbs and bold assertions.
2. Structure:
   - A catchy, bold headline.
   - The "Lead": A powerful opening paragraph setting the scene for the week.
   - "The Power Moves": A section summarizing the most critical industry shifts or technical breakthroughs.
   - "The Cultural Ripple": How these tech changes affect society or the industry landscape.
   - "The Bottom Line": A forward-looking closing statement on what this means for next week.
3. Formatting: Use Markdown. Use bolding for emphasis. Keep paragraphs punchy.
4. Output: Return ONLY the Markdown content. Do not include JSON wrappers or code fences unless asked.
"""


class WeeklyMixin:
    """Mixin providing ``generate_weekly_consolidation`` for LLMService."""

    async def generate_weekly_consolidation(
        self,
        summaries: list[dict],
    ) -> str | None:
        """
        Synthesize multiple daily summaries into a long-form magazine style recap.
        """
        if not settings.effective_llm_api_key:
            return None

        # Build a dense representation for the week
        daily_inputs = []
        for i, s in enumerate(summaries):
            date = s.get("date", "Unknown Date")
            overview = s.get("overview", "")
            headlines = [n.get("headline", "") for n in s.get("top_news", [])]
            daily_inputs.append(f"### {date}\nOverview: {overview}\nHeadlines: {', '.join(headlines)}")

        week_data = "\n\n".join(daily_inputs)

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": WIRED_EDITOR_PROMPT},
                    {
                        "role": "user",
                        "content": f"Here is the data from the past 7 days:\n\n{week_data}",
                    },
                ],
                temperature=0.7,
                max_tokens=2500,
            )

            return response.choices[0].message.content
        except Exception as error:
            logger.error("Error during weekly consolidation: %s", error)
            return None
