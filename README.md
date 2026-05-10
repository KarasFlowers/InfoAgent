# Argos

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-green.svg)](https://fastapi.tiangolo.com)

**[English](README.md) | [Chinese](README_zh.md)**

> An intelligent daily tech briefing assistant powered by LLM and RAG.

Argos is a FastAPI-based daily tech briefing application that aggregates content from multiple sources (RSS, Hacker News, Reddit, GitHub, or pure LLM), uses any OpenAI-compatible LLM to curate structured summaries, and provides article-level RAG chat with feedback-driven personalization.

## Features

- **Multi-source aggregation** - RSS feeds, Hacker News top stories, Reddit posts, GitHub events/releases, or pure-LLM generated content
- **Board system** - Create custom sections (boards) each with its own source type, system prompt, and persona
- **Board Wizard** - AI-guided interactive wizard to configure new boards
- **LLM-driven daily briefing** - Structured summaries with categories, key points, and tags
- **Article Q&A via RAG** - Hybrid retrieval (Bi-Encoder + BM25) with Cross-Encoder reranking
- **Personalized recommendations** - Explicit like/dislike feedback for tailored content
- **Cross-source deduplication** - URL normalization + AI semantic deduplication
- **Multi-channel notifications** - Push briefings via email, webhook, Bark (iOS), or Telegram
- **MCP Server** - Expose all capabilities to AI assistants via Model Context Protocol
- **Local persistence** - SQLite, ChromaDB, and Redis cache for offline-first design

## Demo

<!-- Add screenshots or GIFs here -->
```
Coming soon...
```

## Quick Start

### Prerequisites

- Python 3.11+
- [Redis](https://redis.io/) (for caching)
- An OpenAI-compatible LLM API key (e.g. [DeepSeek](https://platform.deepseek.com/), OpenAI, etc.)

### Docker (Recommended)

```bash
# 1. Clone the repository
git clone https://github.com/KarasFlowers/Argos.git
cd Argos

# 2. Configure environment
cp .env.template .env
# Edit .env and set LLM_API_KEY (or DEEPSEEK_API_KEY for legacy compat)

# 3. Start the stack
docker compose up -d

# 4. Open in browser
# Visit http://127.0.0.1:8000
```

### One-Click Start (Recommended for Local)

The project ships with launcher scripts that handle **venv creation, dependency installation, .env setup, Redis, model download, and browser opening** automatically:

```bash
# macOS / Linux
chmod +x scripts/start.sh
./scripts/start.sh

# Windows — double-click or run:
scripts\Open_Web_Dashboard.bat
```

On first run the script will:
1. Create a virtual environment and install dependencies
2. Prompt you to enter your LLM API key (creates `.env` automatically)
3. Check/start Redis
4. Pre-download RAG embedding models (~650 MB, one-time)
5. Start the backend and open the dashboard in your browser

### Manual Setup

<details>
<summary>Click to expand step-by-step instructions</summary>

```bash
# 1. Clone the repository
git clone https://github.com/KarasFlowers/Argos.git
cd Argos

# 2. Create and activate a virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.template .env
# Edit .env and set LLM_API_KEY (or DEEPSEEK_API_KEY for legacy compat)

# 5. (Optional) Pre-download RAG models to avoid first-request delay
python scripts/download_models.py

# 6. Start Redis (if not already running)
# Windows: the .bat launcher handles this automatically
# Linux / macOS: redis-server --daemonize yes

# 7. Start the application
uvicorn main:app --reload

# 8. Open http://127.0.0.1:8000 in your browser
```

</details>

## Configuration

Copy `.env.template` to `.env` and configure your settings. At minimum, you need to set `LLM_API_KEY` (or the legacy `DEEPSEEK_API_KEY`).

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_API_KEY` | **Yes** | - | API key for any OpenAI-compatible LLM provider |
| `LLM_MODEL` | No | `deepseek-chat` | Model name to use for all LLM calls |
| `LLM_BASE_URL` | No | `https://api.deepseek.com/v1` | Base URL of the LLM API |
| `LLM_TIMEOUT` | No | `180` | Request timeout in seconds |
| `LLM_MAX_RETRIES` | No | `1` | Max retries on transient failures |
| `DEEPSEEK_API_KEY` | No | - | Legacy alias — used as fallback when `LLM_API_KEY` is unset |
| `SQLALCHEMY_DATABASE_URI` | No | `sqlite+aiosqlite:///./data/sqlite/argos.db` | Async SQLite database path |
| `CHROMA_DB_DIR` | No | `./data/chroma` | ChromaDB persistent storage path |
| `CORS_ORIGINS` | No | `http://localhost:5173,...` | Comma-separated allowed frontend origins |
| `GITHUB_TOKEN` | No | - | GitHub personal access token (increases rate limit to 5000 req/hr) |
| `HN_FETCH_TOP_STORIES` | No | `30` | Number of top Hacker News stories to fetch |
| `HN_MIN_SCORE` | No | `100` | Minimum Hacker News score threshold |
| `REDDIT_FETCH_COMMENTS` | No | `5` | Top comments to include per Reddit post |
| `SMTP_HOST` | No | - | SMTP server for email push |
| `SMTP_USER` | No | - | SMTP username |
| `SMTP_PASSWORD` | No | - | SMTP password |
| `EMAIL_SUBSCRIBERS` | No | `[]` | JSON list of subscriber email addresses |
| `DAILY_PUSH_TIME` | No | `08:00` | Daily push time (HH:MM format) |
| `NOTIFY_CHANNELS` | No | `email` | Comma-separated channels: `email,webhook,bark,telegram` |
| `WEBHOOK_URL` | No | - | Generic webhook endpoint (POST JSON) |
| `WEBHOOK_SECRET` | No | - | HMAC-SHA256 signing key for webhook |
| `BARK_URL` | No | - | Bark iOS push URL (e.g. `https://api.day.app/KEY`) |
| `TELEGRAM_BOT_TOKEN` | No | - | Telegram bot token |
| `TELEGRAM_CHAT_ID` | No | - | Telegram chat/group ID to send messages to |

## Board Source Types

Each board has a `source_type` that determines how content is fetched:

| Source Type | Description | Example `source_config` |
|-------------|-------------|------------------------|
| `rss` | Pull from RSS feeds | `{"feeds": ["https://hnrss.org/frontpage"]}` |
| `hackernews` | Fetch HN top stories + comments | `{"fetch_top_stories": 30, "min_score": 100}` |
| `reddit` | Fetch Reddit subreddit/user posts | `{"subreddits": [{"subreddit": "LocalLLaMA"}], "fetch_comments": 5}` |
| `github` | Fetch GitHub user events & repo releases | `{"users": ["openai"], "repos": [{"owner": "openai", "repo": "whisper"}]}` |
| `multi` | Combine multiple source types in parallel | `{"sources": {"rss": {"feeds": [...]}, "hackernews": {"min_score": 50}}}` |
| `pure_llm` | LLM generates original content (no external data) | `{"items_per_day": 5, "style": "fun facts"}` |

## MCP Server (AI Agent Integration)

Argos exposes its capabilities as an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server, allowing AI assistants like Claude, Cursor, and Windsurf to directly query your briefings, ask RAG questions, and manage preferences.

### Available Tools

| Tool | Description |
|------|-------------|
| `get_daily_summary` | Read today's briefing for a board |
| `generate_summary` | Trigger summary generation |
| `ask_article` | RAG Q&A about any ingested article |
| `search_news` | Keyword search across news history |
| `list_boards` | List all content boards |
| `add_feedback` | Like/dislike articles for personalization |
| `get_user_interests` | View current persona/preferences |
| `get_system_status` | System health and config info |

### Usage

```bash
# stdio transport (for IDE integrations like Cursor/Windsurf)
python mcp_server.py

# Or add to your MCP client config (e.g. claude_desktop_config.json):
{
  "mcpServers": {
    "argos": {
      "command": "python",
      "args": ["path/to/Argos/mcp_server.py"]
    }
  }
}
```

## Architecture

The service layer uses a **facade pattern** to keep imports backward-compatible while allowing large modules to be split internally:

### Service Facades

| Facade | Location | Exports |
|--------|----------|---------|
| `llm_service.py` | `app/services/llm/` | `LLMService`, `llm_service` |
| `rag_service.py` | `app/services/rag/_core.py` | All public RAG functions |
| `db_service.py` | `app/services/repositories/` | `DBService`, `db_service` |

### Internal Structure

- **LLM Service**: `ScoringMixin`, `SummaryMixin`, `WeeklyMixin`, `WizardMixin`
- **RAG Service**: Hybrid retrieval pipeline with Bi-Encoder + BM25 + Cross-Encoder reranking
- **DB Service**: `SummaryRepo`, `PersonaRepo`, `BoardRepo`

> **Note**: New code should import from concrete subpackages (e.g., `from app.services.llm import LLMService`) rather than facades.

## Project Structure

```text
.
├── app/
│   ├── api/                    # FastAPI routes (main + RAG)
│   ├── core/                   # Config, DB, HTTP client, scheduler
│   ├── models/                 # SQLModel + Pydantic schemas
│   ├── scrapers/               # HN / Reddit / GitHub scrapers
│   ├── services/
│   │   ├── source_adapters/    # Pluggable board source adapters
│   │   ├── llm/                # LLM scoring, summary, wizard
│   │   ├── rag/                # RAG pipeline
│   │   ├── repositories/      # Database repositories
│   │   ├── chat_history_service.py
│   │   ├── dedup_service.py
│   │   ├── email_service.py
│   │   ├── learning_service.py
│   │   ├── metrics_service.py
│   │   └── rss_service.py
│   └── web/                    # Jinja templates + static assets
├── data/
│   ├── chroma/                 # Local vector store
│   └── sqlite/                 # Local SQLite database
├── docs/                      # Project documentation
├── logs/                      # Runtime logs
├── scripts/                   # Windows launcher + Redis bootstrap
├── tests/                     # Test suite
└── tools/                     # Bundled tools (Redis, etc.)
```

## Key Files

| Path | Description |
|------|-------------|
| `main.py` | Application entry point |
| `app/` | Main application package |
| `app/web/static/` | Frontend static assets |
| `app/web/templates/` | Jinja2 HTML templates |
| `data/sqlite/argos.db` | SQLite database |
| `data/chroma/` | ChromaDB vector store |
| `scripts/Open_Web_Dashboard.bat` | Windows one-click launcher |
| `scripts/start.sh` | macOS / Linux one-click launcher |
| `scripts/download_models.py` | Pre-download RAG embedding models |

## Tech Stack

- **Backend**: FastAPI, SQLModel, APScheduler
- **LLM**: Any OpenAI-compatible API via configurable `LLMClient` (DeepSeek, OpenAI, etc.)
- **RAG**: Sentence Transformers, ChromaDB, BM25
- **Database**: SQLite (async), Redis (cache)
- **Scraping**: httpx, feedparser, BeautifulSoup, trafilatura

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

Made with by [KarasFlowers](https://github.com/KarasFlowers)
