"""
Prompt template system.

All LLM prompts are stored as ``.md`` files in this package directory.
Use ``get_prompt(key, **vars)`` to load and render a template with Jinja2.

Supported variables depend on the template; common ones include:
  - ``board_name``, ``date``, ``interest_context``
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, Environment, TemplateNotFound

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent


class _FileSystemLoader(BaseLoader):
    """Simple Jinja2 loader reading .md files from the prompts directory."""

    def get_source(self, environment: Environment, template: str):
        path = _PROMPTS_DIR / f"{template}.md"
        if not path.is_file():
            raise TemplateNotFound(template)
        source = path.read_text(encoding="utf-8")
        return source, str(path), lambda: path.stat().st_mtime == path.stat().st_mtime


_env = Environment(loader=_FileSystemLoader(), keep_trailing_newline=True)


@lru_cache(maxsize=32)
def _load_template_cached(key: str):
    """Cache compiled templates (cleared on restart)."""
    return _env.get_template(key)


def get_prompt(key: str, **variables: Any) -> str:
    """Load and render a prompt template.

    Args:
        key: Template name without extension (e.g. "daily_briefing").
        **variables: Jinja2 template variables.

    Returns:
        Rendered prompt string.

    Raises:
        FileNotFoundError: If no matching .md file exists.
    """
    try:
        template = _load_template_cached(key)
        return template.render(**variables)
    except TemplateNotFound:
        raise FileNotFoundError(
            f"Prompt template '{key}' not found at {_PROMPTS_DIR / f'{key}.md'}"
        )


__all__ = ["get_prompt"]
