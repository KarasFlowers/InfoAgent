from datetime import datetime, UTC
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship

class NewsItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    headline: str = Field(index=True)
    category: str = Field(default="Uncategorized", index=True)
    # Store key points as a JSON string
    key_points: str 
    # Store tags as a JSON string
    tags: str = Field(default="[]")
    original_link: str
    source: str
    
    # Foreign key to DailySummary with Cascade Delete
    summary_id: int = Field(foreign_key="dailysummary.id", ondelete="CASCADE")
    summary: "DailySummary" = Relationship(back_populates="top_news")

class DailySummary(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    # Note: SQLite doesn't natively support Date, so we store it as a string YYYY-MM-DD
    date: str = Field(index=True, unique=True)
    overview: str
    stats_json: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    
    top_news: List[NewsItem] = Relationship(back_populates="summary")

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

class UserPersona(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    # The actual instruction or extracted keyword
    content: str
    # "instruction" (manual) vs "extracted" (from vector)
    category: str = Field(default="instruction", index=True)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
