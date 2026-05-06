# First-run bootstrap: ensure .env + data dirs exist before anything reads config
from app.core.first_run import run_first_time_checks
run_first_time_checks()

from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.router import api_router
from app.api.rag_router import rag_router
from app.core.config import settings
from app.core.db import init_db
from app.core.logging_config import setup_logging, new_trace_id

# ---- Initialise structured logging BEFORE anything else logs ----
setup_logging()
logger = structlog.get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
WEB_ROOT = PROJECT_ROOT / "app" / "web"
STATIC_DIR = WEB_ROOT / "static"
TEMPLATES_DIR = WEB_ROOT / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    from app.services import rag_service
    from app.core.scheduler import start_scheduler, shutdown_scheduler

    # This runs when the server starts up
    await init_db()

    # Start APScheduler (handles periodic cleanup + future jobs)
    start_scheduler()

    # Start background ingest workers
    worker_tasks: list[asyncio.Task] = []
    if settings.RAG_BACKGROUND_INGEST_ENABLED:
        for i in range(settings.RAG_BACKGROUND_INGEST_WORKERS):
            task = asyncio.create_task(rag_service.ingest_worker_loop(worker_id=i))
            worker_tasks.append(task)

    logger.info("application_started")
    yield

    # Shutdown scheduler
    shutdown_scheduler()

    # Close shared httpx client
    from app.core.http_client import close_http_client
    await close_http_client()

    # Shutdown: send sentinel per worker, then wait
    for _ in worker_tasks:
        try:
            rag_service._ingest_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
    for task in worker_tasks:
        task.cancel()
    if worker_tasks:
        await asyncio.gather(*worker_tasks, return_exceptions=True)
    logger.info("application_stopped")

app = FastAPI(
    title="InfoAgent API",
    description="Backend for the daily LLM information aggregation agent.",
    version="0.1.0",
    lifespan=lifespan
)

# ---- TraceID Middleware ----
class TraceIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        tid = new_trace_id()
        response = await call_next(request)
        response.headers["X-Trace-ID"] = tid
        return response

app.add_middleware(TraceIDMiddleware)

# Set up CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS and "*" not in settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(api_router, prefix="/api/v1")
app.include_router(rag_router, prefix="/api/v1")

# Mount Static Files and Templates
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    # Updated signature for Starlette/FastAPI 0.111.0+ compatibility
    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={}
    )
