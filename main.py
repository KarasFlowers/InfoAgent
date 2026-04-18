from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager

from app.api.router import api_router
from app.api.rag_router import rag_router
from app.core.config import settings
from app.core.db import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    # This runs when the server starts up
    await init_db()
    
    # 自动清理历史缓存 (启动时执行)
    from app.core.db import get_session
    from app.services.db_service import db_service
    try:
        async for session in get_session():
            await db_service.cleanup_old_data(session, days_to_keep=settings.HISTORY_DAYS_TO_KEEP)
            break
    except Exception as e:
        print(f"Startup cleanup failed: {e}")
        
    yield

app = FastAPI(
    title="InfoAgent API",
    description="Backend for the daily LLM information aggregation agent.",
    version="0.1.0",
    lifespan=lifespan
)

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
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    # Updated signature for Starlette/FastAPI 0.111.0+ compatibility
    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={}
    )
