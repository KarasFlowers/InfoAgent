"""
conftest.py - Shared fixtures for Argos tests.

Provides:
  - An async FastAPI test client via httpx.AsyncClient
  - Database initialization for test isolation
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from main import app
from app.core.db import init_db


@pytest_asyncio.fixture(scope="session")
async def client():
    """Provide an async test client that talks directly to the ASGI app."""
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
