"""
Structured logging setup for all services.

Two output modes (auto-selected by settings.environment, ADR-021):
- local  → human-readable, colored, aligned — for eyeballing during dev
- ci/prod → JSON, one line per event — for log aggregators (Loki, Datadog)

Usage in each service's app.py (once, at import time):

    from shared.logging.setup import configure_logging
    configure_logging()

Then anywhere:

    import structlog
    log = structlog.get_logger(__name__)
    log.info("chunk_ingested", chunk_id=..., page=...)

Why structlog over stdlib logging:
- First-class structured key-value pairs; no `%`-formatting string soup.
- Bound loggers: `log = log.bind(request_id=...)` carries context into
  every subsequent call without re-passing it.
- Pluggable processors: swapping output format is one line, not a
  re-plumbing of every call site.

Correlation ID note: we don't inject a request_id middleware in v1. When
we do (fastapi request context), it plugs in as a contextvar processor
here — no changes to any call site.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import Processor

from shared.config.settings import settings


# ─────────────────────────────────────────────────────────────
# Processors shared by both modes
# ─────────────────────────────────────────────────────────────
def _add_app_context(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """
    Stamp every log line with the environment and service name (if set
    via `structlog.contextvars`). Keeping this processor at the top of
    the chain means every downstream processor sees a fully-populated
    event_dict.
    """
    event_dict.setdefault("env", settings.environment)
    return event_dict


def _drop_color_message_key(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """
    uvicorn injects a `color_message` key for its access logs. It's noise
    in JSON mode. Drop it unconditionally — the pretty renderer in local
    mode reconstructs color on its own.
    """
    event_dict.pop("color_message", None)
    return event_dict


# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────
def _build_processors(*, json_mode: bool) -> list[Processor]:
    """Shared pre-render processor chain + mode-specific renderer."""
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_app_context,
        _drop_color_message_key,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_mode:
        return [*shared, structlog.processors.JSONRenderer()]

    return [
        *shared,
        structlog.dev.ConsoleRenderer(
            colors=True,
            exception_formatter=structlog.dev.plain_traceback,
        ),
    ]


def configure_logging(force: bool = False) -> None:
    """
    Configure structlog + stdlib logging for the current process.

    Idempotent by default — safe to call from every service module's
    import path. Pass `force=True` in tests if you need to re-configure
    after mutating settings.

    Side effect: routes the stdlib root logger through structlog so
    third-party libraries (openai, httpx, uvicorn) emit structured logs
    too, not raw text.
    """
    # Auto-select mode: local → pretty; ci/prod → JSON (ADR-021).
    json_mode = settings.log_json or settings.environment != "local"

    # stdlib logging config — used by libraries that don't know structlog.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level, logging.INFO),
        force=force,
    )

    structlog.configure(
        processors=_build_processors(json_mode=json_mode),
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level, logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Route stdlib log records through structlog so uvicorn/openai/httpx
    # lines get the same treatment as our own.
    structlog.configure(
        processors=structlog.get_config()["processors"],
        wrapper_class=structlog.get_config()["wrapper_class"],
        logger_factory=structlog.get_config()["logger_factory"],
        cache_logger_on_first_use=structlog.get_config()["cache_logger_on_first_use"],
    )

    _configure_uvicorn_bridge()

    structlog.get_logger(__name__).debug(
        "logging_configured",
        json_mode=json_mode,
        level=settings.log_level,
    )


def _configure_uvicorn_bridge() -> None:
    """
    Route uvicorn's loggers through our handler chain.

    Without this, uvicorn writes plain text to stdout while our services
    write JSON — mixing formats in the same stream. Bridging keeps a
    single output shape per environment.
    """
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        std_logger = logging.getLogger(name)
        std_logger.handlers = []
        std_logger.propagate = True


# ─────────────────────────────────────────────────────────────
# Convenience: one-liner for services
# ─────────────────────────────────────────────────────────────
def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Thin wrapper so services don't import structlog directly.

        from shared.logging.setup import get_logger
        log = get_logger(__name__)
        log.info("ingest_started", pdf=str(settings.source_pdf))

    This is the ONLY logging entry point services should use — it keeps
    the structlog dependency contained to this module.
    """
    return structlog.get_logger(name)


__all__ = [
    "configure_logging",
    "get_logger",
]