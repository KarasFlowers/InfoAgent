# InfoAgent

InfoAgent is a FastAPI-based daily tech briefing app. It aggregates RSS feeds, asks DeepSeek to curate a structured summary, and provides article-level RAG chat with feedback-driven personalization.

## Features

- Multi-source RSS aggregation for tech and AI news
- LLM-driven daily briefing with categories, key points, and tags
- Article overview and follow-up Q&A via RAG
- Explicit like/dislike feedback for personalized reranking
- Local persistence with SQLite, ChromaDB, and Redis cache

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

## Project Layout

```text
.
├─ app/
│  ├─ api/          # FastAPI routes
│  ├─ core/         # Config, DB, shared utilities
│  ├─ models/       # SQLModel + Pydantic models
│  ├─ services/     # RSS, LLM, RAG, learning, persistence
│  └─ web/          # Jinja templates and static assets
├─ data/
│  ├─ chroma/       # Local vector store
│  └─ sqlite/       # Local SQLite database
├─ docs/            # Project notes
├─ logs/            # Local runtime logs
├─ scripts/         # Windows launcher + Redis bootstrap
├─ tests/           # API tests
└─ tools/           # Local bundled tools such as Redis
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
