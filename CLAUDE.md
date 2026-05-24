# Argos — AI Daily Tech Briefing

## Overview

Argos is a FastAPI-based daily technology briefing assistant powered by LLM and RAG. It aggregates content from multiple sources (RSS, HackerNews, Reddit, GitHub), applies AI scoring and summarization, and delivers personalized daily briefings through multiple notification channels.

## Architecture

```
main.py                    # FastAPI app entry, lifespan, middleware
app/
  api/
    router.py              # All REST endpoints (summary, briefing, persona, admin, etc.)
    rag_router.py           # RAG-specific endpoints (chat, ingest)
  core/
    config.py              # Pydantic Settings (env vars, defaults)
    db.py                  # Async SQLAlchemy engine, session factory, migrations, seeding
    scheduler.py           # APScheduler background jobs with TaskRun tracking
    auth.py                # API key middleware
    logging_config.py      # Structured logging setup
  models/
    domain.py              # SQLModel tables (Board, NewsItem, DailySummary, Source, TaskRun, etc.)
    schemas.py             # Pydantic request/response schemas with LLM output tolerance
  services/
    llm/
      client.py            # Unified LLM client with CircuitBreaker + multi-tier routing
      summary.py           # Daily summary generation pipeline
      scoring.py           # LLM-based article quality scoring with fallback
      weekly.py            # Weekly report generation
      wizard.py            # Conversational board wizard
    rag/                   # RAG pipeline (bi-encoder, cross-encoder, ChromaDB, BM25)
    filtering_service.py   # Rule-based content quality filtering (blacklist + heuristics)
    clustering_service.py  # Event grouping engine (Bi-Encoder + Jaccard fallback)
    source_health_service.py  # RSS source health monitoring
    dedup_service.py       # URL normalization + semantic deduplication
    interest_filter.py     # Persona-based interest pre-filtering
    notification/          # Multi-channel notifications (email, webhook, bark, telegram)
    source_adapters/       # Multi-source adapters (RSS, HN, Reddit, GitHub, pure-LLM)
  web/
    templates/             # Jinja2 HTML templates (index.html, feed.html)
    static/                # CSS, JS assets
alembic/                   # Database migrations (Alembic)
tests/                     # Pytest test suite
```

## Key Business Constraints

- **Board System**: Each board has independent sources, prompts, schedules, notification channels, and perspectives. Default board = tech.
- **Multi-tier LLM**: "fast" tier for scoring/filtering, "smart" tier for summarization. CircuitBreaker prevents cascade failures.
- **Graceful degradation**: If LLM fails, fallback summaries are generated from raw article titles/links.
- **Personalization**: UserPersona + UserMemory + feedback-driven interest extraction. Preferences influence scoring but don't dominate (30-40% cap).

## Development Principles

1. **Never break existing API contracts** — `DailySummaryResponse` is consumed by multiple clients.
2. **SQLite-first** — all DB operations use async aiosqlite. Alembic migrations must be SQLite-compatible (no ALTER COLUMN type changes).
3. **Defensive LLM parsing** — `model_validator` in schemas normalizes common LLM output variations (title→headline, string→list, missing fields).
4. **Background jobs via APScheduler** — all jobs wrapped with `track_task_run()` for observability.
5. **Best-effort health logging** — RSS fetch failures are recorded but never block the pipeline.

## Testing

```bash
# Run all tests
$env:PYTHONPATH="."; venv\Scripts\python.exe -m pytest tests/ -v

# Run specific test suites
pytest tests/test_circuit_breaker.py     # CircuitBreaker state machine
pytest tests/test_filtering_service.py   # Blacklist, low-signal, domain filters
pytest tests/test_clustering_service.py  # Fingerprint, Jaccard overlap
pytest tests/test_schemas_tolerance.py   # LLM output tolerance validation
```

## Database Migrations

```bash
# Generate a new migration after model changes
$env:PYTHONPATH="."; venv\Scripts\python.exe -m alembic revision --autogenerate -m "description"

# IMPORTANT: Review generated migration and remove SQLite-incompatible ALTER COLUMN ops
# Then add `import sqlmodel.sql.sqltypes` if AutoString columns are used

# Apply migrations
$env:PYTHONPATH="."; venv\Scripts\python.exe -m alembic upgrade head

# Stamp current state (when tables already exist from create_all)
$env:PYTHONPATH="."; venv\Scripts\python.exe -m alembic stamp head
```

## Environment Variables

Key settings (see `app/core/config.py` for full list):

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | Primary LLM API key |
| `OPENAI_BASE_URL` | LLM API base URL |
| `OPENAI_MODEL` | Default model name |
| `API_KEY` | Optional API key for auth |
| `DATABASE_URL` | SQLite path (default: `data/argos.db`) |
| `REDIS_URL` | Redis URL for caching |
| `RAG_BACKGROUND_INGEST_ENABLED` | Enable background RAG ingestion |

## Key Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/summary` | Daily summary (with caching + generation) |
| `GET /api/v1/briefing` | Structured briefing with sections + clusters |
| `POST /api/v1/briefing/refine` | Refine existing briefing with instruction |
| `GET /api/v1/feed` | RSS 2.0 XML feed |
| `GET /feed` | Public SEO HTML feed page |
| `GET /api/v1/admin/tasks` | Background task runs |
| `GET /api/v1/admin/sources/health` | Source health dashboard |
| `GET /api/v1/ping` | Health check |

## Admin Access

Admin endpoints (`/admin/*`) are protected by the same `API_KEY` middleware as other endpoints. No separate admin auth — set `API_KEY` env var to enable.
