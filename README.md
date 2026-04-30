# InfoAgent

InfoAgent is a FastAPI-based daily tech briefing app. It aggregates content from multiple sources (RSS, Hacker News, Reddit, GitHub, or pure LLM), asks DeepSeek to curate a structured summary, and provides article-level RAG chat with feedback-driven personalization.

## Features

- **Multi-source aggregation** — RSS feeds, Hacker News top stories, Reddit posts, GitHub events/releases, or pure-LLM generated content
- **Board system** — Create custom sections (boards) each with its own source type, system prompt, and persona
- **Board Wizard** — AI-guided interactive wizard to configure new boards
- **LLM-driven daily briefing** with categories, key points, and tags
- **Article overview and follow-up Q&A** via RAG (Bi-Encoder + BM25 hybrid retrieval, Cross-Encoder rerank)
- **Explicit like/dislike feedback** for personalized reranking
- **Cross-source deduplication** — URL normalization + AI semantic dedup
- **Daily email push** — automatically send briefings to subscribers
- **Local persistence** with SQLite, ChromaDB, and Redis cache

## Quick Start

### Docker

1. Copy `.env.template` to `.env` and fill in your API key.
2. Start the stack:

```bash
docker compose up -d
```

3. Open `http://127.0.0.1:8000`.

### Local Development

1. Create and activate a virtual environment:

```bash
python -m venv venv
# Windows
venv\Scripts\activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the app:

```bash
uvicorn main:app --reload
```

> Windows one-click: double-click `scripts\Open_Web_Dashboard.bat`. It auto-starts Redis, launches the backend, waits for `/api/v1/ping` to become healthy, and opens the dashboard.

## Configuration

Copy `.env.template` to `.env` and set at minimum `DEEPSEEK_API_KEY`.

| Variable | Required | Default | Description |
|---|---|---|---|
| `DEEPSEEK_API_KEY` | **Yes** | — | DeepSeek API key for LLM summarization and RAG |
| `SQLALCHEMY_DATABASE_URI` | No | `sqlite+aiosqlite:///./data/sqlite/infoagent.db` | Async SQLite DB path |
| `CHROMA_DB_DIR` | No | `./data/chroma` | ChromaDB persistent store path |
| `CORS_ORIGINS` | No | `http://localhost:5173,...` | Comma-separated allowed frontend origins |
| `GITHUB_TOKEN` | No | — | GitHub personal access token (increases rate limit) |
| `HN_FETCH_TOP_STORIES` | No | `30` | How many top HN stories to fetch |
| `HN_MIN_SCORE` | No | `100` | Minimum HN score threshold |
| `REDDIT_FETCH_COMMENTS` | No | `5` | How many top comments to include per Reddit post |
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD` | No | — | Email push configuration (optional) |
| `EMAIL_SUBSCRIBERS` | No | `[]` | JSON list of subscriber email addresses |
| `DAILY_PUSH_TIME` | No | `08:00` | Cron-like time for daily email dispatch |

## Board Source Types

Each board has a `source_type` that determines how content is fetched:

| Source Type | Description | Example `source_config` |
|---|---|---|
| `rss` | Pull from RSS feeds | `{"feeds": ["https://hnrss.org/frontpage"]}` |
| `hackernews` | Fetch HN top stories + comments | `{"fetch_top_stories": 30, "min_score": 100}` |
| `reddit` | Fetch Reddit subreddit/user posts | `{"subreddits": [{"subreddit": "LocalLLaMA"}], "fetch_comments": 5}` |
| `github` | Fetch GitHub user events & repo releases | `{"users": ["openai"], "repos": [{"owner": "openai", "repo": "whisper"}]}` |
| `multi` | Combine multiple source types in parallel | `{"sources": {"rss": {"feeds": [...]}, "hackernews": {"min_score": 50}}}` |
| `pure_llm` | LLM generates original content (no external data) | `{"items_per_day": 5, "style": "冷知识"}` |

## Architecture

The service layer uses a **facade pattern** to keep imports backward-compatible while allowing large modules to be split internally:

- `app/services/llm_service.py` — facade re-exporting `LLMService` and `llm_service` from `app/services/llm/`
  - Internal mixins: `ScoringMixin`, `SummaryMixin`, `WeeklyMixin`, `WizardMixin`
- `app/services/rag_service.py` — facade re-exporting all public names from `app/services/rag/_core.py`
- `app/services/db_service.py` — facade re-exporting `DBService` and `db_service` from `app/services/repositories/`
  - Internal repos: `SummaryRepo`, `PersonaRepo`, `BoardRepo`

New code should import from the concrete subpackage (e.g. `from app.services.llm import LLMService`) rather than the facade.

## Project Layout

```text
.
├─ app/
│  ├─ api/              # FastAPI routes (main + RAG)
│  ├─ core/             # Config, DB, shared HTTP client, scheduler
│  ├─ models/           # SQLModel + Pydantic + source config schemas
│  ├─ scrapers/         # HN / Reddit / GitHub scrapers
│  ├─ services/
│  │  ├─ source_adapters/  # Pluggable board source adapters
│  │  ├─ llm/              # LLM scoring, summary, wizard (facade: llm_service.py)
│  │  ├─ rag/              # RAG pipeline (facade: rag_service.py)
│  │  ├─ repositories/    # SummaryRepo, PersonaRepo, BoardRepo (facade: db_service.py)
│  │  ├─ chat_history_service.py
│  │  ├─ dedup_service.py
│  │  ├─ email_service.py
│  │  ├─ learning_service.py
│  │  ├─ metrics_service.py
│  │  └─ rss_service.py
│  └─ web/              # Jinja templates and static assets
├─ data/
│  ├─ chroma/           # Local vector store
│  └─ sqlite/           # Local SQLite database
├─ docs/                # Project notes
├─ logs/                # Local runtime logs
├─ scripts/             # Windows launcher + Redis bootstrap
├─ tests/               # API tests
└─ tools/               # Local bundled tools such as Redis
```

## Important Paths

- Web entry: `main.py`
- App package: `app/`
- Frontend assets: `app/web/static/`
- Templates: `app/web/templates/`
- SQLite DB: `data/sqlite/infoagent.db`
- Chroma store: `data/chroma/`
- Windows launcher: `scripts/Open_Web_Dashboard.bat`

## License

MIT
