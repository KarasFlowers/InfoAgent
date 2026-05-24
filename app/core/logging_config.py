"""
Structured logging configuration using *structlog*.

Usage
-----
Call ``setup_logging()`` once at application startup (before any logger is
created).  Every log line will include:

- ``timestamp`` – ISO-8601
- ``level``     – uppercase log level
- ``logger``    – dotted module path
- ``trace_id``  – per-request UUID (set by the ASGI middleware)

In development the output is coloured key=value; in Docker /
``LOG_FORMAT=json`` it switches to one JSON object per line.
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from contextvars import ContextVar

import structlog

# ContextVar holding the current request's trace id.
trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="-")


def _add_trace_id(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Inject the current request trace_id into every log event."""
    event_dict["trace_id"] = trace_id_ctx.get("-")
    return event_dict


def setup_logging(*, json_output: bool | None = None) -> None:
    """
    Configure structlog + stdlib logging in one shot.

    Parameters
    ----------
    json_output:
        ``True``  → JSON lines (for Docker / log aggregators).
        ``False`` → coloured key=value (for local dev).
        ``None``  → auto-detect from ``LOG_FORMAT`` env var.
    """
    if json_output is None:
        json_output = os.getenv("LOG_FORMAT", "").lower() == "json"

    # Shared processors applied to EVERY log event.
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _add_trace_id,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_output:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer(
            ensure_ascii=False,
        )
    else:
        renderer = structlog.dev.ConsoleRenderer(
            colors=sys.stderr.isatty(),
            pad_level=False,
        )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # Quieten noisy third-party loggers.
    for name in ("httpx", "httpcore", "chromadb", "urllib3", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)


def new_trace_id() -> str:
    """Generate a short trace-id and store it in the context var."""
    tid = uuid.uuid4().hex[:12]
    trace_id_ctx.set(tid)
    return tid
