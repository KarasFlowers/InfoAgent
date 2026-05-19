"""
Simple API Key authentication middleware.

When ``API_KEY`` is set in the environment (or .env), all API requests
must include the header ``X-API-Key: <key>``.  Requests without a matching
key receive a 403 response.

When ``API_KEY`` is unset / empty, the middleware is completely inert —
all requests pass through.  This keeps the local development experience
unchanged.

Routes that are always public (no key required):
  - GET /              (homepage)
  - GET /static/*      (static assets)
  - GET /api/v1/ping   (health check)
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# Paths that never require authentication.
_PUBLIC_PATH_PREFIXES = ("/", "/static", "/api/v1/ping")


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Reject requests that don't carry the correct ``X-API-Key`` header."""

    def __init__(self, app, api_key: str | None):
        super().__init__(app)
        self._api_key = api_key

    async def dispatch(self, request: Request, call_next):
        # No key configured → everything is open
        if not self._api_key:
            return await call_next(request)

        # Public paths bypass auth
        if self._is_public_path(request.url.path):
            return await call_next(request)

        # Check header
        provided = request.headers.get("X-API-Key", "")
        if provided == self._api_key:
            return await call_next(request)

        logger.warning(
            "Rejected request %s %s — invalid or missing X-API-Key",
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=403,
            content={"detail": "Invalid or missing API key"},
        )

    @staticmethod
    def _is_public_path(path: str) -> bool:
        for prefix in _PUBLIC_PATH_PREFIXES:
            if path == prefix or path.startswith(prefix + ("/" if prefix != "/" else "")):
                return True
        return False
