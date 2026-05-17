"""Daily summary generation (RSS-based and pure-LLM)."""
import json
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.schemas import ContentItem, DailySummaryResponse, RSSResponse
from app.services.db_service import db_service

logger = logging.getLogger(__name__)

EDITOR_PROMPT = """
You are the Chief Editor of "Argos", a highly intelligent AI assistant that curates a daily briefing of technology, AI, and interesting internet news for a busy computer science student.

I will provide you with a raw list of articles scraped from various RSS feeds today.
Your goal is to read through all these articles and create a clean, highly readable, and structured daily summary.

Guidelines:
1. Filter out noise: Ignore completely irrelevant articles, spam, or low-quality content. Focus on technology, AI trends, programming, and major industry news.
2. Structure: Provide a high-level "overview" of today's vibe, followed by a list of "top_news".
3. Categorization: For each news item, provide a broad "category" (e.g. "AI", "Mobile", "Software", "Cybersecurity", "Big Tech", "Hardware").
4. Auto-Tagging: For each news item, generate 1 to 3 relevant hashtags that categorize the content.
5. Output format: You MUST output valid JSON matching the exact schema requested. Do not include markdown code fences.
6. Article count: Include AT LEAST 8 articles in "top_news" (or all high-quality articles if fewer than 8 are available). Aim for 8-12 items to give the reader a comprehensive view of the day.
7. Diversity: Ensure variety across categories and sources. Do NOT over-represent a single topic even if the user has expressed interest in it. User preferences should guide priority, NOT exclusivity — still cover other important news.

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


class SummaryMixin:
    """Mixin providing daily summary generation for LLMService."""

    async def generate_daily_summary(
        self,
        rss_responses: list[RSSResponse],
        session: AsyncSession | None = None,
        one_time_preference: str | None = None,
        board=None,
    ) -> tuple[DailySummaryResponse | None, dict[str, str]]:
        """
        Score the raw RSS data, filter out noise, and generate a structured summary.
        Delegates to ``generate_daily_summary_from_items`` via ContentItem conversion.
        """
        from app.services.rss_service import rss_responses_to_content_items

        content_items = rss_responses_to_content_items(rss_responses)
        return await self.generate_daily_summary_from_items(
            content_items,
            session=session,
            one_time_preference=one_time_preference,
            board=board,
        )

    async def generate_daily_summary_from_items(
        self,
        content_items: list[ContentItem],
        session: AsyncSession | None = None,
        one_time_preference: str | None = None,
        board=None,
    ) -> tuple[DailySummaryResponse | None, dict[str, str]]:
        """
        Core summary pipeline accepting unified ContentItem list.

        Returns:
            (summary_or_none, content_fallback) where content_fallback maps
            article URL -> pre-fetched body text for RAG ingest.

        Steps:
        1. Build persona context
        2. Convert ContentItem -> article dicts
        3. Remove recently-shown URLs
        4. URL cross-source dedup + AI semantic dedup
        5. Quality scoring
        6. LLM summarisation
        """
        if not settings.effective_llm_api_key:
            logger.error("Attempted to call LLM without API key configured.")
            return None, {}

        board_id = board.id if board else None
        base_prompt = (board.system_prompt or EDITOR_PROMPT) if board else EDITOR_PROMPT
        schema_suffix = (
            "\n\nIMPORTANT: You MUST output a valid JSON object matching exactly this schema "
            "(no markdown fences, no extra keys at the top level):\n"
            "{\n"
            '  "date": "YYYY-MM-DD",\n'
            '  "overview": "A 2-3 sentence engaging summary of today\'s most important themes.",\n'
            '  "top_news": [\n'
            "    {\n"
            '      "headline": "Clear, standalone headline",\n'
            '      "category": "Broad category name",\n'
            '      "key_points": ["Point 1", "Point 2"],\n'
            '      "tags": ["#Tag1", "#Tag2"],\n'
            '      "original_link": "URL from input",\n'
            '      "source": "source value from input"\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "Both `overview` and `top_news` are REQUIRED."
        )
        system_prompt = base_prompt + schema_suffix

        persona_context = ""
        if session:
            try:
                personas = await db_service.get_active_personas(session, board_id=board_id)
                if personas:
                    persona_lines = []
                    for persona in personas:
                        cat = persona.category
                        if cat == "instruction":
                            marker = "[Instruction]"
                        elif cat == "extracted":
                            marker = "[Derived Interest]"
                        elif cat == "focus_topic":
                            marker = "[MUST COVER topic]"
                        elif cat == "block_topic":
                            marker = "[NEVER include topic]"
                        elif cat == "prefer_source":
                            marker = "[Preferred source]"
                        elif cat == "avoid_source":
                            marker = "[De-prioritize source]"
                        else:
                            marker = f"[{cat}]"
                        persona_lines.append(f"- {marker} {persona.content}")
                    has_extracted = any(p.category == "extracted" for p in personas)
                    diversity_note = (
                        "\nIMPORTANT: These preferences should influence article PRIORITY (put preferred topics near the top), "
                        "but do NOT let them dominate the entire briefing. At most 30-40% of articles should match user interests — "
                        "the rest should cover other important news of the day for breadth."
                    ) if has_extracted else ""
                    persona_context = (
                        "\n\nUSER PERSONALITY & PREFERENCE GUIDELINES:\n"
                        + "\n".join(persona_lines)
                        + "\nAdhere to these preferences while selecting and summarizing."
                        + diversity_note
                    )
            except Exception as error:
                logger.warning("Failed to fetch user persona: %s", error)

        if one_time_preference:
            if not persona_context:
                persona_context = "\n\nUSER PERSONALITY & PREFERENCE GUIDELINES:\n"
            persona_context += f"- [Today Only] {one_time_preference}\n"

        # ---- Interest-based pre-filter ----
        from app.services.interest_filter import build_interest_filter

        interest_filter = None
        if session:
            try:
                personas = await db_service.get_active_personas(session, board_id=board_id)
                if personas:
                    interest_filter = build_interest_filter(personas)
            except Exception as err:
                logger.warning("Failed to build interest filter: %s", err)

        if interest_filter and interest_filter.has_interests:
            before_filter = len(content_items)
            content_items = interest_filter.filter_items(content_items)
            logger.info(
                "Interest pre-filter: %d -> %d items",
                before_filter, len(content_items),
            )

        # ---- URL cross-source dedup + AI semantic dedup ----
        from app.services.dedup_service import (
            merge_cross_source_duplicates,
            merge_topic_duplicates,
        )

        deduped_items = merge_cross_source_duplicates(content_items)
        if len(deduped_items) < len(content_items):
            logger.info(
                "URL dedup: %d -> %d items",
                len(content_items), len(deduped_items),
            )

        # Build content fallback map for RAG ingest (body + comments)
        content_fallback: dict[str, str] = {}
        for ci in deduped_items:
            if ci.content and len(ci.content) > 100:
                content_fallback[ci.url] = ci.content

        # Convert ContentItem -> article dicts for scoring / LLM
        raw_articles = []
        for ci in deduped_items:
            comments_excerpt = ""
            if ci.content and "--- Top Comments ---" in ci.content:
                comments_excerpt = ci.content.split("--- Top Comments ---", 1)[1][:200]
            raw_articles.append(
                {
                    "title": ci.title,
                    "summary": (ci.content or "")[:300],
                    "link": ci.url,
                    "source": ci.source_name or ci.source_type,
                    "comments_excerpt": comments_excerpt,
                }
            )

        # Remove articles already shown in the last 3 days
        if session:
            try:
                recent_urls = await db_service.get_recent_article_urls(
                    session, board_id=board_id, days=3
                )
                if recent_urls:
                    before = len(raw_articles)
                    raw_articles = [a for a in raw_articles if a["link"] not in recent_urls]
                    logger.info(
                        "Dedup: removed %d/%d articles already shown recently",
                        before - len(raw_articles), before,
                    )
            except Exception as dedup_err:
                logger.warning("Dedup check failed, proceeding without: %s", dedup_err)

        limited_articles = raw_articles[:50]
        if not limited_articles:
            logger.info("No articles to summarize.")
            return None, content_fallback

        logger.info("Starting quality scoring for %s articles...", len(limited_articles))
        scoring_context = ""
        if interest_filter:
            scoring_context = interest_filter.build_scoring_context()
        high_quality, rec_report = await self._score_articles(limited_articles, interest_context=scoring_context)
        logger.info("Proceeding with %s high-quality articles for summarization.", len(high_quality))

        # ---- AI semantic dedup on scored articles ----
        # Re-wrap as lightweight ContentItem for the dedup call, then unwrap.
        scored_ci = [
            ContentItem(
                id=f"tmp:{i}",
                source_type=a.get("source", "rss"),
                title=a["title"],
                url=a["link"],
                content=a.get("summary", ""),
                source_name=a.get("source", ""),
            )
            for i, a in enumerate(high_quality)
        ]
        try:
            deduped_ci = await merge_topic_duplicates(scored_ci, self.llm)
            if len(deduped_ci) < len(scored_ci):
                logger.info(
                    "AI semantic dedup: %d -> %d items",
                    len(scored_ci), len(deduped_ci),
                )
                # Map back to article dicts
                keep_ids = {ci.id for ci in deduped_ci}
                high_quality = [
                    a for i, a in enumerate(high_quality)
                    if f"tmp:{i}" in keep_ids
                ]
        except Exception as e:
            logger.warning("AI semantic dedup failed, proceeding without: %s", e)

        input_json = json.dumps(high_quality, ensure_ascii=False)

        try:
            logger.info("Calling LLM chat.completions for daily summary (articles=%d)...", len(high_quality))
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt + persona_context + ("\nYou must respond in JSON format." if "json" not in (system_prompt + persona_context).lower() else "")},
                    {
                        "role": "user",
                        "content": f"Today's Date: {datetime.now().strftime('%Y-%m-%d')}\n\nHere are the articles (respond in JSON):\n{input_json}",
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=4000,
            )
            logger.info("LLM summary response received")

            parsed_json = json.loads(response.choices[0].message.content)
            top_news = parsed_json.get("top_news", [])
            stats = {}
            for item in top_news:
                source = item.get("source", "未知来源")
                stats[source] = stats.get(source, 0) + 1
            parsed_json["source_stats"] = stats
            
            # Map the recommendation metrics back to the response
            final_headlines = [n.get("headline") for n in top_news]
            rec_report["final_recommended_count"] = len(top_news)
            parsed_json["recommendation_report"] = rec_report

            return DailySummaryResponse(**parsed_json), content_fallback
        except Exception as error:
            logger.exception("Error during LLM summarization: %s", error)
            return None, content_fallback


    async def generate_pure_llm_summary(
        self,
        board,
        session: AsyncSession | None = None,
        one_time_preference: str | None = None,
    ) -> DailySummaryResponse | None:
        """
        Generate a daily summary WITHOUT any external data source. The LLM
        produces N original items guided by the board's system_prompt and
        source_config (e.g. ``items_per_day``, ``style``).

        Used by boards like 冷知识 / 英语学习 / 名人名言 that don't rely on RSS.
        """
        if not settings.effective_llm_api_key:
            logger.error("Attempted pure-LLM generation without API key.")
            return None

        config = board.source_config or {}
        items_per_day = int(config.get("items_per_day", 5))
        items_per_day = max(1, min(items_per_day, 15))
        style_hint = config.get("style", "")

        # Persona context (board-scoped + globals).
        persona_context = ""
        if session:
            try:
                personas = await db_service.get_active_personas(session, board_id=board.id)
                if personas:
                    lines = [f"- {p.category}: {p.content}" for p in personas]
                    persona_context = (
                        "\n\nUSER PREFERENCES:\n" + "\n".join(lines)
                    )
            except Exception as error:
                logger.warning("Failed to fetch personas for pure-LLM board: %s", error)

        if one_time_preference:
            persona_context += f"\n- [Today Only] {one_time_preference}"

        base_prompt = board.system_prompt or (
            f"You are the editor of the '{board.name}' board. "
            f"Generate {items_per_day} high-quality, self-contained items for today."
        )
        if style_hint:
            base_prompt += f"\nStyle guidance: {style_hint}"

        output_schema = (
            "Output a valid JSON object with this exact schema (no code fences):\n"
            "{\n"
            '  "overview": "A 1-2 sentence intro to today\'s items.",\n'
            '  "top_news": [\n'
            "    {\n"
            '      "headline": "Concise headline for the item",\n'
            '      "category": "Short category label",\n'
            '      "key_points": ["Point 1 ...", "Point 2 ..."],\n'
            '      "tags": ["#Tag1", "#Tag2"],\n'
            '      "original_link": "",\n'
            f'      "source": "{board.name}"\n'
            "    }\n"
            "  ]\n"
            "}\n"
            f"Produce exactly {items_per_day} items. All content must be original and factual."
        )

        system_content = base_prompt + persona_context + "\n\n" + output_schema + ("\nYou must respond in JSON format." if "json" not in (base_prompt + persona_context + output_schema).lower() else "")
        user_content = f"Today's Date: {datetime.now().strftime('%Y-%m-%d')}. Produce today's items now."

        try:
            logger.info(
                "Calling LLM chat.completions for pure-LLM board '%s' (items=%d)...",
                board.slug,
                items_per_day,
            )
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
                max_tokens=3000,
            )
            logger.info("LLM pure-LLM response received for board '%s'", board.slug)

            parsed = json.loads(response.choices[0].message.content)
            top_news = parsed.get("top_news", [])

            # Fill required fields / guard missing ones
            for i, item in enumerate(top_news):
                item.setdefault("category", board.name)
                item.setdefault("key_points", [])
                item.setdefault("tags", [])
                # Generate deterministic pseudo-URLs so PK constraints don't collide.
                if not item.get("original_link"):
                    slug = board.slug
                    date = datetime.now().strftime("%Y%m%d")
                    item["original_link"] = f"llm://{slug}/{date}/{i + 1}"
                item.setdefault("source", board.name)

            stats: dict[str, int] = {}
            for item in top_news:
                src = item.get("source", board.name)
                stats[src] = stats.get(src, 0) + 1

            parsed["top_news"] = top_news
            parsed["source_stats"] = stats
            parsed.setdefault("overview", "")
            parsed.setdefault("date", datetime.now().strftime("%Y-%m-%d"))
            parsed["recommendation_report"] = {
                "total_fetched": 0,
                "passed_count": len(top_news),
                "excluded_count": 0,
                "final_recommended_count": len(top_news),
                "source_type": "pure_llm",
            }

            return DailySummaryResponse(**parsed)
        except Exception as error:
            logger.exception("Error during pure-LLM generation: %s", error)
            return None
