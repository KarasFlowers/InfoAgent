"""Board Wizard and interest extraction."""
import json
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class WizardMixin:
    """Mixin providing ``wizard_suggest_board`` and ``extract_interest_options``."""

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
            "source_type": "rss" | "pure_llm" | "hackernews" | "reddit" | "github" | "multi",
            "source_config": dict,
            "system_prompt": str,
          } | None
        }
        """
        if not settings.effective_llm_api_key:
            return {"reply": "LLM API key 未配置。", "ready": False, "config": None}

        system_prompt = """你是 Argos 的「板块配置向导」，帮助用户配置一个新的内容板块。

你的目标：通过 1-3 轮对话，快速理解用户想要什么内容，并输出一份可直接使用的板块配置。

输出格式：你必须始终返回一个 JSON 对象，结构如下：
{
  "reply": "用简体中文，对用户友好、简洁的回复（markdown 允许）。如果还缺关键信息则在这里追问。如果已经给出配置，可在这里解释你的选择。",
  "ready": true | false,
  "config": {
    "slug": "英文小写横线分隔的唯一标识，如 english-daily",
    "name": "中文显示名，如 每日英语",
    "icon": "一个 emoji，如 🇬🇧",
    "source_type": "rss | pure_llm | hackernews | reddit | github | multi",
    "source_config": {},
    "system_prompt": "将写入板块的系统级提示词，用于指导 AI 每天生成该板块内容的风格/重点/格式"
  } | null
}

决策规则：
1. 如果用户描述清晰（说明了主题），你应尽量**一次性**给出完整 config 并设 ready=true，不要反复追问。
2. 如果用户描述过于模糊（比如只说"有趣内容"），才追问 1 次澄清，此时 ready=false、config=null。
3. source_type 判断：
   - 如果话题有现成的优质 RSS 源（新闻、博客、技术社区、播客），用 "rss"，并在 source_config.feeds 中给出 3-6 个**真实存在的、常用的**公开 RSS feed 地址。
   - 如果话题是"学习素材生成""每日一句""冷知识""心理学小知识"等需要 AI 原创的，用 "pure_llm"。
   - 如果用户想看 Hacker News 热门讨论，用 "hackernews"，source_config 示例：{"fetch_top_stories": 30, "min_score": 100}
   - 如果用户想看 Reddit 社区内容，用 "reddit"，source_config 示例：{"subreddits": [{"subreddit": "LocalLLaMA", "min_score": 50}], "fetch_comments": 5}
   - 如果用户想追踪 GitHub 项目/用户动态，用 "github"，source_config 示例：{"repos": [{"owner": "openai", "repo": "whisper"}], "users": [{"username": "torvalds"}]}
   - 如果用户想混合多种源（如 RSS + HN + Reddit），用 "multi"，source_config 示例：{"sources": {"rss": {"feeds": ["..."]}, "hackernews": {"min_score": 100}, "reddit": {"subreddits": [{"subreddit": "programming"}]}}}
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
7. config 中的 source_config 是一个 dict，内容根据 source_type 而定：
   - rss: {"feeds": ["url1", "url2"]}
   - hackernews: {"fetch_top_stories": 30, "min_score": 100}
   - reddit: {"subreddits": [...], "fetch_comments": 5}
   - github: {"repos": [...], "users": [...]}
   - multi: {"sources": {"rss": {...}, "hackernews": {...}, ...}}
   - pure_llm: {}
"""

        full_messages = [{"role": "system", "content": system_prompt}]
        for m in messages:
            role = m.get("role", "user")
            if role not in ("user", "assistant"):
                continue
            full_messages.append({"role": role, "content": str(m.get("content", ""))})

        try:
            response = await self.llm.chat(
                messages=full_messages,
                response_format={"type": "json_object"},
                temperature=0.4,
                max_tokens=1200,
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
                    "source_type": config.get("source_type") if config.get("source_type") in ("rss", "pure_llm", "hackernews", "reddit", "github", "multi") else "rss",
                    "source_config": config.get("source_config") if isinstance(config.get("source_config"), dict) else {},
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
        if not settings.effective_llm_api_key:
            return []

        kp_text = "\n".join(f"- {p}" for p in (key_points or []))
        tags_text = ", ".join(tags or [])

        prompt = (
            "你是一名用户兴趣分析师。用户刚刚对下面这条资讯点赞，"
            "请你推断他可能感兴趣的 3 个不同抽象层级的\u201c长期兴趣\u201d描述，"
            "从最具体到最抽象，便于用户挑选最贴近他真实意图的那一项。\n\n"
            "要求：\n"
            "1. 每条用 10-22 个汉字，名词短语，不要句子，不要标点结尾。\n"
            "2. 第 1 条偏具体（聚焦本文的核心实体/产品/事件类型）。\n"
            "3. 第 2 条偏中等（涵盖该实体所属领域的同类信息）。\n"
            "4. 第 3 条偏抽象（用户可能更深层的追求，如\u201c前沿模型动态\u201d\u201c开发者生态变化\u201d）。\n"
            '5. 输出 JSON：{"options": ["...", "...", "..."]} ，不要额外文本。\n'
        )

        user_content = (
            f"标题：{headline}\n"
            f"要点：\n{kp_text or '(无)'}\n"
            f"标签：{tags_text or '(无)'}"
        )

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.5,
                max_tokens=300,
            )
            data = json.loads(response.choices[0].message.content)
            options = data.get("options", []) if isinstance(data, dict) else []
            cleaned = [str(o).strip() for o in options if isinstance(o, str) and o.strip()]
            return cleaned[:4]
        except Exception as error:
            logger.warning("extract_interest_options failed: %s", error)
            return []
