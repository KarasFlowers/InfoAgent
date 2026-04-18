from pydantic import BaseModel, Field


class Article(BaseModel):
    title: str
    url: str
    source: str
    content_preview: str | None = None


class RSSItem(BaseModel):
    title: str
    link: str
    published: str
    summary: str
    source: str


class RSSResponse(BaseModel):
    source_url: str
    items: list[RSSItem]


class SummaryItem(BaseModel):
    headline: str
    category: str
    key_points: list[str]
    tags: list[str] = Field(default_factory=list)
    original_link: str
    source: str
    feedback_sentiment: int | None = None
    persona_score: float | None = None


class SummaryArchiveItem(BaseModel):
    date: str
    overview_preview: str
    news_count: int
    source_stats: dict[str, int] = Field(default_factory=dict)
    top_categories: list[str] = Field(default_factory=list)


class HistoryStatItem(BaseModel):
    name: str
    count: int


class WeeklyRecapResponse(BaseModel):
    window_start: str
    window_end: str
    days_covered: int
    total_news: int
    top_categories: list[HistoryStatItem] = Field(default_factory=list)
    top_sources: list[HistoryStatItem] = Field(default_factory=list)
    recap_text: str
    weekly_insight: str | None = None
    latest_date: str


class SummaryHistoryResponse(BaseModel):
    archive_items: list[SummaryArchiveItem] = Field(default_factory=list)
    weekly_recap: WeeklyRecapResponse | None = None


class DailySummaryResponse(BaseModel):
    date: str
    overview: str
    top_news: list[SummaryItem]
    source_stats: dict[str, int] = Field(default_factory=dict)
    # Recommendation statistics for transparency
    recommendation_report: dict = Field(default_factory=dict)
