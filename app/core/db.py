from collections.abc import AsyncGenerator
from sqlmodel import SQLModel
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import settings

# Create the async engine
# connect_args is needed for SQLite to support multi-threading
engine = create_async_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    echo=False,
    connect_args={"check_same_thread": False}
)


# SQLite does not enforce foreign keys (and therefore ondelete="CASCADE") by
# default. Turn it on for every new DBAPI connection so referential integrity
# and cascading deletes match what the models declare.
@event.listens_for(engine.sync_engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:
        # Not a SQLite connection (or pragma unsupported). Silently ignore.
        pass


# Module-level async session factory (preferred over constructing per-request)
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def _ensure_legacy_columns(conn) -> None:
    result = await conn.exec_driver_sql("PRAGMA table_info(dailysummary)")
    columns = {row[1] for row in result.fetchall()}
    if "stats_json" not in columns:
        await conn.exec_driver_sql("ALTER TABLE dailysummary ADD COLUMN stats_json VARCHAR")
    if "board_id" not in columns:
        await conn.exec_driver_sql("ALTER TABLE dailysummary ADD COLUMN board_id INTEGER")

    persona_result = await conn.exec_driver_sql("PRAGMA table_info(userpersona)")
    persona_columns = {row[1] for row in persona_result.fetchall()}
    if "board_id" not in persona_columns:
        await conn.exec_driver_sql("ALTER TABLE userpersona ADD COLUMN board_id INTEGER")

    # Board table: new columns added in P1 (schedule + notify_channels)
    board_result = await conn.exec_driver_sql("PRAGMA table_info(board)")
    board_columns = {row[1] for row in board_result.fetchall()}
    if "schedule" not in board_columns:
        await conn.exec_driver_sql("ALTER TABLE board ADD COLUMN schedule TEXT NOT NULL DEFAULT ''")
    if "notify_channels" not in board_columns:
        await conn.exec_driver_sql("ALTER TABLE board ADD COLUMN notify_channels TEXT NOT NULL DEFAULT ''")

    # Fix any rows where schedule/notify_channels ended up as NULL
    await conn.exec_driver_sql("UPDATE board SET schedule = '' WHERE schedule IS NULL")
    await conn.exec_driver_sql("UPDATE board SET notify_channels = '' WHERE notify_channels IS NULL")


async def _migrate_dailysummary_date_uniqueness(conn) -> None:
    """
    The old schema had ``UNIQUE(date)``. The new schema replaces it with a
    composite ``UNIQUE(board_id, date)``. Drop the legacy single-column index
    if it exists so two boards can both have summaries for the same date.
    """
    indexes = await conn.exec_driver_sql("PRAGMA index_list(dailysummary)")
    for row in indexes.fetchall():
        # row: (seq, name, unique, origin, partial)
        idx_name = row[1]
        is_unique = bool(row[2])
        if not is_unique:
            continue
        cols_res = await conn.exec_driver_sql(f"PRAGMA index_info({idx_name})")
        cols = [c[2] for c in cols_res.fetchall()]
        # Old unique index on just (date) -> drop it (only autoindexes can't be dropped)
        if cols == ["date"] and not idx_name.startswith("sqlite_autoindex_"):
            await conn.exec_driver_sql(f"DROP INDEX IF EXISTS {idx_name}")

    # Ensure composite uniqueness exists.
    existing = {row[1] for row in (await conn.exec_driver_sql("PRAGMA index_list(dailysummary)")).fetchall()}
    if "ux_dailysummary_board_date" not in existing:
        try:
            await conn.exec_driver_sql(
                "CREATE UNIQUE INDEX ux_dailysummary_board_date "
                "ON dailysummary(board_id, date)"
            )
        except Exception:
            # If pre-existing data violates the constraint (shouldn't in fresh installs),
            # leave uniqueness enforcement to a later migration rather than failing startup.
            pass


async def _seed_default_board(conn) -> None:
    """
    Ensure a default board exists. If the boards table is empty, insert a
    "tech" board populated from settings.RSS_FEEDS, and backfill any existing
    DailySummary / UserPersona rows with its id.
    """
    import json as _json
    from app.core.config import settings as _settings

    count_row = await conn.exec_driver_sql("SELECT COUNT(*) FROM board")
    existing = count_row.fetchone()[0]
    if existing > 0:
        return

    default_prompt = (
        "You are the Chief Editor of Argos's '科技快讯' board. "
        "Curate today's most important technology, AI, programming, and "
        "industry news for a busy CS student."
    )
    default_config = _json.dumps({"feeds": list(_settings.RSS_FEEDS)})
    result = await conn.exec_driver_sql(
        "INSERT INTO board (slug, name, icon, description, system_prompt, "
        "source_type, source_config, display_order, is_active, is_default, schedule, notify_channels, created_at) "
        "VALUES ('tech', '科技快讯', '📰', '默认科技 / AI 简报', ?, 'rss', ?, 0, 1, 1, '', '', CURRENT_TIMESTAMP)",
        (default_prompt, default_config),
    )
    default_id_row = await conn.exec_driver_sql("SELECT id FROM board WHERE slug = 'tech'")
    default_id = default_id_row.fetchone()[0]

    # Backfill existing summaries and personas.
    await conn.exec_driver_sql(
        "UPDATE dailysummary SET board_id = ? WHERE board_id IS NULL",
        (default_id,),
    )


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


async def _migrate_json_columns(conn) -> None:
    """
    Convert string-based JSON columns (key_points, tags, stats_json) to
    native JSON.  In SQLite the storage is TEXT either way, but SQLAlchemy
    needs the values to be actual JSON objects (not double-encoded strings)
    when the column is declared as ``JSON``.

    This is idempotent — rows that are already valid JSON objects are left
    untouched.
    """
    import json as _json

    # --- NewsItem.key_points ---
    rows = await conn.exec_driver_sql(
        "SELECT id, key_points FROM newsitem WHERE typeof(key_points) = 'text'"
    )
    for row in rows.fetchall():
        rid, raw = row
        try:
            parsed = _json.loads(raw)
            if not isinstance(parsed, list):
                parsed = [str(parsed)]
            await conn.exec_driver_sql(
                "UPDATE newsitem SET key_points = ? WHERE id = ?",
                (_json.dumps(parsed, ensure_ascii=False), rid),
            )
        except (_json.JSONDecodeError, TypeError):
            pass

    # --- NewsItem.tags ---
    rows = await conn.exec_driver_sql(
        "SELECT id, tags FROM newsitem WHERE typeof(tags) = 'text'"
    )
    for row in rows.fetchall():
        rid, raw = row
        try:
            parsed = _json.loads(raw)
            if not isinstance(parsed, list):
                parsed = []
            await conn.exec_driver_sql(
                "UPDATE newsitem SET tags = ? WHERE id = ?",
                (_json.dumps(parsed, ensure_ascii=False), rid),
            )
        except (_json.JSONDecodeError, TypeError):
            pass

    # --- DailySummary.stats_json ---
    rows = await conn.exec_driver_sql(
        "SELECT id, stats_json FROM dailysummary WHERE stats_json IS NOT NULL AND typeof(stats_json) = 'text'"
    )
    for row in rows.fetchall():
        rid, raw = row
        try:
            parsed = _json.loads(raw)
            if not isinstance(parsed, dict):
                parsed = {}
            await conn.exec_driver_sql(
                "UPDATE dailysummary SET stats_json = ? WHERE id = ?",
                (_json.dumps(parsed, ensure_ascii=False), rid),
            )
        except (_json.JSONDecodeError, TypeError):
            pass


async def init_db():
    """Create the database tables if they don't exist."""
    async with engine.begin() as conn:
        # Import models here to ensure they form part of SQLModel.metadata
        from app.models.domain import (
            Board,
            DailySummary,
            NewsItem,
            UserFeedback,
            ChatMessage,
            UserPersona,
        )
        await conn.run_sync(SQLModel.metadata.create_all)
        await _ensure_legacy_columns(conn)
        await _migrate_dailysummary_date_uniqueness(conn)
        await _seed_default_board(conn)
        await _ensure_feedback_uniqueness(conn)
        await _migrate_json_columns(conn)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to provide a database session to FastAPI endpoints."""
    async with AsyncSessionLocal() as session:
        yield session
