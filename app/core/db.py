from collections.abc import AsyncGenerator
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# Create the async engine
# connect_args is needed for SQLite to support multi-threading
engine = create_async_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    echo=False,
    connect_args={"check_same_thread": False}
)


async def _ensure_legacy_columns(conn) -> None:
    result = await conn.exec_driver_sql("PRAGMA table_info(dailysummary)")
    columns = {row[1] for row in result.fetchall()}
    if "stats_json" not in columns:
        await conn.exec_driver_sql("ALTER TABLE dailysummary ADD COLUMN stats_json VARCHAR")


async def _ensure_feedback_uniqueness(conn) -> None:
    duplicate_rows = await conn.exec_driver_sql(
        """
        SELECT article_url
        FROM userfeedback
        GROUP BY article_url
        HAVING COUNT(*) > 1
        """
    )
    duplicates = [row[0] for row in duplicate_rows.fetchall()]

    for article_url in duplicates:
        rows = await conn.exec_driver_sql(
            """
            SELECT id
            FROM userfeedback
            WHERE article_url = ?
            ORDER BY created_at DESC, id DESC
            """,
            (article_url,),
        )
        ids = [row[0] for row in rows.fetchall()]
        for stale_id in ids[1:]:
            await conn.exec_driver_sql("DELETE FROM userfeedback WHERE id = ?", (stale_id,))

    indexes_result = await conn.exec_driver_sql("PRAGMA index_list(userfeedback)")
    existing_indexes = {row[1] for row in indexes_result.fetchall()}
    if "ux_userfeedback_article_url" not in existing_indexes:
        await conn.exec_driver_sql(
            "CREATE UNIQUE INDEX ux_userfeedback_article_url ON userfeedback(article_url)"
        )


async def init_db():
    """Create the database tables if they don't exist."""
    async with engine.begin() as conn:
        # Import models here to ensure they form part of SQLModel.metadata
        from app.models.domain import DailySummary, NewsItem, UserFeedback, ChatMessage, UserPersona
        await conn.run_sync(SQLModel.metadata.create_all)
        await _ensure_legacy_columns(conn)
        await _ensure_feedback_uniqueness(conn)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to provide a database session to FastAPI endpoints."""
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session
