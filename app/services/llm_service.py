import json
import logging
from datetime import datetime

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.schemas import DailySummaryResponse, RSSResponse
from app.services.db_service import db_service

logger = logging.getLogger(__name__)

EDITOR_PROMPT = """
You are the Chief Editor of "InfoAgent", a highly intelligent AI assistant that curates a daily briefing of technology, AI, and interesting internet news for a busy computer science student.

I will provide you with a raw list of articles scraped from various RSS feeds today.
Your goal is to read through all these articles and create a clean, highly readable, and structured daily summary.

Guidelines:
1. Filter out noise: Ignore completely irrelevant articles, spam, or low-quality content. Focus on technology, AI trends, programming, and major industry news.
2. Structure: Provide a high-level "overview" of today's vibe, followed by a list of "top_news".
3. Categorization: For each news item, provide a broad "category" (e.g. "AI", "Mobile", "Software", "Cybersecurity", "Big Tech", "Hardware").
4. Auto-Tagging: For each news item, generate 1 to 3 relevant hashtags that categorize the content.
5. Output format: You MUST output valid JSON matching the exact schema requested. Do not include markdown code fences.

Input JSON schema:
[
  {
    "title": "Article Title",
    "summary": "Short snippet...",
    "link": "URL",
    "source": "RSS Feed Name"
  }
]

Output JSON schema must strictly match:
{
  "date": "YYYY-MM-DD",
  "overview": "A 2-3 sentence engaging summary of today's most important themes.",
  "top_news": [
    {
      "headline": "Clear, standalone headline for the news item",
      "category": "Broad category name",
      "key_points": ["Point 1 explaining why it matters", "Point 2 with details"],
      "tags": ["#Tag1", "#Tag2"],
      "original_link": "the primary URL from the input",
      "source": "the 'source' value from the input article"
    }
  ]
}
"""

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


