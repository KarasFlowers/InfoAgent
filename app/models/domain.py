from datetime import datetime, UTC
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import UniqueConstraint, JSON, Column, Text


class Board(SQLModel, table=True):
    """
    A "board" (custom section) — e.g. 科技快讯, 冷知识, 英语学习.
    Each board has its own system prompt, data sources, and optionally
    its own preferences / feedback.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)   # e.g. "tech", "trivia", "english"
    name: str                                     # display name e.g. "科技快讯"
    icon: str = Field(default="")                 # emoji or lucide key
    description: str = Field(default="")
    system_prompt: str = Field(default="")        # editor prompt override
    source_type: str = Field(default="rss")       # "rss" | "pure_llm" | "hackernews" | "reddit" | "github" | "multi"
    source_config: Optional[dict] = Field(default_factory=dict, sa_column=Column(JSON))
    display_order: int = Field(default=0, index=True)
    is_active: bool = Field(default=True)
    is_default: bool = Field(default=False)       # exactly one default per install
    schedule: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))  # cron expr e.g. "08:00" or "*/6h"; empty = use global
    notify_channels: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))  # comma-separated: "email,webhook,bark" ; empty = all configured
    perspectives: Optional[dict] = Field(default=None, sa_column=Column(JSON))  # e.g. {"active": ["technical", "business"]}; None = single-view mode
    prompt_key: str = Field(default="daily_briefing", sa_column=Column(Text, nullable=False, server_default="daily_briefing"))  # prompt template key
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class NewsItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    headline: str = Field(index=True)
    category: str = Field(default="Uncategorized", index=True)
    # Stored as native JSON column (migrated from JSON-string in refactor)
    key_points: list = Field(default=[], sa_column=Column(JSON))
    tags: list = Field(default=[], sa_column=Column(JSON))
    topic_path: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))  # e.g. "AI/LLM/微调"
    original_link: str
    source: str
    
    # Foreign key to DailySummary with Cascade Delete
    summary_id: int = Field(foreign_key="dailysummary.id", ondelete="CASCADE")
    summary: "DailySummary" = Relationship(back_populates="top_news")


class DailySummary(SQLModel, table=True):
    # One summary per (board, date, perspective).
    __table_args__ = (
        UniqueConstraint("board_id", "date", "perspective", name="ux_dailysummary_board_date_perspective"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    # Note: SQLite doesn't natively support Date, so we store it as a string YYYY-MM-DD
    date: str = Field(index=True)
    board_id: Optional[int] = Field(
        default=None, foreign_key="board.id", index=True, ondelete="CASCADE"
    )
    perspective: str = Field(default="overview", sa_column=Column(Text, nullable=False, server_default="overview"))  # "overview" | "technical" | "business" | custom
    overview: str
    stats_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # cascade="all, delete-orphan" ensures ORM-level deletion removes related NewsItems
    # instead of trying to NULL their summary_id (which violates NOT NULL).
    top_news: List[NewsItem] = Relationship(
        back_populates="summary",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class UserFeedback(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    article_url: str = Field(index=True, unique=True)
    # sentiment: 1 for Like, -1 for Dislike
    sentiment: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    article_url: str = Field(index=True)
    role: str  # "user" or "ai"
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ArticleOverview(SQLModel, table=True):
    """Persisted article overview text — avoids re-generating on every panel open."""
    id: Optional[int] = Field(default=None, primary_key=True)
    article_url: str = Field(index=True, unique=True)
    overview_text: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UserPersona(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    # The actual instruction or extracted keyword
    content: str
    # "instruction" (manual) vs "extracted" (from vector) vs explicit categories
    category: str = Field(default="instruction", index=True)
    # null = global (applies to all boards). Non-null = scoped to a single board.
    board_id: Optional[int] = Field(
        default=None, foreign_key="board.id", index=True, ondelete="CASCADE"
    )
    is_active: bool = Field(default=True)
    weight: float = Field(default=1.0)  # decay weight for auto-extracted interests
    source: str = Field(default="manual", sa_column=Column(Text, nullable=False, server_default="manual"))  # "manual" | "auto"
    last_refreshed: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
