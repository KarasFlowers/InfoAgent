import json
import logging
import time
from datetime import datetime

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.schemas import DailySummaryResponse, RSSResponse
from app.services.db_service import db_service
from app.services.metrics_service import metrics_service

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

        # timeout=180s prevents summary generation from hanging indefinitely.
        # max_retries=1 retries once on connection errors / 5xx responses.
        self.client = AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            timeout=180.0,
            max_retries=1,
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
            start_time = time.time()
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
            duration = time.time() - start_time
            
            if response.usage:
                await metrics_service.record_tokens(
                    response.usage.prompt_tokens, 
                    response.usage.completion_tokens
                )
            # Not recording _score_articles latency to the "summary" metric, because it's just scoring.
            
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
        board=None,
    ) -> DailySummaryResponse | None:
        """
        Score the raw RSS data, filter out noise, and generate a structured summary.
        Persona instructions are included when available.
        When ``board`` is provided, personas are scoped to that board (plus globals)
        and ``board.system_prompt`` overrides the default EDITOR_PROMPT.
        """
        if not settings.DEEPSEEK_API_KEY:
            logger.error("Attempted to call LLM without API key configured.")
            return None

        board_id = board.id if board else None
        base_prompt = (board.system_prompt or EDITOR_PROMPT) if board else EDITOR_PROMPT
        # Always enforce the output JSON schema, even when a custom board
        # system_prompt is used (otherwise the LLM may omit required fields).
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
            start_time = time.time()
            logger.info("Calling DeepSeek chat.completions for daily summary (articles=%d)...", len(high_quality))
            response = await self.client.chat.completions.create(
                model="deepseek-chat",
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
            duration = time.time() - start_time
            logger.info("DeepSeek summary response received in %.2fs", duration)

            if response.usage:
                await metrics_service.record_tokens(
                    response.usage.prompt_tokens, 
                    response.usage.completion_tokens
                )
            await metrics_service.record_latency(duration)

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
            logger.exception("Error during LLM summarization: %s", error)
            return None


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
        if not settings.DEEPSEEK_API_KEY:
            logger.error("Attempted pure-LLM generation without API key.")
            return None

        try:
            config = json.loads(board.source_config or "{}")
        except (json.JSONDecodeError, TypeError):
            config = {}
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
            start_time = time.time()
            logger.info(
                "Calling DeepSeek chat.completions for pure-LLM board '%s' (items=%d)...",
                board.slug,
                items_per_day,
            )
            response = await self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
                max_tokens=3000,
            )
            duration = time.time() - start_time
            logger.info("DeepSeek pure-LLM response received in %.2fs", duration)

            if response.usage:
                await metrics_service.record_tokens(
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                )
            await metrics_service.record_latency(duration)

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

            if response.usage:
                await metrics_service.record_tokens(
                    response.usage.prompt_tokens, 
                    response.usage.completion_tokens
                )

            return response.choices[0].message.content
        except Exception as error:
            logger.error("Error during weekly consolidation: %s", error)
            return None

    async def wizard_suggest_board(
        self,
        messages: list[dict],
    ) -> dict:
        """
        Interactive conversational wizard that helps a user configure a new content board.
        
        Takes a conversation history (list of {role, content} dicts) and returns:
        {
          "reply": str,           # Natural-language reply to show the user
          "ready": bool,          # True if the config is complete and ready to apply
          "config": {             # null or filled when ready=True
            "slug": str,
            "name": str,
            "icon": str,
            "source_type": "rss" | "pure_llm",
            "rss_urls": list[str],
            "system_prompt": str,
          } | None
        }
        """
        if not settings.DEEPSEEK_API_KEY:
            return {"reply": "LLM API key 未配置。", "ready": False, "config": None}

        system_prompt = """你是 InfoAgent 的「板块配置向导」，帮助用户配置一个新的内容板块。

你的目标：通过 1-3 轮对话，快速理解用户想要什么内容，并输出一份可直接使用的板块配置。

输出格式：你必须始终返回一个 JSON 对象，结构如下：
{
  "reply": "用简体中文，对用户友好、简洁的回复（markdown 允许）。如果还缺关键信息则在这里追问。如果已经给出配置，可在这里解释你的选择。",
  "ready": true | false,
  "config": {
    "slug": "英文小写横线分隔的唯一标识，如 english-daily",
    "name": "中文显示名，如 每日英语",
    "icon": "一个 emoji，如 🇬🇧",
    "source_type": "rss 或 pure_llm",
    "rss_urls": ["https://...", ...],
    "system_prompt": "将写入板块的系统级提示词，用于指导 AI 每天生成该板块内容的风格/重点/格式"
  } | null
}

决策规则：
1. 如果用户描述清晰（说明了主题），你应尽量**一次性**给出完整 config 并设 ready=true，不要反复追问。
2. 如果用户描述过于模糊（比如只说"有趣内容"），才追问 1 次澄清，此时 ready=false、config=null。
3. source_type 判断：
   - 如果话题有现成的优质 RSS 源（新闻、博客、技术社区、播客），用 "rss"，并在 rss_urls 中给出 3-6 个**真实存在的、常用的**公开 RSS feed 地址。
   - 如果话题是"学习素材生成""每日一句""冷知识""心理学小知识"等需要 AI 原创的，用 "pure_llm"，rss_urls 留空数组。
4. system_prompt 要具体可执行，说明：内容风格、篇幅、格式（是否 markdown）、是否需要例句/翻译等。
5. 常用中文互联网 RSS 源示例（真实可用，供参考）：
   - 少数派 https://sspai.com/feed
   - 36氪 https://36kr.com/feed
   - 阮一峰科技周刊 https://www.ruanyifeng.com/blog/atom.xml
   - 机器之心 https://www.jiqizhixin.com/rss
   - linux.do https://linux.do/top.rss
   - 英语相关：BBC Learning English https://www.bbc.co.uk/learningenglish/english/podcasts
   - VOA Learning English 类 RSS
   - Hacker News https://hnrss.org/frontpage
   - TechCrunch https://techcrunch.com/feed/
   - The Verge https://www.theverge.com/rss/index.xml
6. 确保只输出 JSON，不要任何外层文字或代码块标记。
"""

        full_messages = [{"role": "system", "content": system_prompt}]
        for m in messages:
            role = m.get("role", "user")
            if role not in ("user", "assistant"):
                continue
            full_messages.append({"role": role, "content": str(m.get("content", ""))})

        try:
            response = await self.client.chat.completions.create(
                model="deepseek-chat",
                messages=full_messages,
                response_format={"type": "json_object"},
                temperature=0.4,
                max_tokens=1200,
            )
            if response.usage:
                await metrics_service.record_tokens(
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                )
            raw = response.choices[0].message.content or "{}"
            parsed = json.loads(raw)
            # Normalize
            reply = str(parsed.get("reply", "")).strip() or "（AI 未返回回复）"
            ready = bool(parsed.get("ready", False))
            config = parsed.get("config") if parsed.get("config") else None
            if config and not isinstance(config, dict):
                config = None
            if config:
                # Enforce expected keys
                config = {
                    "slug": str(config.get("slug", "")).strip(),
                    "name": str(config.get("name", "")).strip(),
                    "icon": str(config.get("icon", "")).strip() or "📌",
                    "source_type": config.get("source_type") if config.get("source_type") in ("rss", "pure_llm") else "rss",
                    "rss_urls": [u for u in (config.get("rss_urls") or []) if isinstance(u, str) and u.strip()],
                    "system_prompt": str(config.get("system_prompt", "")).strip(),
                }
                if not config["slug"] or not config["name"]:
                    # If slug/name missing we don't consider it ready
                    ready = False
                    config = None
            return {"reply": reply, "ready": ready, "config": config}
        except Exception as error:
            logger.exception("Board wizard LLM call failed: %s", error)
            return {
                "reply": f"抱歉，AI 向导出错了: {error}",
                "ready": False,
                "config": None,
            }


    async def extract_interest_options(
        self,
        headline: str,
        key_points: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> list[str]:
        """
        Given an article the user just liked, ask the LLM to propose 3-4
        ABSTRACT interest descriptions (short, generalizable). The user picks
        one to be saved as a long-term persona, capturing their *real* intent
        rather than the literal article subject.
        """
        if not settings.DEEPSEEK_API_KEY:
            return []

        kp_text = "\n".join(f"- {p}" for p in (key_points or []))
        tags_text = ", ".join(tags or [])

        prompt = (
            "你是一名用户兴趣分析师。用户刚刚对下面这条资讯点赞，"
            "请你推断他可能感兴趣的 3 个不同抽象层级的“长期兴趣”描述，"
            "从最具体到最抽象，便于用户挑选最贴近他真实意图的那一项。\n\n"
            "要求：\n"
            "1. 每条用 10-22 个汉字，名词短语，不要句子，不要标点结尾。\n"
            "2. 第 1 条偏具体（聚焦本文的核心实体/产品/事件类型）。\n"
            "3. 第 2 条偏中等（涵盖该实体所属领域的同类信息）。\n"
            "4. 第 3 条偏抽象（用户可能更深层的追求，如“前沿模型动态”“开发者生态变化”）。\n"
            "5. 输出 JSON：{\"options\": [\"...\", \"...\", \"...\"]} ，不要额外文本。\n"
        )

        user_content = (
            f"标题：{headline}\n"
            f"要点：\n{kp_text or '(无)'}\n"
            f"标签：{tags_text or '(无)'}"
        )

        try:
            response = await self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.5,
                max_tokens=300,
            )
            if response.usage:
                await metrics_service.record_tokens(
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                )
            data = json.loads(response.choices[0].message.content)
            options = data.get("options", []) if isinstance(data, dict) else []
            cleaned = [str(o).strip() for o in options if isinstance(o, str) and o.strip()]
            return cleaned[:4]
        except Exception as error:
            logger.warning("extract_interest_options failed: %s", error)
            return []


llm_service = LLMService()
