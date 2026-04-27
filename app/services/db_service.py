from sqlalchemy import delete as sa_delete, desc
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
import json
import logging
from datetime import datetime, timedelta

from app.models.domain import Board, DailySummary, NewsItem, UserFeedback, UserPersona, ChatMessage
from app.models.schemas import DailySummaryResponse, HistoryStatItem, SummaryArchiveItem, SummaryHistoryResponse, SummaryItem, WeeklyRecapResponse

logger = logging.getLogger(__name__)


class DBService:
    async def get_summary_by_date(
        self,
        session: AsyncSession,
        date_str: str,
        board_id: int | None = None,
    ) -> DailySummaryResponse | None:
        """
        Check if a summary already exists for a specific date (YYYY-MM-DD).
        When board_id is provided, restricts to that board.
        """
        statement = select(DailySummary).where(DailySummary.date == date_str)
        if board_id is not None:
            statement = statement.where(DailySummary.board_id == board_id)
        result = await session.execute(statement)
        db_summary = result.scalars().first()

        if not db_summary:
            return None

        news_statement = select(NewsItem).where(NewsItem.summary_id == db_summary.id)
        news_result = await session.execute(news_statement)
        db_news_items = news_result.scalars().all()

        article_urls = [item.original_link for item in db_news_items]
        feedback_map: dict[str, int] = {}
        if article_urls:
            feedback_statement = select(UserFeedback.article_url, UserFeedback.sentiment).where(
                UserFeedback.article_url.in_(article_urls)
            )
            feedback_result = await session.execute(feedback_statement)
            # article_url is UNIQUE, so a simple dict is correct.
            feedback_map = dict(feedback_result.all())

        top_news = []
        for item in db_news_items:
            try:
                key_points_list = json.loads(item.key_points)
            except json.JSONDecodeError:
                key_points_list = [item.key_points]

            try:
                tags_list = json.loads(item.tags) if item.tags else []
            except json.JSONDecodeError:
                tags_list = []

            top_news.append(
                SummaryItem(
                    headline=item.headline,
                    category=item.category or "Uncategorized",
                    key_points=key_points_list,
                    tags=tags_list,
                    original_link=item.original_link,
                    source=item.source,
                    feedback_sentiment=feedback_map.get(item.original_link),
                )
            )

        stats = {}
        for item in top_news:
            stats[item.source] = stats.get(item.source, 0) + 1

        return DailySummaryResponse(
            date=db_summary.date,
            overview=db_summary.overview,
            top_news=top_news,
            source_stats=stats,
            recommendation_report=json.loads(db_summary.stats_json) if db_summary.stats_json else {}
        )

    async def get_summary_archive(self, session: AsyncSession, limit: int = 7, board_id: int | None = None) -> list[SummaryArchiveItem]:
        """
        Return lightweight archive cards for recent summaries.
        """
        history = await self.get_summary_history(session, limit=limit, board_id=board_id)
        return history.archive_items

    async def get_summary_history(self, session: AsyncSession, limit: int = 7, board_id: int | None = None) -> SummaryHistoryResponse:
        """
        Return archive cards together with a lightweight weekly recap.
        """
        statement = select(DailySummary)
        if board_id is not None:
            statement = statement.where(DailySummary.board_id == board_id)
        statement = statement.order_by(desc(DailySummary.date)).limit(limit)
        result = await session.execute(statement)
        summaries = result.scalars().all()

        if not summaries:
            return SummaryHistoryResponse()

        summary_ids = [summary.id for summary in summaries if summary.id is not None]
        news_by_summary_id: dict[int, list[NewsItem]] = {summary_id: [] for summary_id in summary_ids}

        if summary_ids:
            news_statement = select(NewsItem).where(NewsItem.summary_id.in_(summary_ids))
            news_result = await session.execute(news_statement)
            for item in news_result.scalars().all():
                news_by_summary_id.setdefault(item.summary_id, []).append(item)

        archive: list[SummaryArchiveItem] = []
        source_totals: dict[str, int] = {}
        category_totals: dict[str, int] = {}

        for summary in summaries:
            news_items = news_by_summary_id.get(summary.id or -1, [])
            source_stats: dict[str, int] = {}
            category_counts: dict[str, int] = {}

            for item in news_items:
                source = item.source or "未知来源"
                category = item.category or "未分类"
                source_stats[source] = source_stats.get(source, 0) + 1
                category_counts[category] = category_counts.get(category, 0) + 1
                source_totals[source] = source_totals.get(source, 0) + 1
                category_totals[category] = category_totals.get(category, 0) + 1

            top_categories = [
                name
                for name, _ in sorted(
                    category_counts.items(),
                    key=lambda pair: (-pair[1], pair[0]),
                )[:3]
            ]

            overview_preview = (summary.overview or "").strip().replace("\n", " ")
            if len(overview_preview) > 120:
                overview_preview = overview_preview[:117].rstrip() + "..."

            archive.append(
                SummaryArchiveItem(
                    date=summary.date,
                    overview_preview=overview_preview,
                    news_count=len(news_items),
                    source_stats=source_stats,
                    top_categories=top_categories,
                )
            )

        weekly_recap = self._build_weekly_recap(archive, category_totals, source_totals)
        return SummaryHistoryResponse(archive_items=archive, weekly_recap=weekly_recap)

    def _build_weekly_recap(
        self,
        archive_items: list[SummaryArchiveItem],
        category_totals: dict[str, int],
        source_totals: dict[str, int],
    ) -> WeeklyRecapResponse | None:
        if not archive_items:
            return None

        sorted_categories = sorted(category_totals.items(), key=lambda pair: (-pair[1], pair[0]))
        sorted_sources = sorted(source_totals.items(), key=lambda pair: (-pair[1], pair[0]))
        top_category_names = [name for name, _ in sorted_categories[:3]]
        latest_entry = archive_items[0]
        previous_entry = archive_items[1] if len(archive_items) > 1 else None

        recap_parts = []
        if top_category_names:
            recap_parts.append(f"本周主要聚焦 {', '.join(top_category_names)}")
        if sorted_sources:
            recap_parts.append(f"其中 {sorted_sources[0][0]} 出现最频繁")
        if previous_entry:
            latest_categories = set(latest_entry.top_categories)
            previous_categories = set(previous_entry.top_categories)
            new_categories = [category for category in latest_categories if category not in previous_categories]
            if new_categories:
                recap_parts.append(f"最新一期新增了 {', '.join(new_categories[:2])} 等主题")
            elif latest_categories & previous_categories:
                recurring = list(latest_categories & previous_categories)
                recap_parts.append(f"最近两期持续关注 {', '.join(recurring[:2])}")

        recap_text = "，".join(recap_parts) + "。" if recap_parts else "本周已有多期简报，可从这里快速回看重点主题。"

        return WeeklyRecapResponse(
            window_start=archive_items[-1].date,
            window_end=archive_items[0].date,
            days_covered=len(archive_items),
            total_news=sum(item.news_count for item in archive_items),
            top_categories=[HistoryStatItem(name=name, count=count) for name, count in sorted_categories[:3]],
            top_sources=[HistoryStatItem(name=name, count=count) for name, count in sorted_sources[:3]],
            recap_text=recap_text,
            latest_date=archive_items[0].date,
        )

    async def replace_summary(
        self,
        session: AsyncSession,
        summary: DailySummaryResponse,
        board_id: int | None = None,
    ) -> None:
        """
        Replace an existing summary atomically (scoped to board when provided).
        """
        try:
            statement = select(DailySummary).where(DailySummary.date == summary.date)
            if board_id is not None:
                statement = statement.where(DailySummary.board_id == board_id)
            result = await session.execute(statement)
            existing = result.scalars().first()

            if existing:
                await session.execute(sa_delete(NewsItem).where(NewsItem.summary_id == existing.id))
                await session.delete(existing)
                await session.flush()

            await self._persist_summary(session, summary, board_id=board_id)
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            raise

    async def save_summary(
        self,
        session: AsyncSession,
        summary: DailySummaryResponse,
        board_id: int | None = None,
    ) -> None:
        """
        Save a newly generated LLM summary into the database.
        """
        try:
            await self._persist_summary(session, summary, board_id=board_id)
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            raise

    async def _persist_summary(
        self,
        session: AsyncSession,
        summary: DailySummaryResponse,
        board_id: int | None = None,
    ) -> None:
        db_summary = DailySummary(
            date=summary.date,
            board_id=board_id,
            overview=summary.overview,
            stats_json=json.dumps(summary.recommendation_report, ensure_ascii=False) if summary.recommendation_report else None
        )
        session.add(db_summary)
        await session.flush()

        for item in summary.top_news:
            db_news = NewsItem(
                headline=item.headline,
                category=item.category,
                key_points=json.dumps(item.key_points, ensure_ascii=False),
                tags=json.dumps(item.tags, ensure_ascii=False) if item.tags else "[]",
                original_link=item.original_link,
                source=item.source,
                summary_id=db_summary.id,
            )
            session.add(db_news)

    async def get_active_personas(
        self,
        session: AsyncSession,
        board_id: int | None = None,
        include_global: bool = True,
    ) -> list:
        """
        Get active user persona entries.

        - ``board_id=None, include_global=True`` — returns all personas (legacy behavior).
        - ``board_id=<int>, include_global=True`` — returns global (null board_id)
          + personas for that board.
        - ``board_id=<int>, include_global=False`` — returns only personas for that
          specific board.
        """
        statement = select(UserPersona).where(UserPersona.is_active == True)
        if board_id is not None:
            if include_global:
                statement = statement.where(
                    (UserPersona.board_id == board_id) | (UserPersona.board_id.is_(None))
                )
            else:
                statement = statement.where(UserPersona.board_id == board_id)
        result = await session.execute(statement)
        return result.scalars().all()

    async def save_persona(
        self,
        session: AsyncSession,
        content: str,
        category: str = "instruction",
        board_id: int | None = None,
    ) -> None:
        """
        Save a new persona entry (null board_id = global).
        """
        db_persona = UserPersona(content=content, category=category, board_id=board_id)
        session.add(db_persona)
        await session.commit()

    async def delete_persona(self, session: AsyncSession, persona_id: int) -> None:
        """
        Delete a persona entry by ID.
        """
        statement = select(UserPersona).where(UserPersona.id == persona_id)
        result = await session.execute(statement)
        db_persona = result.scalars().first()
        if db_persona:
            await session.delete(db_persona)
            await session.commit()

    async def get_personas_by_category(
        self,
        session: AsyncSession,
        category: str,
        board_id: int | None = None,
        include_global: bool = True,
    ) -> list:
        """
        Get active personas of a specific category, optionally scoped to a board.
        """
        statement = select(UserPersona).where(
            UserPersona.is_active == True,
            UserPersona.category == category,
        )
        if board_id is not None:
            if include_global:
                statement = statement.where(
                    (UserPersona.board_id == board_id) | (UserPersona.board_id.is_(None))
                )
            else:
                statement = statement.where(UserPersona.board_id == board_id)
        result = await session.execute(statement)
        return result.scalars().all()

    async def get_explicit_preferences(
        self,
        session: AsyncSession,
        board_id: int | None = None,
        include_global: bool = True,
    ) -> dict[str, list[str]]:
        """
        Return all explicit preference personas grouped by category.
        Output: {"focus_topic": ["AI", ...], "block_topic": [...], "prefer_source": [...], "avoid_source": [...]}
        """
        categories = ["focus_topic", "block_topic", "prefer_source", "avoid_source"]
        statement = select(UserPersona).where(
            UserPersona.is_active == True,
            UserPersona.category.in_(categories),
        )
        if board_id is not None:
            if include_global:
                statement = statement.where(
                    (UserPersona.board_id == board_id) | (UserPersona.board_id.is_(None))
                )
            else:
                statement = statement.where(UserPersona.board_id == board_id)
        result = await session.execute(statement)
        personas = result.scalars().all()
        grouped: dict[str, list[str]] = {cat: [] for cat in categories}
        for p in personas:
            grouped[p.category].append(p.content)
        return grouped

    async def get_available_dates(self, session: AsyncSession, limit: int = 7) -> list[str]:
        """
        Return the list of dates that have a summary, ordered by newest first.
        """
        statement = select(DailySummary.date).order_by(desc(DailySummary.date)).limit(limit)
        result = await session.execute(statement)
        return list(result.scalars().all())

    async def cleanup_old_data(self, session: AsyncSession, days_to_keep: int = 7) -> int:
        """
        Delete summaries and their associated news items/vectors older than X days.
        """
        threshold_date = (datetime.now() - timedelta(days=days_to_keep)).strftime("%Y-%m-%d")

        # 1. Find summaries older than threshold
        statement = select(DailySummary).where(DailySummary.date < threshold_date)
        result = await session.execute(statement)
        old_summaries = result.scalars().all()

        if not old_summaries:
            return 0

        summary_ids = [s.id for s in old_summaries]

        # 2. Extract article URLs for vector cleanup
        news_statement = select(NewsItem.original_link).where(NewsItem.summary_id.in_(summary_ids))
        news_result = await session.execute(news_statement)
        urls_to_delete = list(news_result.scalars().all())

        # 3. Delete from Vector Store (ChromaDB)
        if urls_to_delete:
            from app.services.rag_service import delete_collections_by_urls
            await delete_collections_by_urls(urls_to_delete)

        # 4. Delete article-linked feedback/chat rows before removing summaries
        if urls_to_delete:
            await session.execute(sa_delete(UserFeedback).where(UserFeedback.article_url.in_(urls_to_delete)))
            await session.execute(sa_delete(ChatMessage).where(ChatMessage.article_url.in_(urls_to_delete)))

        # 5. Delete from SQLite (Cascades to NewsItem)
        for s in old_summaries:
            await session.delete(s)

        await session.commit()
        logger.info("Cleanup removed %s summaries older than %s", len(old_summaries), threshold_date)
        return len(old_summaries)


    # ------------------------------------------------------------------
    # Board management
    # ------------------------------------------------------------------

    async def list_boards(self, session: AsyncSession, active_only: bool = True) -> list[Board]:
        """Return all boards ordered by display_order."""
        stmt = select(Board)
        if active_only:
            stmt = stmt.where(Board.is_active == True)
        stmt = stmt.order_by(Board.display_order, Board.id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_board_by_slug(self, session: AsyncSession, slug: str) -> Board | None:
        stmt = select(Board).where(Board.slug == slug)
        result = await session.execute(stmt)
        return result.scalars().first()

    async def get_board_by_id(self, session: AsyncSession, board_id: int) -> Board | None:
        stmt = select(Board).where(Board.id == board_id)
        result = await session.execute(stmt)
        return result.scalars().first()

    async def get_default_board(self, session: AsyncSession) -> Board | None:
        """Return the is_default board, or fall back to the first active board."""
        stmt = select(Board).where(Board.is_default == True).limit(1)
        result = await session.execute(stmt)
        board = result.scalars().first()
        if board:
            return board
        stmt = select(Board).where(Board.is_active == True).order_by(Board.display_order, Board.id).limit(1)
        result = await session.execute(stmt)
        return result.scalars().first()

    async def create_board(
        self,
        session: AsyncSession,
        slug: str,
        name: str,
        icon: str = "",
        description: str = "",
        system_prompt: str = "",
        source_type: str = "rss",
        source_config: str = "{}",
        display_order: int = 0,
    ) -> Board:
        board = Board(
            slug=slug,
            name=name,
            icon=icon,
            description=description,
            system_prompt=system_prompt,
            source_type=source_type,
            source_config=source_config,
            display_order=display_order,
        )
        session.add(board)
        await session.commit()
        await session.refresh(board)
        return board

    async def update_board(
        self, session: AsyncSession, slug: str, updates: dict
    ) -> Board | None:
        board = await self.get_board_by_slug(session, slug)
        if not board:
            return None
        allowed = {
            "name", "icon", "description", "system_prompt",
            "source_type", "source_config", "display_order", "is_active",
        }
        for key, value in updates.items():
            if key in allowed and value is not None:
                setattr(board, key, value)
        await session.commit()
        await session.refresh(board)
        return board

    async def delete_board(self, session: AsyncSession, slug: str) -> bool:
        """
        Soft delete (mark inactive). The default board cannot be deleted.
        """
        board = await self.get_board_by_slug(session, slug)
        if not board or board.is_default:
            return False
        board.is_active = False
        await session.commit()
        return True


db_service = DBService()
