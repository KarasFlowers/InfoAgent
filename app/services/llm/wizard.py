"""Board Wizard and interest extraction."""
import json
import logging

from app.core.config import settings
from app.prompts import get_prompt

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

        system_prompt = get_prompt("board_wizard")

        full_messages = [{"role": "system", "content": system_prompt}]
        for m in messages:
            role = m.get("role", "user")
            if role not in ("user", "assistant"):
                continue
            full_messages.append({"role": role, "content": str(m.get("content", ""))})

        try:
            response = await self.llm.chat(
                messages=full_messages,
                tier="smart",
                label="wizard",
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
                tier="fast",
                label="interest_extract",
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
