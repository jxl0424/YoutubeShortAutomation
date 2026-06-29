"""Structured logging configuration built on structlog.

Provides JSON (production) or console (dev) rendering plus a ``log_duration``
context manager used throughout the pipeline to record stage timings.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog

_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


def configure_logging(level: str = "INFO", *, json_logs: bool = True) -> None:
    """Configure structlog. Safe to call more than once."""
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            _LEVELS.get(level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)


@contextmanager
def log_duration(
    logger: Any, event: str, **fields: Any
) -> Iterator[dict[str, Any]]:
    """Log the wall-clock duration of a block under ``event``.

    Yields a mutable dict; values added to it are merged into the final log
    line (e.g. counts discovered during the block).
    """
    extra: dict[str, Any] = {}
    start = time.perf_counter()
    try:
        yield extra
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(event, duration_ms=duration_ms, **fields, **extra)
