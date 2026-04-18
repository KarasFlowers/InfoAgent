import json
from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_path(value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        resolved = path
    else:
        resolved = (PROJECT_ROOT / path).resolve()

    resolved.mkdir(parents=True, exist_ok=True)
    return str(resolved)


def _resolve_sqlite_uri(value: str) -> str:
    prefix = "sqlite+aiosqlite:///"
    if not value.startswith(prefix):
        return value

    db_path = value[len(prefix):]
    if not db_path:
        return value

    resolved = Path(db_path)
    if not resolved.is_absolute():
        resolved = (PROJECT_ROOT / resolved).resolve()

    resolved.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{resolved.as_posix()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    PROJECT_NAME: str = "InfoAgent"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    
    # RSS feeds — must be freely accessible (no paywall) for RAG to scrape full text
    RSS_FEEDS: list[str] = [
        "https://news.ycombinator.com/rss",
        "https://feeds.arstechnica.com/arstechnica/index",
        "https://huggingface.co/blog/feed.xml",
        "https://openai.com/news/rss.xml",
        "https://www.theverge.com/rss/index.xml",
        "https://techcrunch.com/feed/",
        "https://linux.do/top.rss",
        "https://sspai.com/feed",
        "https://www.solidot.org/index.rss",
        "https://36kr.com/feed",
    ]
    
    # LLM Configuration
    DEEPSEEK_API_KEY: str | None = None
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    
    # Database
    SQLALCHEMY_DATABASE_URI: str = "sqlite+aiosqlite:///./data/sqlite/infoagent.db"
    
    # Retention Policy
    HISTORY_DAYS_TO_KEEP: int = 7
    
    # RAG Vector Store
    CHROMA_DB_DIR: str = "./data/chroma"
    
    # Redis Cache
    REDIS_URL: str = "redis://localhost:6379"

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    CORS_ALLOW_CREDENTIALS: bool = True

    @field_validator("SQLALCHEMY_DATABASE_URI", mode="before")
    @classmethod
    def resolve_database_uri(cls, value: str) -> str:
        return _resolve_sqlite_uri(value)

    @field_validator("CHROMA_DB_DIR", mode="before")
    @classmethod
    def resolve_chroma_dir(cls, value: str) -> str:
        return _resolve_path(value)

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):
                return json.loads(raw)
            return [origin.strip() for origin in raw.split(",") if origin.strip()]
        return value

settings = Settings()