class LLMService:
    def __init__(self):
        if not settings.DEEPSEEK_API_KEY:
            logger.warning("DEEPSEEK_API_KEY is not set. LLM features will fail.")

        self.client = AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
        )

    async def _score_articles(self, articles: list[dict]) -> tuple[list[dict], dict]:
        """
        Pre-filter: ask the LLM to score each article's value (1-10).
        Returns (high_quality_articles, stats_metadata).
        """
        quality_threshold = 7

        scoring_prompt = """You are a news quality evaluator for a tech-focused daily briefing aimed at a CS student.

For each article below, score its VALUE from 1-10 based on:
- Relevance to tech, AI, programming, industry news (high = good)
- Uniqueness / newsworthiness (not just a press release or ad)
- Educational or discussion value

Output ONLY a valid JSON object with a top-level \"scores\" array.
Example:
{
  \"scores\": [{\"index\": 0, \"score\": 8}, {\"index\": 1, \"score\": 3}]
}
Do NOT include any other text."""

        input_for_scoring = json.dumps(
            [{"index": i, "title": a["title"], "summary": a["summary"][:150]} for i, a in enumerate(articles)],
            ensure_ascii=False,
        )

        try:
            response = await self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": scoring_prompt},
                    {"role": "user", "content": input_for_scoring},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=2000,
            )

            result = response.choices[0].message.content
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                scores = parsed.get("scores", parsed.get("articles", []))
            elif isinstance(parsed, list):
                scores = parsed
            else:
                scores = []

            high_quality_indices = {
                item["index"]
                for item in scores
                if isinstance(item, dict) and item.get("score", 0) >= quality_threshold
            }
            
            filtered = [article for i, article in enumerate(articles) if i in high_quality_indices]
            excluded = [article for i, article in enumerate(articles) if i not in high_quality_indices]

            logger.info(
                "Quality filter: %s/%s articles passed (threshold=%s)",
                len(filtered),
                len(articles),
                quality_threshold,
            )

            # Build report metadata
            report = {
                "total_fetched": len(articles),
                "passed_count": len(filtered),
                "excluded_count": len(excluded),
                "excluded_samples": [a["title"] for a in excluded[:5]]  # Just a few samples
            }

            if len(filtered) < 3 and len(articles) >= 3:
                sorted_scores = sorted(scores, key=lambda item: item.get("score", 0), reverse=True)
                top_indices = {item["index"] for item in sorted_scores[:5]}
                filtered = [article for i, article in enumerate(articles) if i in top_indices]
                logger.info("Fallback: kept top %s articles by score", len(filtered))

            return filtered if filtered else articles[:10], report
        except Exception as error:
            logger.warning("Article scoring failed, using all articles: %s", error)
            return articles, {"total_fetched": len(articles), "error": str(error)}

    async def generate_daily_summary(
        self,
        rss_responses: list[RSSResponse],
        session: AsyncSession | None = None,
        one_time_preference: str | None = None,
    ) -> DailySummaryResponse | None:
        """
        Score the raw RSS data, filter out noise, and generate a structured summary.
        Persona instructions are included when available.
        """
        if not settings.DEEPSEEK_API_KEY:
            logger.error("Attempted to call LLM without API key configured.")
            return None

        persona_context = ""
        if session:
            try:
                personas = await db_service.get_active_personas(session)
                if personas:
                    persona_lines = []
                    for persona in personas:
                        marker = "[Instruction]" if persona.category == "instruction" else "[Derived Interest]"
                        persona_lines.append(f"- {marker} {persona.content}")
                    persona_context = (
                        "\n\nUSER PERSONALITY & PREFERENCE GUIDELINES:\n"
                        + "\n".join(persona_lines)
                        + "\nStrictly adhere to these preferences while selecting and summarizing."
                    )
            except Exception as error:
                logger.warning("Failed to fetch user persona: %s", error)

        if one_time_preference:
            if not persona_context:
                persona_context = "\n\nUSER PERSONALITY & PREFERENCE GUIDELINES:\n"
            persona_context += f"- [Today Only] {one_time_preference}\n"

        raw_articles = []
        for feed in rss_responses:
            for item in feed.items:
                raw_articles.append(
                    {
                        "title": item.title,
                        "summary": item.summary[:300],
                        "link": item.link,
                        "source": item.source,
                    }
                )

        limited_articles = raw_articles[:50]
        if not limited_articles:
            logger.info("No articles to summarize.")
            return None

        logger.info("Starting quality scoring for %s articles...", len(limited_articles))
        high_quality, rec_report = await self._score_articles(limited_articles)
        logger.info("Proceeding with %s high-quality articles for summarization.", len(high_quality))

        input_json = json.dumps(high_quality, ensure_ascii=False)

        try:
            response = await self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": EDITOR_PROMPT + persona_context},
                    {
                        "role": "user",
                        "content": f"Today's Date: {datetime.now().strftime('%Y-%m-%d')}\n\nHere are the articles:\n{input_json}",
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=4000,
            )

            parsed_json = json.loads(response.choices[0].message.content)
            top_news = parsed_json.get("top_news", [])
            stats = {}
            for item in top_news:
                source = item.get("source", "未知来源")
                stats[source] = stats.get(source, 0) + 1
            parsed_json["source_stats"] = stats
            
            # Map the recommendation metrics back to the response
            # We add specifically which ones were 'recommended' in final stage
            final_headlines = [n.get("headline") for n in top_news]
            rec_report["final_recommended_count"] = len(top_news)
            parsed_json["recommendation_report"] = rec_report

            return DailySummaryResponse(**parsed_json)
        except Exception as error:
            logger.error("Error during LLM summarization: %s", error)
            return None


    async def generate_weekly_consolidation(
        self,
        summaries: list[dict],
    ) -> str | None:
        """
        Synthesize multiple daily summaries into a long-form magazine style recap.
        """
        if not settings.DEEPSEEK_API_KEY:
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
            response = await self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": WIRED_EDITOR_PROMPT},
                    {
                        "role": "user",
                        "content": f"Here is the data from the past 7 days:\n\n{week_data}",
                    },
                ],
                temperature=0.7,  # Higher temperature for better creative writing
                max_tokens=2500,
            )

            return response.choices[0].message.content
        except Exception as error:
            logger.error("Error during weekly consolidation: %s", error)
            return None


llm_service = LLMService()
